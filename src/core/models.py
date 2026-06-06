"""Data models for the novel writer agent — SQLAlchemy ORM + Pydantic schemas."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship


# ═══════════════════════════════════════════════════════════
# Base
# ═══════════════════════════════════════════════════════════

class Base(DeclarativeBase):
    pass


# ═══════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════

class NovelStatus(str, Enum):
    PLANNING = "planning"
    WRITING = "writing"
    COMPLETED = "completed"
    PAUSED = "paused"


class Genre(str, Enum):
    XUANHUAN = "玄幻"
    XIANXIA = "仙侠"
    DUSHI = "都市"
    KEHUAN = "科幻"
    LISHI = "历史"
    YOUXI = "游戏"
    XUANYI = "悬疑"
    YANQING = "言情"
    WUXIA = "武侠"


class CharacterRole(str, Enum):
    PROTAGONIST = "protagonist"
    SUPPORTING = "supporting"
    ANTAGONIST = "antagonist"
    MENTOR = "mentor"
    LOVE_INTEREST = "love_interest"
    COMIC_RELIEF = "comic_relief"
    RIVAL = "rival"


class PlotPointType(str, Enum):
    HOOK = "hook"
    INCITING_INCIDENT = "inciting_incident"
    TURNING_POINT = "turning_point"
    CLIMAX = "climax"
    RESOLUTION = "resolution"
    SUBPLOT = "subplot"
    FORESHADOWING = "foreshadowing"
    CLIFFHANGER = "cliffhanger"


class ChapterStatus(str, Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


# ═══════════════════════════════════════════════════════════
# SQLAlchemy ORM Models
# ═══════════════════════════════════════════════════════════

class Novel(Base):
    """A novel being written by the agent."""
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    genre = Column(String(64), nullable=False)
    subgenre = Column(String(128))
    status = Column(String(32), default=NovelStatus.PLANNING.value)
    synopsis = Column(Text)
    target_chapters = Column(Integer, default=100)
    total_chapters = Column(Integer, default=0)
    trending_elements = Column(JSON)       # {"tags": [...], "tropes": [...], "source": {...}}
    world_setting = Column(JSON)            # Structured world-building data
    writing_style = Column(JSON)            # Style parameters
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chapters = relationship("Chapter", back_populates="novel", lazy="dynamic",
                           cascade="all, delete-orphan", passive_deletes=True)
    characters = relationship("Character", back_populates="novel", lazy="dynamic",
                             cascade="all, delete-orphan", passive_deletes=True)
    plot_points = relationship("PlotPoint", back_populates="novel", lazy="dynamic",
                              cascade="all, delete-orphan", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Novel(id={self.id}, title='{self.title}', status='{self.status}')>"


class Chapter(Base):
    """A single chapter of a novel."""
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    title = Column(String(256))
    word_count = Column(Integer, default=0)
    status = Column(String(32), default=ChapterStatus.DRAFT.value)
    outline = Column(JSON)           # Chapter outline bullet points
    content_path = Column(String(512))  # Path to chapter file
    summary = Column(Text)           # AI-generated summary for context
    quality_score = Column(Float)    # Post-generation quality score (0-1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("novel_id", "chapter_number", name="uq_novel_chapter"),
    )

    novel = relationship("Novel", back_populates="chapters")

    def __repr__(self) -> str:
        return f"<Chapter(novel_id={self.novel_id}, number={self.chapter_number}, words={self.word_count})>"


class Character(Base):
    """A character in a novel."""
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    role = Column(String(32), nullable=False)
    profile = Column(JSON)    # Background, personality, appearance, motivation, abilities
    state = Column(JSON)      # Current state: location, power_level, goals, inventory, relationships
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    novel = relationship("Novel", back_populates="characters")

    def __repr__(self) -> str:
        return f"<Character(name='{self.name}', role='{self.role}')>"


class PlotPoint(Base):
    """A plot point or story beat."""
    __tablename__ = "plot_points"

    id = Column(Integer, primary_key=True, autoincrement=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    chapter_introduced = Column(Integer)
    chapter_resolved = Column(Integer)
    status = Column(String(32), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    novel = relationship("Novel", back_populates="plot_points")

    def __repr__(self) -> str:
        return f"<PlotPoint(type='{self.type}', status='{self.status}')>"


class TrendingElement(Base):
    """A trending element extracted from novel platforms."""
    __tablename__ = "trending_elements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(64), nullable=False)       # "fanqie" or "qidian"
    category = Column(String(64))                     # "tag", "trope", "genre"
    name = Column(String(128), nullable=False)
    frequency = Column(Integer, default=0)
    growth_rate = Column(Float, default=0.0)
    co_occurring = Column(JSON)                       # Tags that appear together: {tag: count}
    collected_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<TrendingElement(source='{self.source}', name='{self.name}', freq={self.frequency})>"


class GenerationLog(Base):
    """Log of an LLM generation call for cost and performance tracking."""
    __tablename__ = "generation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="SET NULL"), nullable=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    stage = Column(String(64))            # "chapter_writing", "world_building", "quality_check", etc.
    model_used = Column(String(64))
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    cache_read_tokens = Column(Integer, default=0)
    cache_write_tokens = Column(Integer, default=0)
    cost_usd = Column(Float)
    latency_ms = Column(Integer)
    success = Column(Integer, default=1)  # 1 = success, 0 = failure
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<GenerationLog(stage='{self.stage}', model='{self.model_used}', cost={self.cost_usd})>"


# ═══════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════

class CharacterProfile(BaseModel):
    """Full profile of a character used during design and generation."""
    name: str
    role: CharacterRole
    age: Optional[int] = None
    gender: Optional[str] = None
    appearance: str = ""
    personality: str = ""
    background: str = ""
    motivation: str = ""
    abilities: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)  # name -> relationship description


class CharacterState(BaseModel):
    """Runtime state tracking for a character — updated after each chapter."""
    current_location: str = ""
    power_level: str = ""
    active_goals: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    relationship_changes: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class StoryBible(BaseModel):
    """The canonical source of truth for a novel's continuity.

    This is the most critical data structure for maintaining coherence
    across hundreds of chapters. It is always included in the LLM context.
    """
    novel_id: int
    novel_title: str = ""
    world_setting: dict = Field(default_factory=dict)
    characters: dict[str, CharacterState] = Field(default_factory=dict)  # name -> current state
    active_plot_threads: list[dict] = Field(default_factory=list)
    revealed_secrets: list[dict] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)           # chronological major events
    chapter_summaries: dict[int, str] = Field(default_factory=dict)  # chapter_num -> summary
    last_updated_chapter: int = 0
    version: int = 1                                            # increment on each update


class ChapterOutline(BaseModel):
    """The outline for a single chapter."""
    chapter_number: int
    title: str
    bullet_points: list[str] = Field(default_factory=list)  # 3-5 key plot beats
    pov_character: str = ""
    cliffhanger: str = ""                                    # End hook description
    characters_appearing: list[str] = Field(default_factory=list)


class TrendReport(BaseModel):
    """Aggregated trend analysis report."""
    collected_at: datetime
    source: str
    top_genres: list[dict] = Field(default_factory=list)    # [{name, score, growth}]
    top_tags: list[dict] = Field(default_factory=list)      # [{name, frequency, co_occurring}]
    emerging_tropes: list[dict] = Field(default_factory=list)  # [{name, description, examples}]
    recommended_genre: str = ""
    recommended_elements: list[str] = Field(default_factory=list)


class WorldSetting(BaseModel):
    """Structured world-building data."""
    world_name: str = ""
    world_type: str = ""
    era: str = ""
    geography: dict = Field(default_factory=dict)
    power_system: Optional[dict] = None    # For 玄幻/仙侠
    social_structure: dict = Field(default_factory=dict)
    factions: list[dict] = Field(default_factory=list)
    history: str = ""
    unique_rules: list[str] = Field(default_factory=list)
    story_hooks: list[str] = Field(default_factory=list)


class GenerationConfig(BaseModel):
    """Configuration for a chapter generation call."""
    target_words: int = 2000
    temperature: float = 0.8
    max_tokens: int = 4096
    use_adaptive_thinking: bool = True
    use_prompt_caching: bool = True
