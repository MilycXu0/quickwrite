"""Web server for the Novel Writer Agent.

FastAPI-based web UI for:
- Creating and managing novels
- Generating chapters with custom instructions
- Viewing chapter content
- Controlling the scheduler
- Monitoring system status
"""

import asyncio
import hashlib
import hmac
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from src.config import AppConfig
from src.generation.character_designer import CharacterDesigner
from src.generation.planner import NovelPlanner
from src.generation.plot_outliner import PlotOutliner
from src.generation.quality_checker import QualityChecker
from src.generation.world_builder import WorldBuilder
from src.llm.client import LLMClient
from src.llm.cost_tracker import CostTracker
from src.llm.prompt_manager import PromptManager
from src.publishing.local_publisher import LocalPublisher
from src.scheduler.jobs import (cost_report, generate_evening_chapter,
                                 generate_morning_chapter, health_check, init_jobs,
                                 refresh_trends, weekly_learning)
from src.scheduler.scheduler_service import SchedulerService
from src.storage.database import Database
from src.storage.file_store import FileStore
from src.storage.repositories.chapter_repo import ChapterRepository
from src.storage.repositories.novel_repo import NovelRepository
from src.storage.repositories.trend_repo import TrendRepository
from src.trend_analysis.analyzer import TrendAnalyzer
from src.utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

# ── App Setup ────────────────────────────────────────────

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="Novel Writer Agent", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# ── Auth Configuration ────────────────────────────────────

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SECRET_KEY = os.environ.get("NOVEL_SECRET_KEY", "quickwrite-secret-change-me")
COOKIE_NAME = "qw_token"
COOKIE_MAX_AGE = 86400 * 30  # 30 days


def _make_token(password: str) -> str:
    """Create a signed token from the password."""
    payload = f"{password}:{int(time.time())}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_token(token: str) -> bool:
    """Verify a signed token against the admin password."""
    if not ADMIN_PASSWORD:
        return True  # No password set — allow all access
    try:
        parts = token.rsplit(":", 1)
        if len(parts) != 2:
            return False
        payload, sig = parts
        expected_sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return False
        stored_password = payload.rsplit(":", 1)[0]
        return hmac.compare_digest(stored_password, ADMIN_PASSWORD)
    except Exception:
        return False


def _is_public_path(path: str) -> bool:
    """Paths that don't require authentication."""
    public = ["/static/", "/login", "/api/auth/login", "/api/auth/logout"]
    return any(path.startswith(p) for p in public)


# ── Auth Middleware ───────────────────────────────────────

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse


class AuthMiddleware(BaseHTTPMiddleware):
    """Protect all routes except login and static files."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth if no password configured
        if not ADMIN_PASSWORD:
            return await call_next(request)

        # Allow public paths
        if _is_public_path(request.url.path):
            return await call_next(request)

        # Check auth cookie
        token = request.cookies.get(COOKIE_NAME, "")
        if not token or not _verify_token(token):
            # For API requests, return 401 instead of redirect
            if request.url.path.startswith("/api/"):
                return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
            # For page requests, redirect to login
            login_url = f"/login?next={request.url.path}"
            return RedirectResponse(url=login_url, status_code=302)

        response = await call_next(request)
        return response


app.add_middleware(AuthMiddleware)


def render(template_name: str, context: dict) -> HTMLResponse:
    """Render a Jinja2 template and return HTMLResponse."""
    template = jinja_env.get_template(template_name)
    return HTMLResponse(template.render(**context))

# ── Global App Instance ──────────────────────────────────

_novel_app = None


def get_app():
    """Lazy-initialize the NovelWriterApp."""
    global _novel_app
    if _novel_app is None:
        _novel_app = WebNovelApp()
    return _novel_app


class WebNovelApp:
    """Application class for the web server."""

    def __init__(self):
        self.config = AppConfig()
        setup_logging(log_dir=self.config.log_dir, level=logging.WARNING)

        self.db = Database(db_url=self.config.db_url)
        self.db.initialize()

        self.cost_tracker = CostTracker(
            monthly_budget_usd=self.config.budget.get("monthly_limit_usd", 25.00),
            alert_threshold=self.config.budget.get("alert_threshold", 0.8),
        )

        # LLM client may fail if no API key — defer error to generation time
        try:
            self.llm_client = LLMClient(cost_tracker=self.cost_tracker)
            self._api_ready = True
        except ValueError:
            self.llm_client = None
            self._api_ready = False
            logger.warning("ANTHROPIC_API_KEY not set — generation will not work")

        self.prompt_manager = PromptManager()
        self.file_store = FileStore(output_dir=self.config.output_dir)

        session = self.db.create_session()
        self.novel_repo = NovelRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.trend_repo = TrendRepository(session)
        self._session = session

        if self._api_ready:
            self.world_builder = WorldBuilder(self.llm_client, self.prompt_manager)
            self.character_designer = CharacterDesigner(self.llm_client, self.prompt_manager)
            self.plot_outliner = PlotOutliner(self.llm_client, self.prompt_manager)
            self.quality_checker = QualityChecker(self.llm_client)
            self.trend_analyzer = TrendAnalyzer(
                llm_client=self.llm_client,
                prompt_manager=self.prompt_manager,
                trend_repo=self.trend_repo,
            )
        else:
            self.world_builder = None
            self.character_designer = None
            self.plot_outliner = None
            self.quality_checker = None
            self.trend_analyzer = None

        self.local_publisher = LocalPublisher(self.file_store)

        # Initialize learning system
        from src.learning.knowledge_base import KnowledgeBase
        from src.learning.style_optimizer import StyleOptimizer
        self.knowledge_base = KnowledgeBase()
        self.style_optimizer = StyleOptimizer(self.knowledge_base)

        if self._api_ready:
            from src.learning.writing_analytics import WritingAnalytics
            self.learning_engine = WritingAnalytics(
                llm_client=self.llm_client,
                knowledge_base=self.knowledge_base,
                chapter_repo=self.chapter_repo,
                novel_repo=self.novel_repo,
            )
        else:
            self.learning_engine = None

        self.scheduler = SchedulerService(
            db_url=self.config.db_url,
            timezone=self.config.scheduling.get("timezone", "Asia/Shanghai"),
        )

        self._planner: NovelPlanner | None = None
        self._running_tasks: dict[str, asyncio.Task] = {}  # task_id -> asyncio Task
        self._task_states: dict[str, dict] = {}  # task_id -> {status, type, novel_id, result, error, created_at}

    def _reset_session(self):
        """Reset the database session if it's in a failed state."""
        try:
            self._session.rollback()
        except Exception:
            pass
        try:
            self._session.close()
        except Exception:
            pass
        self._session = self.db.create_session()
        self.novel_repo = NovelRepository(self._session)
        self.chapter_repo = ChapterRepository(self._session)
        self.trend_repo = TrendRepository(self._session)

    def _get_planner(self) -> NovelPlanner:
        if self._planner is None:
            self._planner = NovelPlanner(
                llm_client=self.llm_client,
                world_builder=self.world_builder,
                character_designer=self.character_designer,
                plot_outliner=self.plot_outliner,
                chapter_writer=None,
                quality_checker=self.quality_checker,
                local_publisher=self.local_publisher,
                novel_repo=self.novel_repo,
                chapter_repo=self.chapter_repo,
                style_optimizer=self.style_optimizer,
            )
        return self._planner

    # ── Task management ────────────────────────────

    def _start_task(self, task_type: str, novel_id: int | None, coro) -> str:
        """Launch a background task that survives client disconnect.

        Returns a task_id for polling.
        """
        task_id = str(uuid.uuid4())[:8]
        self._task_states[task_id] = {
            "id": task_id,
            "type": task_type,
            "novel_id": novel_id,
            "status": "running",
            "result": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        async def _wrapper():
            try:
                result = await coro
                self._task_states[task_id]["status"] = "completed"
                self._task_states[task_id]["result"] = result
                self._task_states[task_id]["updated_at"] = time.time()
            except asyncio.CancelledError:
                self._task_states[task_id]["status"] = "cancelled"
                self._task_states[task_id]["updated_at"] = time.time()
            except Exception as e:
                self._task_states[task_id]["status"] = "failed"
                self._task_states[task_id]["error"] = str(e)
                self._task_states[task_id]["updated_at"] = time.time()
                logger.exception("Background task %s failed", task_id)

        bg_task = asyncio.create_task(_wrapper())
        self._running_tasks[task_id] = bg_task
        return task_id

    def _get_task_state(self, task_id: str) -> dict | None:
        """Get current state of a background task."""
        return self._task_states.get(task_id)

    def _cancel_task(self, task_id: str) -> bool:
        """Cancel a running background task."""
        state = self._task_states.get(task_id)
        if not state or state["status"] != "running":
            return False
        bg_task = self._running_tasks.get(task_id)
        if bg_task and not bg_task.done():
            bg_task.cancel()
        state["status"] = "cancelled"
        state["updated_at"] = time.time()
        return True


# ═══════════════════════════════════════════════════════════
# Page Routes
# ═══════════════════════════════════════════════════════════

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    next_url = request.query_params.get("next", "/")
    return render("login.html", {
        "request": request,
        "next": next_url,
        "has_password": bool(ADMIN_PASSWORD),
    })


@app.post("/api/auth/login")
async def api_login(request: Request):
    """Verify password and set auth cookie."""
    try:
        body = await request.json()
        password = body.get("password", "")
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid request"}, status_code=400)

    if not password:
        return JSONResponse({"success": False, "error": "请输入密码"}, status_code=400)

    if not hmac.compare_digest(password, ADMIN_PASSWORD):
        return JSONResponse({"success": False, "error": "密码错误"}, status_code=401)

    token = _make_token(password)
    response = JSONResponse({"success": True, "message": "登录成功"})
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # Set True if using HTTPS
    )
    return response


@app.post("/api/auth/logout")
async def api_logout():
    """Clear auth cookie."""
    response = JSONResponse({"success": True})
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard showing all novels and system status."""
    app_inst = get_app()
    try:
        novels = app_inst.novel_repo.list_all()
    except Exception:
        app_inst._reset_session()
        novels = app_inst.novel_repo.list_all()
    cost = app_inst.cost_tracker.get_summary()
    scheduler_running = app_inst.scheduler.is_running

    # Enrich novels with chapter info
    novel_data = []
    for n in novels:
        latest = app_inst.chapter_repo.get_latest(n.id)
        novel_data.append({
            "id": n.id,
            "title": n.title,
            "genre": n.genre,
            "status": n.status,
            "total_chapters": n.total_chapters,
            "target_chapters": n.target_chapters,
            "latest_chapter": latest.chapter_number if latest else 0,
            "synopsis": n.synopsis or "",
        })

    return render("index.html", {
        "request": request,
        "novels": novel_data,
        "cost": cost,
        "scheduler_running": scheduler_running,
        "novel_count": len(novel_data),
        "api_ready": app_inst._api_ready,
    })


@app.get("/create", response_class=HTMLResponse)
async def create_page(request: Request):
    """Novel creation form."""
    app_inst = get_app()
    genres = list(app_inst.config.genres.keys())
    trending_tags = app_inst.config.trending_tags_2025

    # Try to get trend recommendation
    rec = {}
    try:
        rec = app_inst.trend_analyzer.recommend()
    except Exception:
        rec = {"genre": "玄幻", "hot_elements": trending_tags[:5]}

    return render("create.html", {
        "request": request,
        "genres": genres,
        "trending_tags": trending_tags,
        "recommendation": rec,
    })


@app.get("/novel/{novel_id}", response_class=HTMLResponse)
async def novel_detail(request: Request, novel_id: int):
    """Novel detail page with chapter list."""
    app_inst = get_app()
    try:
        novel = app_inst.novel_repo.get(novel_id)
    except Exception:
        app_inst._reset_session()
        novel = app_inst.novel_repo.get(novel_id)
    if not novel:
        return HTMLResponse("<h1>Novel not found</h1>", status_code=404)

    chapters = app_inst.chapter_repo.list_by_novel(novel_id)
    chapter_data = [
        {
            "number": ch.chapter_number,
            "title": ch.title,
            "word_count": ch.word_count,
            "status": ch.status,
            "quality_score": ch.quality_score,
            "has_content": ch.content_path is not None and Path(ch.content_path).exists() if ch.content_path else False,
        }
        for ch in chapters
    ]

    return render("novel.html", {
        "request": request,
        "novel": novel,
        "chapters": chapter_data,
        "chapter_count": len(chapter_data),
    })


@app.get("/novel/{novel_id}/chapter/{chapter_num}", response_class=HTMLResponse)
async def chapter_view(request: Request, novel_id: int, chapter_num: int):
    """View a single chapter."""
    app_inst = get_app()
    novel = app_inst.novel_repo.get(novel_id)
    if not novel:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    chapter = app_inst.chapter_repo.get_by_number(novel_id, chapter_num)
    if not chapter:
        return HTMLResponse("<h1>Chapter not found</h1>", status_code=404)

    content = ""
    if chapter.content_path and Path(chapter.content_path).exists():
        with open(chapter.content_path, "r", encoding="utf-8") as f:
            content = f.read()

    # Navigation — use actual chapter count from DB, not just completed ones
    actual_ch_count = max(
        novel.total_chapters,
        app_inst.chapter_repo.count_by_novel(novel_id),
    )
    prev_ch = chapter_num - 1 if chapter_num > 1 else None
    next_ch = chapter_num + 1 if chapter_num < actual_ch_count else None

    return render("chapter.html", {
        "request": request,
        "novel": novel,
        "chapter": chapter,
        "content": content,
        "prev_chapter": prev_ch,
        "next_chapter": next_ch,
        "chapter_count": actual_ch_count,
        "chapter_list": list(range(1, actual_ch_count + 1)),
    })


@app.get("/learning", response_class=HTMLResponse)
async def learning_page(request: Request):
    """Learning report page showing system knowledge and style evolution."""
    app_inst = get_app()
    kb_stats = app_inst.knowledge_base.get_stats()

    return render("learning.html", {
        "request": request,
        "stats": kb_stats,
        "genre_summary": kb_stats.get("genre_summary", {}),
        "top_elements": app_inst.knowledge_base._data.get("top_performing_elements", []),
        "global_tips": app_inst.knowledge_base._data.get("global_tips", []),
        "evolution": app_inst.knowledge_base._data.get("style_evolution", []),
    })


@app.post("/api/learning/run")
async def api_run_learning():
    """Manually trigger a learning analysis cycle."""
    app_inst = get_app()
    if not app_inst.learning_engine:
        return JSONResponse({"success": False, "error": "Learning engine not available"}, status_code=400)

    try:
        report = await app_inst.learning_engine.run_analysis_cycle()
        return JSONResponse({
            "success": True,
            "chapters_analyzed": report.total_chapters_analyzed,
            "quality_trend": report.quality_trend,
            "avg_quality": report.avg_quality,
            "suggestions": report.improvement_suggestions[:5],
        })
    except Exception as e:
        logger.exception("Manual learning cycle failed")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """System settings and configuration page."""
    app_inst = get_app()
    cost = app_inst.cost_tracker.get_summary()

    return render("settings.html", {
        "request": request,
        "config": app_inst.config,
        "cost": cost,
        "api_ready": app_inst._api_ready,
        "scheduler_running": app_inst.scheduler.is_running,
        "db_url": app_inst.config.db_url,
        "output_dir": str(app_inst.config.output_dir),
        "app_version": "0.1.0",
    })


# ═══════════════════════════════════════════════════════════
# API Routes
# ═══════════════════════════════════════════════════════════

from pydantic import BaseModel


class CreateNovelRequest(BaseModel):
    genre: str = "玄幻"
    extra_requirements: str = ""
    custom_elements: list[str] = []


class GenerateRequest(BaseModel):
    special_instructions: str = ""
    count: int = 1  # Number of chapters to generate (1-10)


class UpdateChapterRequest(BaseModel):
    content: str
    title: str = ""


@app.post("/api/novels")
async def api_create_novel(req: CreateNovelRequest):
    """Create a new novel (fire-and-forget, survives refresh)."""
    app_inst = get_app()
    if not app_inst._api_ready:
        return JSONResponse({"success": False, "error": "请先设置 ANTHROPIC_API_KEY 环境变量"}, status_code=400)
    planner = app_inst._get_planner()

    elements = req.custom_elements if req.custom_elements else None

    async def _create():
        return await planner.create_novel(
            genre=req.genre,
            trending_elements=elements,
            extra_requirements=req.extra_requirements,
            trend_analyzer=app_inst.trend_analyzer,
        )

    task_id = app_inst._start_task("create_novel", None, _create())
    return JSONResponse({"success": True, "task_id": task_id})


@app.post("/api/novels/{novel_id}/generate")
async def api_generate_chapter(novel_id: int, req: GenerateRequest = GenerateRequest()):
    """Generate chapters (fire-and-forget, survives refresh).

    Set count > 1 to generate multiple chapters in sequence.
    """
    app_inst = get_app()
    planner = app_inst._get_planner()

    novel = app_inst.novel_repo.get(novel_id)
    if not novel:
        return JSONResponse({"success": False, "error": "Novel not found"}, status_code=404)

    count = max(1, min(req.count, 10))  # Clamp to 1-10

    async def _gen_multi():
        results = []
        current_novel = novel
        for i in range(count):
            # Refresh novel state before each chapter
            current_novel = app_inst.novel_repo.get(novel_id)
            if not current_novel:
                break
            chapter, content = await planner.generate_next_chapter(current_novel)
            results.append((chapter, content))
            # Update task progress
            task_state = app_inst._task_states.get(task_id_local)
            if task_state:
                task_state["progress"] = {"current": i + 1, "total": count}
                task_state["last_chapter"] = chapter.chapter_number
                task_state["last_title"] = chapter.title
        return results

    task_id = app_inst._start_task("generate_chapter", novel_id, _gen_multi())
    task_id_local = task_id  # Capture for closure
    # Initialize progress
    app_inst._task_states[task_id]["progress"] = {"current": 0, "total": count}
    return JSONResponse({"success": True, "task_id": task_id, "novel_id": novel_id, "total": count})


@app.post("/api/tasks/cancel")
async def api_cancel_tasks():
    """Cancel all running tasks (legacy)."""
    app_inst = get_app()
    cancelled = 0
    for task_id, task in list(app_inst._running_tasks.items()):
        if not task.done():
            task.cancel()
            cancelled += 1
            logger.info("Cancelled task: %s", task_id)
    app_inst._running_tasks.clear()
    return JSONResponse({"success": True, "cancelled": cancelled})


@app.get("/api/tasks/{task_id}")
async def api_get_task(task_id: str):
    """Get the status of a background task. Survives page refresh."""
    app_inst = get_app()
    state = app_inst._get_task_state(task_id)
    if not state:
        return JSONResponse({"success": False, "error": "Task not found"}, status_code=404)

    result = state.get("result")
    progress = state.get("progress")
    # If the task completed and was a generate_chapter, include content
    response_data = {
        "success": True,
        "task_id": task_id,
        "type": state["type"],
        "status": state["status"],
        "novel_id": state.get("novel_id"),
        "error": state.get("error"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "progress": progress,
        "last_chapter": state.get("last_chapter"),
        "last_title": state.get("last_title"),
    }

    if state["status"] == "completed" and result:
        if state["type"] == "create_novel":
            response_data["novel_id"] = result.id
            response_data["title"] = result.title
            response_data["genre"] = result.genre
        elif state["type"] == "generate_chapter":
            # result is a list of (chapter, content) tuples
            results_list = result if isinstance(result, list) else [result]
            if results_list:
                last_chapter, last_content = results_list[-1]
                response_data["novel_id"] = last_chapter.novel_id
                response_data["chapter_number"] = last_chapter.chapter_number
                response_data["title"] = last_chapter.title
                response_data["word_count"] = last_chapter.word_count
                response_data["quality_score"] = last_chapter.quality_score
                response_data["chapters_generated"] = len(results_list)

    return JSONResponse(response_data)


@app.post("/api/tasks/{task_id}/cancel")
async def api_cancel_single_task(task_id: str):
    """Cancel a specific background task."""
    app_inst = get_app()
    ok = app_inst._cancel_task(task_id)
    return JSONResponse({"success": ok, "message": "已中止" if ok else "任务不存在或已完成"})


@app.delete("/api/novels/{novel_id}")
async def api_delete_novel(novel_id: int):
    """Delete a novel and all its chapters."""
    app_inst = get_app()
    novel = app_inst.novel_repo.get(novel_id)
    if not novel:
        return JSONResponse({"success": False, "error": "Novel not found"}, status_code=404)

    # Delete chapter files from disk
    import shutil
    novel_dir = app_inst.file_store.get_novel_dir(novel.title)
    if novel_dir.exists():
        shutil.rmtree(novel_dir, ignore_errors=True)

    # Delete from database
    app_inst.novel_repo.delete(novel_id)
    return JSONResponse({"success": True, "message": f"已删除《{novel.title}》"})


@app.delete("/api/novels/{novel_id}/chapters/{chapter_num}")
async def api_delete_chapter(novel_id: int, chapter_num: int):
    """Delete a single chapter."""
    app_inst = get_app()
    chapter = app_inst.chapter_repo.get_by_number(novel_id, chapter_num)
    if not chapter:
        return JSONResponse({"success": False, "error": "Chapter not found"}, status_code=404)

    # Delete the file
    if chapter.content_path:
        p = Path(chapter.content_path)
        if p.exists():
            p.unlink()

    # Delete from DB
    app_inst.chapter_repo.session.delete(chapter)
    app_inst.chapter_repo.session.commit()

    # Update novel chapter count if needed
    novel = app_inst.novel_repo.get(novel_id)
    if novel and novel.total_chapters >= chapter_num:
        novel.total_chapters -= 1
        app_inst.novel_repo.session.commit()

    return JSONResponse({"success": True, "message": f"已删除第{chapter_num}章"})


@app.put("/api/novels/{novel_id}/chapters/{chapter_num}")
async def api_update_chapter(novel_id: int, chapter_num: int, req: UpdateChapterRequest):
    """Update a chapter's content and/or title."""
    app_inst = get_app()
    chapter = app_inst.chapter_repo.get_by_number(novel_id, chapter_num)
    if not chapter:
        return JSONResponse({"success": False, "error": "Chapter not found"}, status_code=404)

    novel = app_inst.novel_repo.get(novel_id)

    if req.content:
        # Save updated content to file
        filepath = app_inst.file_store.save_chapter(
            novel_title=novel.title,
            chapter_number=chapter_num,
            chapter_title=req.title or chapter.title,
            content=req.content,
        )
        chapter.content_path = str(filepath)
        chapter.word_count = len(req.content.replace("\n", "").replace(" ", ""))

    if req.title:
        chapter.title = req.title

    chapter.updated_at = __import__('datetime').datetime.utcnow()
    app_inst.chapter_repo.session.commit()

    return JSONResponse({
        "success": True,
        "message": f"第{chapter_num}章已更新",
        "word_count": chapter.word_count,
    })


@app.get("/api/status")
async def api_status():
    """Get system status."""
    app_inst = get_app()
    novels = app_inst.novel_repo.list_all()
    cost = app_inst.cost_tracker.get_summary()

    return JSONResponse({
        "novels": [
            {"id": n.id, "title": n.title, "genre": n.genre,
             "chapters": n.total_chapters, "status": n.status}
            for n in novels
        ],
        "cost": {
            "total": cost["total_cost_usd"],
            "remaining": cost["remaining_budget_usd"],
            "calls": cost["total_calls"],
        },
        "scheduler_running": app_inst.scheduler.is_running,
    })


@app.post("/api/scheduler/start")
async def api_start_scheduler():
    """Start the scheduler."""
    app_inst = get_app()
    if not app_inst.scheduler.is_running:
        planner = app_inst._get_planner()
        init_jobs(
            planner=planner,
            cost_tracker=app_inst.cost_tracker,
            novel_repo=app_inst.novel_repo,
            chapter_repo=app_inst.chapter_repo,
            file_store=app_inst.file_store,
            db=app_inst.db,
            trend_analyzer=app_inst.trend_analyzer,
            learning_engine=app_inst.learning_engine,
        )
        app_inst.scheduler.start()
        # Register jobs
        sched_cfg = app_inst.config.scheduling
        mh, mm = map(int, sched_cfg.get("morning_chapter", "08:00").split(":"))
        eh, em = map(int, sched_cfg.get("evening_chapter", "20:00").split(":"))
        app_inst.scheduler.add_daily_job(generate_morning_chapter, "morning_chapter", mh, mm)
        app_inst.scheduler.add_daily_job(generate_evening_chapter, "evening_chapter", eh, em)
        app_inst.scheduler.add_weekly_job(refresh_trends, "trend_refresh", "sun", 3, 0)
        app_inst.scheduler.add_weekly_job(weekly_learning, "weekly_learning", "sun", 4, 0)
        app_inst.scheduler.add_daily_job(cost_report, "cost_report", 23, 0)
        app_inst.scheduler.add_interval_job(health_check, "health_check", 30)
        return JSONResponse({"success": True, "message": "Scheduler started (with weekly learning)"})
    return JSONResponse({"success": False, "message": "Already running"})


@app.post("/api/scheduler/stop")
async def api_stop_scheduler():
    """Stop the scheduler."""
    app_inst = get_app()
    if app_inst.scheduler.is_running:
        app_inst.scheduler.shutdown(wait=False)
        return JSONResponse({"success": True, "message": "Scheduler stopped"})
    return JSONResponse({"success": False, "message": "Not running"})


# ═══════════════════════════════════════════════════════════
# Export Routes
# ═══════════════════════════════════════════════════════════

@app.post("/api/novels/{novel_id}/export/txt")
async def api_export_txt(novel_id: int):
    """Compile all chapters into a TXT file and return download."""
    app_inst = get_app()
    novel = app_inst.novel_repo.get(novel_id)
    if not novel:
        return JSONResponse({"success": False, "error": "Novel not found"}, status_code=404)

    chapters = app_inst.chapter_repo.list_by_novel(novel_id)
    if not chapters:
        return JSONResponse({"success": False, "error": "No chapters to export"}, status_code=400)

    chapter_data = []
    for ch in chapters:
        if ch.content_path and Path(ch.content_path).exists():
            with open(ch.content_path, "r", encoding="utf-8") as f:
                content = f.read()
            chapter_data.append({
                "number": ch.chapter_number,
                "title": ch.title,
                "content": content,
            })

    if not chapter_data:
        return JSONResponse({"success": False, "error": "No chapter content files found"}, status_code=400)

    output_path = app_inst.local_publisher.compile_novel_txt(novel.title, chapter_data)
    filename = f"{novel.title}_全文.txt"
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="text/plain; charset=utf-8",
    )


@app.post("/api/novels/{novel_id}/export/epub")
async def api_export_epub(novel_id: int):
    """Compile all chapters into an EPUB file and return download."""
    app_inst = get_app()
    novel = app_inst.novel_repo.get(novel_id)
    if not novel:
        return JSONResponse({"success": False, "error": "Novel not found"}, status_code=404)

    chapters = app_inst.chapter_repo.list_by_novel(novel_id)
    if not chapters:
        return JSONResponse({"success": False, "error": "No chapters to export"}, status_code=400)

    chapter_data = []
    for ch in chapters:
        if ch.content_path and Path(ch.content_path).exists():
            with open(ch.content_path, "r", encoding="utf-8") as f:
                content = f.read()
            chapter_data.append({
                "number": ch.chapter_number,
                "title": ch.title,
                "content": content,
            })

    if not chapter_data:
        return JSONResponse({"success": False, "error": "No chapter content files found"}, status_code=400)

    output_path = app_inst.local_publisher.compile_novel_epub(
        novel_title=novel.title,
        author="AI Novel Writer",
        chapters=chapter_data,
        genre=novel.genre,
        synopsis=novel.synopsis or "",
    )
    filename = f"{novel.title}.epub"
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/epub+zip",
    )


# ═══════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════

def run_server(host: str = None, port: int = 8080):
    """Start the web server.

    host defaults to 0.0.0.0 in production (when not on Windows),
    or 127.0.0.1 on Windows for local development.
    """
    import platform
    import uvicorn
    if host is None:
        host = "127.0.0.1" if platform.system() == "Windows" else "0.0.0.0"
    print(f"\n  ╔══════════════════════════════════════╗")
    print(f"  ║  Novel Writer Agent Web UI          ║")
    print(f"  ║  http://{host}:{port}                 ║")
    print(f"  ║  按 Ctrl+C 停止                      ║")
    print(f"  ╚══════════════════════════════════════╝\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run_server()
