import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# --- Sessions ---
class SessionCreate(BaseModel):
    name: str
    notes: str | None = None
    meeting_type: str = "general"
    meeting_context: str = ""


class SessionUpdate(BaseModel):
    name: str | None = None
    state: str | None = None
    notes: str | None = None
    meeting_type: str | None = None
    meeting_context: str | None = None
    group_id: uuid.UUID | None = None


class SessionOut(BaseModel):
    id: uuid.UUID
    name: str
    state: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    notes: str | None
    meeting_type: str = "general"
    meeting_context: str = ""
    group_id: uuid.UUID | None = None
    speaker_context_dirty: bool = False
    speaker_context_enhanced_at: datetime | None = None
    drain_summary: str = ""

    model_config = {"from_attributes": True}


class TokenUsageSourceOut(BaseModel):
    source: str
    model_id: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    total_tokens: int
    # Non-zero only for duration-billed models (ALP-300).
    audio_seconds: float = 0.0


class TokenUsageModelOut(BaseModel):
    model_id: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    total_tokens: int
    audio_seconds: float = 0.0


class TokenUsageSummaryOut(BaseModel):
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    total_tokens: int
    audio_seconds: float = 0.0
    by_source: list[TokenUsageSourceOut]
    by_model: list[TokenUsageModelOut]


# --- Directives ---
class DirectiveCreate(BaseModel):
    text: str


class DirectiveUpdate(BaseModel):
    text: str | None = None
    active: bool | None = None


class DirectiveOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    text: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Documents ---
class DocumentOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    filename: str
    mime_type: str
    gemini_file_uri: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}


# --- Questions ---
class QuestionUpdate(BaseModel):
    starred: bool | None = None
    dismissed: bool | None = None
    vote: int | None = None  # -1, 0, or 1


class QuestionOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    item_type: str
    lens_label: str = ""
    question: str
    rationale: str
    source_context: str
    speaker_id: uuid.UUID | None = None
    directive_id: uuid.UUID | None
    starred: bool
    dismissed: bool
    answered: bool
    answer_summary: str
    needs_followup: bool
    followup_question: str
    created_at: datetime
    updated_at: datetime | None = None
    enrichment_notes: str = ""
    revision_count: int = 0
    agent_source: str = "general"
    offering_match: str = ""
    vote: int = 0
    enhanced: bool = False

    model_config = {"from_attributes": True}


class RevalidationBatchOut(BaseModel):
    id: uuid.UUID
    index: int
    kind: str
    status: str
    attempts: int
    processed_entries: int
    duration_ms: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    requested_model_id: str | None = None
    model_id: str | None = None
    error: str | None = None


class EnhanceInsightsOut(BaseModel):
    status: Literal["unchanged", "running", "completed", "partial", "failed"]
    run_id: uuid.UUID | None = None
    mapping_revision: int | None = None
    content_version: str | None = None
    total_batches: int = 0
    completed_batches: int = 0
    failed_batches: int = 0
    failure_rate: float = 0
    processed_entries: int = 0
    applied_operations: int = 0
    enhanced_insights: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    speaker_context_dirty: bool
    speaker_context_enhanced_at: datetime | None = None
    briefing_updated: bool
    briefing_status: str | None = None
    error: str | None = None
    batches: list[RevalidationBatchOut] = Field(default_factory=list)


class SynthesisSectionItem(BaseModel):
    title: str = ""
    summary: str = ""
    rationale: str = ""
    owner: str = ""
    status: str = ""
    evidence_refs: list[dict] = Field(default_factory=list)


class InsightClusterOut(BaseModel):
    id: uuid.UUID
    synthesis_id: uuid.UUID
    session_id: uuid.UUID
    title: str
    summary: str
    priority: int
    confidence: str
    related_question_ids: list = Field(default_factory=list)
    evidence_refs: list = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionSynthesisOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    mode: str
    status: str
    top_outcomes: list = Field(default_factory=list)
    client_objectives: list = Field(default_factory=list)
    top_opportunities: list = Field(default_factory=list)
    risks_blockers: list = Field(default_factory=list)
    action_plan: list = Field(default_factory=list)
    unresolved_discovery_questions: list = Field(default_factory=list)
    strategic_signals: list = Field(default_factory=list)
    signal_history: list = Field(default_factory=list)
    signal_history_count: int = 0
    evidence_refs: list = Field(default_factory=list)
    lens_meeting: dict = Field(default_factory=dict)
    lens_discovery: dict = Field(default_factory=dict)
    arbiter_notes: str = ""
    model_ids: dict = Field(default_factory=dict)
    error_message: str = ""
    created_at: datetime
    updated_at: datetime | None = None
    clusters: list[InsightClusterOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# --- Call Segments ---
class CallSegmentOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    segment_number: int
    started_at: datetime
    ended_at: datetime | None
    audio_path: str | None = None
    mic_audio_path: str | None = None
    system_audio_path: str | None = None

    model_config = {"from_attributes": True}


# --- Speakers ---
class SpeakerCreate(BaseModel):
    name: str
    role: str = ""
    color: str = "#0d9488"
    is_user: bool = False
    speaker_type: Literal["team", "external"] = "external"


class SpeakerUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    color: str | None = None
    is_user: bool | None = None
    speaker_type: Literal["team", "external"] | None = None
    display_name: str | None = None
    display_name_enabled: bool | None = None


class SpeakerMergeRequest(BaseModel):
    target_speaker_id: uuid.UUID


class SpeakerMergeOut(BaseModel):
    source_speaker_id: uuid.UUID
    target_speaker_id: uuid.UUID
    transcript_entries_updated: int
    questions_updated: int


class SpeakerOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    name: str
    role: str
    color: str
    is_user: bool
    speaker_type: str = "external"
    display_name: str = ""
    display_name_enabled: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Offerings ---
class OfferingCreate(BaseModel):
    vendor: str
    product_name: str
    category: str
    subcategory: str = ""
    description: str = ""
    use_cases: str = ""
    note: str = ""
    tags: str = ""
    active: bool = True


class OfferingUpdate(BaseModel):
    vendor: str | None = None
    product_name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    description: str | None = None
    use_cases: str | None = None
    note: str | None = None
    tags: str | None = None
    active: bool | None = None


class OfferingOut(BaseModel):
    id: uuid.UUID
    vendor: str
    product_name: str
    category: str
    subcategory: str
    description: str
    use_cases: str
    note: str
    tags: str
    active: bool
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Transcript ---
class TranscriptEntryOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    text: str
    timestamp: datetime
    sequence: int
    speaker_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


# --- Knowledge Sources ---
class KnowledgeSourceCreate(BaseModel):
    name: str
    source_type: str  # collection | files
    description: str = ""
    config: str = "{}"
    active: bool = True


class KnowledgeSourceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: str | None = None
    active: bool | None = None


class KnowledgeSourceOut(BaseModel):
    id: uuid.UUID
    name: str
    source_type: str
    description: str
    config: str
    active: bool
    record_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class KnowledgeRecordCreate(BaseModel):
    title: str = ""
    body: str = ""
    meta: str = "{}"
    active: bool = True


class KnowledgeRecordUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    meta: str | None = None
    active: bool | None = None


class KnowledgeRecordOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    title: str
    body: str
    meta: str
    active: bool
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Agent Configs ---
class AgentConfigUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    model_id: str | None = None
    prompt: str | None = None
    enabled: bool | None = None
    sub_types: str | None = None
    lenses: str | None = None  # JSON array of lens configs; validated in the router
    interval_seconds: int | None = None
    model_intervals: str | None = None  # JSON {model_id: interval}; validated in the router
    knowledge_source_ids: str | None = None  # comma-separated UUIDs; "" = default offerings


class AgentConfigOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    agent_type: str
    model_id: str
    prompt: str
    enabled: bool
    sub_types: str
    lenses: str = ""
    interval_seconds: int | None = None
    model_intervals: str = ""
    knowledge_source_ids: str = ""
    display_order: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Session Agent Overrides ---
class SessionAgentOverrideSet(BaseModel):
    agent_slug: str
    enabled: bool


class SessionAgentOut(BaseModel):
    slug: str
    name: str
    description: str
    agent_type: str
    enabled: bool
    is_override: bool


# --- Session Groups ---
class SessionGroupCreate(BaseModel):
    name: str


class SessionGroupUpdate(BaseModel):
    name: str | None = None
    display_order: int | None = None


class SessionGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    display_order: int
    created_at: datetime

    model_config = {"from_attributes": True}
