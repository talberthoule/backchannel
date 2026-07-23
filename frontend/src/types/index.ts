export type MeetingType =
  | "general"
  | "client_sales"
  | "customer_delivery"
  | "internal_enablement"
  | "internal_checkin"
  | "vendor_partner";

export interface Session {
  id: string;
  name: string;
  state: "pre_call" | "active" | "completed";
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  notes: string | null;
  meeting_type: MeetingType;
  meeting_context: string;
  group_id: string | null;
  speaker_context_dirty: boolean;
  speaker_context_enhanced_at: string | null;
}

export interface TokenUsageBreakdown {
  source?: string;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface TokenUsageSummary {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  by_source: TokenUsageBreakdown[];
  by_model: TokenUsageBreakdown[];
}

export interface SessionGroup {
  id: string;
  name: string;
  display_order: number;
  created_at: string;
}

export interface AgentConfig {
  id: string;
  slug: string;
  name: string;
  description: string;
  agent_type: "audio" | "text" | "meta" | "db";
  model_id: string;
  prompt: string;
  enabled: boolean;
  sub_types: string;
  lenses: string; // JSON array of AnalystLens
  interval_seconds: number | null;
  knowledge_source_ids: string;
  display_order: number;
  created_at: string;
  updated_at: string | null;
}

// One configurable analysis lens of the Consolidated Analyst. Each enabled
// lens contributes its own section to the composed system prompt; item_type
// picks which insight bucket the lens's findings surface as.
export interface AnalystLens {
  key: string;
  label: string;
  // One of the built-in types (question/observation/opportunity/action_item)
  // for special pipeline behavior, or a custom slug for a bespoke insight type.
  item_type: string;
  enabled: boolean;
  prompt: string;
}

export interface SessionAgent {
  slug: string;
  name: string;
  description: string;
  agent_type: string;
  enabled: boolean;
  is_override: boolean;
}

export interface Directive {
  id: string;
  session_id: string;
  text: string;
  active: boolean;
  created_at: string;
}

export interface Document {
  id: string;
  session_id: string;
  filename: string;
  mime_type: string;
  gemini_file_uri: string;
  uploaded_at: string;
}

export interface Question {
  id: string;
  session_id: string;
  // Built-in types (question, observation, opportunity, action_item,
  // objection) or a custom lens type slug.
  item_type: string;
  // Display heading of the analysis lens that produced this insight
  // ("" / absent for non-lens agents like the objection handler).
  lens_label?: string;
  question: string;
  rationale: string;
  source_context: string;
  speaker_id?: string | null;
  directive_id: string | null;
  starred: boolean;
  dismissed: boolean;
  created_at: string;
  answered: boolean;
  answer_summary: string;
  needs_followup: boolean;
  followup_question: string;
  is_followup?: boolean;
  updated_at?: string | null;
  enrichment_notes?: string;
  revision_count?: number;
  agent_source?: string;
  offering_match?: string;
  vote?: number; // -1 downvote, 0 neutral, 1 upvote
  enhanced?: boolean;
}

export interface EnhanceInsightsResult {
  status: "unchanged" | "running" | "completed" | "partial" | "failed";
  run_id: string | null;
  mapping_revision: number | null;
  content_version: string | null;
  total_batches: number;
  completed_batches: number;
  failed_batches: number;
  failure_rate: number;
  processed_entries: number;
  applied_operations: number;
  enhanced_insights: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  duration_ms: number;
  speaker_context_dirty: boolean;
  speaker_context_enhanced_at: string | null;
  briefing_updated: boolean;
  briefing_status: string | null;
  error: string | null;
  batches: Array<{
    id: string;
    index: number;
    kind: string;
    status: string;
    attempts: number;
    processed_entries: number;
    duration_ms: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    error: string | null;
  }>;
}

export interface Offering {
  id: string;
  vendor: string;
  product_name: string;
  category: string;
  subcategory: string;
  description: string;
  use_cases: string;
  note: string;
  tags: string;
  active: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface KnowledgeSource {
  id: string;
  name: string;
  source_type: "offerings" | "collection" | "files";
  description: string;
  config: string;
  active: boolean;
  record_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface KnowledgeRecord {
  id: string;
  source_id: string;
  title: string;
  body: string;
  meta: string;
  active: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface AppMeta {
  version: string;
}

export interface ReleaseNote {
  version: string;
  date: string;
  title: string;
  body: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  description: string;
  tier: string;
  requires_key?: string | null;
  key_available?: boolean;
  supports_text?: boolean;
  supports_batch_audio?: boolean;
  supports_live_audio?: boolean;
}

export interface DiarizationDiagnostics {
  torch_available: boolean;
  sortformer_available: boolean;
  cuda_available: boolean;
  gpu_backend: "cuda" | "rocm" | "none";
  device: string;
  gpu_name: string | null;
  gpu_memory_gb: number | null;
  model_id: string;
  status: string;
  recommended_live_diarizer: "lightweight" | "sortformer";
  reason: string;
  selected_live_diarizer: "lightweight" | "sortformer";
  effective_live_diarizer: "lightweight" | "sortformer";
  sortformer_selectable: boolean;
  benchmark_status: "passed" | "failed" | "unavailable" | "";
  benchmark_real_time_factor: number | null;
  speaker_similarity_threshold: number;
  selection_reason: string;
}

export interface DiarizationBenchmarkResult {
  status: "passed" | "failed" | "unavailable";
  recommended_live_diarizer: "lightweight" | "sortformer";
  real_time_factor: number | null;
  audio_seconds: number;
  processing_seconds: number;
  device: string;
  model_id: string;
  threshold: number;
  reason: string;
}

export interface TranscriptionConfig {
  batch_model_id: string;
  live_preview_model_id: string;
  description: string;
}

export interface PrivacyImpactItem {
  feature: string;
  detail: string;
}

export interface PrivacyConfig {
  local_only: boolean;
  batch_model_id: string;
  impact: {
    available: PrivacyImpactItem[];
    disabled: PrivacyImpactItem[];
  };
}

export interface CallSegment {
  id: string;
  session_id: string;
  segment_number: number;
  started_at: string;
  ended_at: string | null;
  audio_path?: string | null;
}

export interface Speaker {
  id: string;
  session_id: string;
  name: string;
  role: string;
  color: string;
  is_user: boolean;
  speaker_type: "team" | "external";
  display_name: string;
  display_name_enabled: boolean;
  created_at: string;
}

export interface TranscriptEntry {
  id?: string;
  session_id?: string;
  text: string;
  timestamp: string;
  sequence?: number;
  speaker_id?: string | null;
}

export interface SynthesisSectionItem {
  title: string;
  summary: string;
  rationale?: string;
  owner?: string;
  status?: string;
  evidence_refs?: Record<string, unknown>[];
}

export interface InsightCluster {
  id: string;
  synthesis_id: string;
  session_id: string;
  title: string;
  summary: string;
  priority: number;
  confidence: string;
  related_question_ids: string[];
  evidence_refs: Record<string, unknown>[];
  created_at: string;
}

export interface SessionSynthesis {
  id: string;
  session_id: string;
  mode: "live" | "post_call" | string;
  status: "pending" | "partial" | "completed" | "error" | string;
  top_outcomes: SynthesisSectionItem[];
  client_objectives: SynthesisSectionItem[];
  top_opportunities: SynthesisSectionItem[];
  risks_blockers: SynthesisSectionItem[];
  action_plan: SynthesisSectionItem[];
  unresolved_discovery_questions: SynthesisSectionItem[];
  strategic_signals: SynthesisSectionItem[];
  evidence_refs: Record<string, unknown>[];
  lens_meeting: Record<string, unknown>;
  lens_discovery: Record<string, unknown>;
  arbiter_notes: string;
  model_ids: Record<string, string>;
  error_message: string;
  created_at: string;
  updated_at: string | null;
  clusters: InsightCluster[];
}

/** How much post-call analysis a deliberate stop should run. */
export type StopDrainMode = "full" | "skip_analysis";

export interface WSStatusData {
  state: string;
  message: string;
  stage?: string;
  current_step?: number;
  total_steps?: number;
  progress?: number;
  steps?: string[];
  details?: Record<string, unknown>;
}

export interface PostProcessingProgress {
  active: boolean;
  state: "idle" | "running" | "completed" | "timeout" | "error";
  stage: string;
  message: string;
  currentStep: number;
  totalSteps: number;
  progress: number;
  startedAt: string | null;
  completedAt: string | null;
  confirmed: boolean;
  steps?: string[];
  details?: Record<string, unknown>;
}

export interface AudioSendStats {
  chunksSent: number;
  bytesSent: number;
  chunksDropped: number;
  lastSentAt: string | null;
}

export type WSMessage =
  | { type: "question"; data: Omit<Question, "session_id" | "starred" | "dismissed" | "created_at" | "answered" | "answer_summary" | "needs_followup" | "followup_question"> & { timestamp: string; is_followup?: boolean; item_type?: string } }
  | { type: "transcript"; data: TranscriptEntry }
  | { type: "interim_transcript"; data: { text: string } }
  | { type: "status"; data: WSStatusData }
  | { type: "synthesis_updated"; data: SessionSynthesis }
  | { type: "question_answered"; data: { id: string; answer_summary: string; needs_followup: boolean; followup_question: string } }
  | { type: "insight_updated"; data: Record<string, any> }
  | { type: "insight_elevated"; data: Record<string, any> & { old_type: string } };
