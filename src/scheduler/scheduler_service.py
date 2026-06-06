"""Scheduler service — manages APScheduler lifecycle with SQLAlchemy persistence.

Provides:
- Background scheduler with SQLAlchemy job store for persistence across restarts
- Configurable timezone (default Asia/Shanghai)
- Job registration for chapter generation, trend refresh, cost reports, health checks
- Graceful startup and shutdown
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages the APScheduler lifecycle for the novel writer agent.

    Usage:
        service = SchedulerService(db_url="sqlite:///data/novels.db", timezone="Asia/Shanghai")
        service.start()
        service.add_daily_job(my_func, job_id="morning_chapter", hour=8, minute=0)
        # ... app runs ...
        service.shutdown()
    """

    def __init__(
        self,
        db_url: str = "sqlite:///F:/novel-writer-agent/data/novels.db",
        timezone: str = "Asia/Shanghai",
    ):
        self.db_url = db_url
        self.timezone = timezone
        self._scheduler: Optional[BackgroundScheduler] = None
        self._running = False

    @property
    def scheduler(self) -> BackgroundScheduler:
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized. Call start() first.")
        return self._scheduler

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Initialize and start the background scheduler."""
        if self._running:
            logger.warning("Scheduler is already running")
            return

        # Job store: persist jobs in SQLite so they survive restarts
        jobstores = {
            "default": SQLAlchemyJobStore(url=self.db_url),
        }

        # Executor: thread pool for running jobs
        executors = {
            "default": ThreadPoolExecutor(max_workers=4),
        }

        # Job defaults
        job_defaults = {
            "coalesce": True,          # Merge missed triggers into one execution
            "max_instances": 1,         # Prevent overlapping job runs
            "misfire_grace_time": 3600, # Allow 1-hour delay before skipping
        }

        self._scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=self.timezone,
        )

        self._scheduler.start()
        self._running = True

        logger.info("Scheduler started | timezone=%s | db=%s", self.timezone, self.db_url)

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the scheduler gracefully.

        Args:
            wait: If True, wait for running jobs to complete.
        """
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=wait)
            self._running = False
            logger.info("Scheduler shut down")

    # ── Job Registration ────────────────────────────────

    def add_daily_job(
        self,
        func,
        job_id: str,
        hour: int = 8,
        minute: int = 0,
        name: str = "",
        kwargs: Optional[dict] = None,
    ) -> str:
        """Add a daily job at a specific time.

        Args:
            func: The callable to execute.
            job_id: Unique job identifier.
            hour: Hour (0-23) in configured timezone.
            minute: Minute (0-59).
            name: Human-readable job name.
            kwargs: Keyword arguments to pass to func.

        Returns:
            The job ID.
        """
        trigger = CronTrigger(hour=hour, minute=minute, timezone=self.timezone)
        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            kwargs=kwargs or {},
            replace_existing=True,
        )
        logger.info("Daily job added: %s at %02d:%02d %s", job_id, hour, minute, self.timezone)
        return job_id

    def add_weekly_job(
        self,
        func,
        job_id: str,
        day_of_week: str = "sun",
        hour: int = 3,
        minute: int = 0,
        name: str = "",
        kwargs: Optional[dict] = None,
    ) -> str:
        """Add a weekly job.

        Args:
            func: The callable to execute.
            job_id: Unique job identifier.
            day_of_week: Day abbreviation (mon, tue, wed, thu, fri, sat, sun).
            hour: Hour (0-23).
            minute: Minute (0-59).
            name: Human-readable name.
            kwargs: Keyword arguments to pass to func.

        Returns:
            The job ID.
        """
        trigger = CronTrigger(
            day_of_week=day_of_week,
            hour=hour,
            minute=minute,
            timezone=self.timezone,
        )
        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            kwargs=kwargs or {},
            replace_existing=True,
        )
        logger.info("Weekly job added: %s on %s at %02d:%02d", job_id, day_of_week, hour, minute)
        return job_id

    def add_interval_job(
        self,
        func,
        job_id: str,
        minutes: int = 30,
        name: str = "",
        kwargs: Optional[dict] = None,
    ) -> str:
        """Add an interval job that runs every N minutes.

        Args:
            func: The callable to execute.
            job_id: Unique job identifier.
            minutes: Interval in minutes.
            name: Human-readable name.
            kwargs: Keyword arguments to pass to func.

        Returns:
            The job ID.
        """
        trigger = IntervalTrigger(minutes=minutes, timezone=self.timezone)
        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            kwargs=kwargs or {},
            replace_existing=True,
        )
        logger.info("Interval job added: %s every %d min", job_id, minutes)
        return job_id

    # ── Job Management ──────────────────────────────────

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        try:
            self.scheduler.remove_job(job_id)
            logger.info("Job removed: %s", job_id)
            return True
        except Exception as e:
            logger.warning("Failed to remove job %s: %s", job_id, e)
            return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a job without removing it."""
        try:
            self.scheduler.pause_job(job_id)
            logger.info("Job paused: %s", job_id)
            return True
        except Exception as e:
            logger.warning("Failed to pause job %s: %s", job_id, e)
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        try:
            self.scheduler.resume_job(job_id)
            logger.info("Job resumed: %s", job_id)
            return True
        except Exception as e:
            logger.warning("Failed to resume job %s: %s", job_id, e)
            return False

    def get_jobs(self) -> list[dict]:
        """Get information about all registered jobs."""
        jobs = self.scheduler.get_jobs()
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else "paused",
                "trigger": str(job.trigger),
            }
            for job in jobs
        ]

    def print_jobs(self) -> None:
        """Print all registered jobs in a readable format."""
        jobs = self.get_jobs()
        if not jobs:
            print("  No scheduled jobs.")
            return

        print(f"\n  Scheduled Jobs ({len(jobs)}):")
        print(f"  {'ID':<30} {'Next Run':<22} {'Trigger'}")
        print(f"  {'-'*30} {'-'*22} {'-'*25}")
        for job in jobs:
            print(f"  {job['id']:<30} {job['next_run']:<22} {job['trigger']}")
        print()

    def run_job_now(self, job_id: str) -> bool:
        """Trigger a job to run immediately (for testing)."""
        try:
            job = self.scheduler.get_job(job_id)
            if job:
                job.modify(next_run_time=datetime.now())
                logger.info("Job triggered immediately: %s", job_id)
                return True
            logger.warning("Job not found: %s", job_id)
            return False
        except Exception as e:
            logger.error("Failed to trigger job %s: %s", job_id, e)
            return False
