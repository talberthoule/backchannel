import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Text, String, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(20), default="pre_call")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    meeting_type: Mapped[str] = mapped_column(String(50), default="general")
    meeting_context: Mapped[str] = mapped_column(Text, default="")
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), ForeignKey("session_groups.id", use_alter=True), nullable=True)
    speaker_context_dirty: Mapped[bool] = mapped_column(Boolean, default=False)
    speaker_context_enhanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    speaker_context_version: Mapped[int] = mapped_column(Integer, default=0)

    documents = relationship("Document", back_populates="session", cascade="all, delete-orphan")
    directives = relationship("Directive", back_populates="session", cascade="all, delete-orphan")
    transcript_entries = relationship("TranscriptEntry", back_populates="session", cascade="all, delete-orphan")
    questions = relationship("Question", back_populates="session", cascade="all, delete-orphan")
    call_segments = relationship("CallSegment", back_populates="session", cascade="all, delete-orphan", order_by="CallSegment.segment_number")
    speakers = relationship("Speaker", back_populates="session", cascade="all, delete-orphan")
    agent_overrides = relationship("SessionAgentOverride", back_populates="session", cascade="all, delete-orphan")
    syntheses = relationship("SessionSynthesis", back_populates="session", cascade="all, delete-orphan")
    token_usage = relationship("TokenUsage", back_populates="session", cascade="all, delete-orphan")
    speaker_mapping_revisions = relationship("SpeakerMappingRevision", cascade="all, delete-orphan")
    speaker_revalidation_runs = relationship("SpeakerRevalidationRun", cascade="all, delete-orphan")
    group = relationship("SessionGroup", foreign_keys=[group_id])


class SpeakerMappingRevision(Base):
    __tablename__ = "speaker_mapping_revisions"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "source_version",
            name="uq_speaker_mapping_revision_session_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    source_version: Mapped[int] = mapped_column(Integer)
    mapping_hash: Mapped[str] = mapped_column(String(64))
    mapping_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SpeakerRevalidationRun(Base):
    __tablename__ = "speaker_revalidation_runs"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "mapping_revision_id",
            "content_version",
            name="uq_speaker_revalidation_run_revision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    mapping_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("speaker_mapping_revisions.id", ondelete="CASCADE")
    )
    content_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="running")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    mapping_revision = relationship("SpeakerMappingRevision")
    batches = relationship(
        "SpeakerRevalidationBatch",
        cascade="all, delete-orphan",
        order_by="SpeakerRevalidationBatch.batch_index",
    )


class SpeakerRevalidationBatch(Base):
    __tablename__ = "speaker_revalidation_batches"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "batch_index",
            name="uq_speaker_revalidation_batch_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("speaker_revalidation_runs.id", ondelete="CASCADE")
    )
    batch_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    item_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    processed_entries: Mapped[int] = mapped_column(Integer, default=0)
    applied_operations: Mapped[int] = mapped_column(Integer, default=0)
    enhanced_insights: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(100))
    # Wide enough for "endpoint:<slug>:<served model name>" ids (see
    # services/custom_endpoints.py), not just registry ids.
    model_id: Mapped[str] = mapped_column(String(160))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("Session", back_populates="token_usage")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    gemini_file_uri: Mapped[str] = mapped_column(String(500), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("Session", back_populates="documents")


class Directive(Base):
    __tablename__ = "directives"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("Session", back_populates="directives")


class TranscriptEntry(Base):
    __tablename__ = "transcript_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), ForeignKey("speakers.id"), nullable=True)

    session = relationship("Session", back_populates="transcript_entries")
    speaker = relationship("Speaker")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    item_type: Mapped[str] = mapped_column(String(50), default="question")  # built-ins (question, observation, opportunity, action_item, objection) or a custom lens type slug
    lens_label: Mapped[str] = mapped_column(String(120), default="")  # display heading of the lens that produced this insight ("" for non-lens agents)
    question: Mapped[str] = mapped_column(Text)  # the text content (question text, observation text, etc.)
    rationale: Mapped[str] = mapped_column(Text, default="")
    source_context: Mapped[str] = mapped_column(Text, default="")
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), ForeignKey("speakers.id"), nullable=True)
    directive_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), ForeignKey("directives.id"), nullable=True)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    answer_summary: Mapped[str] = mapped_column(Text, default="")
    needs_followup: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_question: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enrichment_notes: Mapped[str] = mapped_column(Text, default="")
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    agent_source: Mapped[str] = mapped_column(String(30), default="general")
    offering_match: Mapped[str] = mapped_column(Text, default="")
    vote: Mapped[int] = mapped_column(Integer, default=0)  # -1 downvote, 0 neutral, 1 upvote
    enhanced: Mapped[bool] = mapped_column(Boolean, default=False)
    speaker_mapping_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("speaker_mapping_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )

    session = relationship("Session", back_populates="questions")
    directive = relationship("Directive")
    speaker = relationship("Speaker")


class SessionSynthesis(Base):
    __tablename__ = "session_syntheses"
    __table_args__ = (
        UniqueConstraint("session_id", "mode", name="uq_session_syntheses_session_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    mode: Mapped[str] = mapped_column(String(20), default="post_call")  # live, post_call
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, partial, completed, error
    top_outcomes: Mapped[list] = mapped_column(JSON, default=list)
    client_objectives: Mapped[list] = mapped_column(JSON, default=list)
    top_opportunities: Mapped[list] = mapped_column(JSON, default=list)
    risks_blockers: Mapped[list] = mapped_column(JSON, default=list)
    action_plan: Mapped[list] = mapped_column(JSON, default=list)
    unresolved_discovery_questions: Mapped[list] = mapped_column(JSON, default=list)
    strategic_signals: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    lens_meeting: Mapped[dict] = mapped_column(JSON, default=dict)
    lens_discovery: Mapped[dict] = mapped_column(JSON, default=dict)
    arbiter_notes: Mapped[str] = mapped_column(Text, default="")
    model_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    speaker_mapping_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("speaker_mapping_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )

    session = relationship("Session", back_populates="syntheses")
    clusters = relationship("InsightCluster", back_populates="synthesis", cascade="all, delete-orphan", order_by="InsightCluster.priority")


class InsightCluster(Base):
    __tablename__ = "insight_clusters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    synthesis_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("session_syntheses.id"))
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str] = mapped_column(String(20), default="medium")
    related_question_ids: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    synthesis = relationship("SessionSynthesis", back_populates="clusters")


class CallSegment(Base):
    __tablename__ = "call_segments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    segment_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mic_audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    system_audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    session = relationship("Session", back_populates="call_segments")


class Offering(Base):
    __tablename__ = "offerings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    vendor: Mapped[str] = mapped_column(String(100))
    product_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100))  # Security, Cloud, Networking, etc.
    subcategory: Mapped[str] = mapped_column(String(255), default="")  # sub-category within the category
    description: Mapped[str] = mapped_column(Text, default="")
    use_cases: Mapped[str] = mapped_column(Text, default="")  # pain points / use cases it addresses
    note: Mapped[str] = mapped_column(String(255), default="")  # free-form note (positioning, packaging, caveats)
    tags: Mapped[str] = mapped_column(String(255), default="")  # tag(s), comma-separated if multiple
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(30))  # offerings, collection, files (future: http_rag)
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[str] = mapped_column(Text, default="{}")  # JSON text, e.g. {"char_budget": 60000}
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeRecord(Base):
    __tablename__ = "knowledge_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("knowledge_sources.id"))
    title: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[str] = mapped_column(Text, default="{}")  # JSON text (filename, import row extras)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Speaker(Base):
    __tablename__ = "speakers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(100), default="")  # e.g. "Sales Engineer", "Client", "Technical Lead"
    color: Mapped[str] = mapped_column(String(20), default="#0d9488")  # hex color for UI
    is_user: Mapped[bool] = mapped_column(Boolean, default=False)  # true if this is the app user
    speaker_type: Mapped[str] = mapped_column(String(20), default="external")  # team or external
    display_name: Mapped[str] = mapped_column(String(255), default="")  # mapped real name (e.g. "John Smith")
    display_name_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # show display_name in UI/exports
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = relationship("Session", back_populates="speakers")


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    agent_type: Mapped[str] = mapped_column(String(20))  # audio, text, meta, db
    # Registry id, or "endpoint:<slug>:<served model name>" for a model on a
    # self-hosted endpoint (see services/custom_endpoints.py).
    model_id: Mapped[str] = mapped_column(String(160))
    prompt: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sub_types: Mapped[str] = mapped_column(String(200), default="")  # comma-separated item_types (legacy; superseded by lenses where present)
    lenses: Mapped[str] = mapped_column(Text, default="")  # JSON array of {key,label,item_type,enabled,prompt} lens configs
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)  # cycle interval for periodic agents
    # JSON dict {model_id: interval_seconds}: a per-model cycle budget that wins
    # over interval_seconds when the agent runs that model. Empty falls back to
    # interval_seconds, then the seeded default. Written from the fit test.
    model_intervals: Mapped[str] = mapped_column(Text, default="")
    knowledge_source_ids: Mapped[str] = mapped_column(
        Text, default=""
    )  # comma-separated knowledge source UUIDs for db-type agents; empty falls back to the offerings catalog
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionAgentOverride(Base):
    __tablename__ = "session_agent_overrides"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("sessions.id"))
    agent_slug: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    session = relationship("Session", back_populates="agent_overrides")


class SessionGroup(Base):
    __tablename__ = "session_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomEndpoint(Base):
    """A self-hosted OpenAI-compatible chat server (LM Studio, Ollama, vLLM, ...).

    Each row contributes one selectable model per entry in models, so a
    workstation running two models shows two named options in every model
    picker instead of one opaque placeholder. api_key is a Fernet token (see
    services/secrets.py) and is usually empty: local servers are unauthenticated.
    """

    __tablename__ = "custom_endpoints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # slug used in model ids
    name: Mapped[str] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(255))
    api_key: Mapped[str] = mapped_column(Text, default="")  # encrypted; "" means keyless
    models: Mapped[list] = mapped_column(JSON, default=list)  # [{"id": ..., "label": ...}]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Last connection-test outcome, so the UI can show reachability without probing on load.
    last_status: Mapped[str] = mapped_column(String(20), default="")  # "ok", "error", or ""
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
