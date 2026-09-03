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
  // JSON drain summary saved at finalize; "" for sessions that predate it.
  drain_summary?: string;
}

export interface TokenUsageBreakdown {
  source?: string;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  // Reasoning tokens. Billed at output rates and already counted in
  // total_tokens, so never add it to input + output.
  thinking_tokens: number;
  total_tokens: number;
  // Audio duration, for models billed per minute instead of per token
  // (the live gateway). Zero for every token-billed model.
  audio_seconds: number;
  // Slices of input_tokens / output_tokens that bill at their own rate:
  // cached prompt tokens at the cached-input rate, audio tokens at the
  // audio rate. Subsets, already counted in the totals above. Optional so a
  // response from a backend that predates them still renders.
  cached_input_tokens?: number;
  audio_input_tokens?: number;
  audio_output_tokens?: number;
}

export interface TokenUsageSummary {
  input_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  total_tokens: number;
  audio_seconds: number;
  cached_input_tokens?: number;
  audio_input_tokens?: number;
  audio_output_tokens?: number;
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
  // JSON {model_id: seconds}. A budget the local-model fit test wrote for a
  // specific model; when the agent runs that model this wins over
  // interval_seconds, so it is what actually determines cadence.
  model_intervals: string;
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
    requested_model_id: string | null;
    model_id: string | null;
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

export type DesktopUpdateState =
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "needs_authorization"
  | "ready"
  | "applying"
  | "error";

export interface DesktopUpdateStatus {
  enabled: boolean;
  state: DesktopUpdateState;
  current_version?: string;
  available_version?: string;
  available_notes?: string;
  published_at?: string;
  platform_id?: string;
  filename?: string;
  size?: number;
  downloaded?: number;
  checked_at?: string;
  error?: string;
  blocked_reason?: string;
}

export interface DesktopUpdateController {
  status: DesktopUpdateStatus;
  check: () => Promise<void>;
  download: () => Promise<void>;
  cancel: () => Promise<void>;
  apply: () => Promise<void>;
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
  /** Runs on this machine or its network, so Privacy First mode allows it. */
  runs_locally?: boolean;
  /** Set when the model is served by a saved self-hosted endpoint. */
  endpoint_id?: string | null;
  recommendations?: ModelRecommendation[];
}

export interface ModelRecommendation {
  role: string;
  provider: string;
  recommended: boolean;
  source: "provider_default" | "local_fit";
  interval_seconds?: number | null;
  reasoning_effort?: string | null;
}

/** A self-hosted OpenAI-compatible server (LM Studio, Ollama, vLLM, LiteLLM). */
export interface CustomEndpointModel {
  id: string;
  label: string;
  /** Registry id to store on an agent, e.g. "endpoint:lm-studio:antares-1b". */
  model_id: string;
}

export interface CustomEndpoint {
  id: string;
  name: string;
  base_url: string;
  has_api_key: boolean;
  models: CustomEndpointModel[];
  enabled: boolean;
  on_prem: boolean;
  last_status: "ok" | "error" | "";
  last_error: string;
  last_checked_at: string | null;
}

export interface EndpointProbeResult {
  ok: boolean;
  message: string;
  served_models: string[];
  on_prem?: boolean;
}

// USD per 1M tokens at standard paid-tier rates (no long-context or
// cache-storage surcharges); null means no published rate. The cached and
// audio rates apply to the matching slices of a usage row; when one is null
// that slice prices at the plain input or output rate.
export interface ModelPricing {
  input_per_million: number | null;
  output_per_million: number | null;
  cached_input_per_million: number | null;
  audio_input_per_million: number | null;
  // USD per minute of audio. Set only for duration-billed models, whose
  // token rates are null in turn.
  per_minute: number | null;
  audio_output_per_million?: number | null;
}

// GET /api/models/pricing: rates keyed by model id; a null entry means the
// model is in the registry but has no published per-token pricing.
export interface ModelPricingResponse {
  as_of: string;
  models: Record<string, ModelPricing | null>;
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
  benchmark_contention_adjusted_real_time_factor: number | null;
  benchmark_peak_memory_mb: number | null;
  benchmark_measured_at: string | null;
  benchmark_validity: FitValidityStatus;
  benchmark_validity_reason: string;
  speaker_similarity_threshold: number;
  selection_reason: string;
}

export interface DiarizationBenchmarkResult {
  status: "passed" | "failed" | "unavailable";
  recommended_live_diarizer: "lightweight" | "sortformer";
  real_time_factor: number | null;
  contention_adjusted_real_time_factor: number | null;
  peak_memory_mb: number | null;
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

// Local Model Fit Test: keep-up speed of self-hosted text models per agent role.
export type FitVerdict = "green" | "yellow" | "red";
export type FitValidityStatus = "current" | "incompatible" | "superseded" | "aged";
export interface FitValidity {
  status: FitValidityStatus;
  reason: string;
  age_days: number | null;
}

export interface FitProfileLatency {
  latency_seconds: number;
  output_chars: number;
  tokens_per_second: number | null;
}

export interface FitRole {
  slug: string;
  name: string;
  prompt_profile: "short" | "long";
  latency_seconds: number;
  budget_seconds: number;
  verdict?: FitVerdict;
  recommended_interval_seconds?: number;
  changed?: boolean;
  // Post-call briefing agents run once at call end: no live budget, not editable.
  post_call: boolean;
  editable: boolean;
}

export type FitFeasibility = "feasible" | "marginal" | "no" | "";

export interface TextModelFit {
  model_id: string;
  model_name: string;
  status: "ok" | "failed";
  reason: string;
  short: FitProfileLatency | null;
  long: FitProfileLatency | null;
  roles: FitRole[];
  validity?: FitValidity;
}

export interface LocalFitRoleCatalogEntry {
  slug: string;
  name: string;
  prompt_profile: "short" | "long";
  default_interval: number;
  post_call: boolean;
}

export interface LocalServiceOption {
  key: string;
  label: string;
  local_options: { id: string; name: string }[];
  cloud_only: boolean;
  note: string;
}

export interface LocalModelUsage {
  id: string;
  name: string;
  usable_for: string[];
}

export interface LocalCapabilities {
  services: LocalServiceOption[];
  models: LocalModelUsage[];
}

export interface LocalFitSummary {
  has_local_text_models: boolean;
  models: { id: string; name: string }[];
  intervals: Record<string, number>;
  roles: LocalFitRoleCatalogEntry[];
  // Present on current backends; optional so an older backend still parses.
  capabilities?: LocalCapabilities;
  // The last run, persisted server-side so returning to the tab does not
  // discard a benchmark the user waited on. Null when none has been run.
  last_result?: LocalFitReport | null;
}

export interface LocalFitReport extends LocalFitSummary {
  text_models: TextModelFit[];
  contention: number;
  asr: AsrFitReport | null;
  measured_at?: string;
  validity?: FitValidity;
}

// Local transcription (ASR) keep-up: real-time factor per bundled ONNX model.
export interface AsrModelFit {
  model_id: string;
  model_name: string;
  status: "ok" | "failed";
  reason: string;
  audio_seconds: number;
  processing_seconds: number;
  real_time_factor: number | null;
  verdict?: FitVerdict | "";
  short_real_time_factor: number | null;
  live_feasibility?: FitFeasibility;
  validity?: FitValidity;
  estimated: boolean;
}

export interface AsrFitReport {
  audio_seconds: number;
  estimated: boolean;
  asr_models: AsrModelFit[];
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

export type PiiCategory =
  | "PERSON" | "ORG" | "LOCATION" | "EMAIL" | "PHONE" | "SSN" | "CARD" | "IP" | "ADDRESS";

export interface PiiProtectedTerm {
  value: string;
  category: PiiCategory;
}

export interface PiiShieldSettings {
  enabled: boolean;
  categories: PiiCategory[];
  ner: boolean;
  protected_terms: PiiProtectedTerm[];
  // Record every outbound model prompt, exactly as sent, to the prompt log.
  prompt_log: boolean;
}

export interface PiiEgressEntry {
  at: string;
  source: string;
  model_id: string;
  session_id: string | null;
  chars: number;
  tokens_present: boolean;
  blocked: boolean;
  leaks: { category: PiiCategory; value: string }[];
  prompt: string;
  truncated: boolean;
}

/** One set of model weights the app is fetching, or has fetched. */
export interface ModelDownload {
  key: string;
  label: string;
  /** What needs it, e.g. "PII Shield". */
  purpose: string;
  state: "queued" | "downloading" | "installed" | "error";
  downloaded: number;
  /** 0 when the source will not say how big the download is. */
  total: number;
  /** null when there is no total to divide by. */
  percent: number | null;
  error: string;
  updated_at: number;
}

export interface ModelDownloadsStatus {
  downloads: ModelDownload[];
  active: number;
  failed: number;
}

export interface PiiShieldStatus {
  settings: PiiShieldSettings;
  categories: { id: PiiCategory; label: string }[];
  ner: {
    state: "off" | "ready" | "not_downloaded" | "downloading" | "unavailable";
    error: string | null;
    model: string;
    download: ModelDownload | null;
  };
  coverage: {
    text: boolean;
    // With the shield on, audio is locked to local models by enforcement.
    enforced: boolean;
    transcription: { covered: boolean; model_id: string };
    // paused: a cloud gateway is configured but skipped while the shield is on.
    live_gateway: { covered: boolean; model_id: string; paused: boolean };
    documents: boolean;
    refinement: { enabled: boolean; model_id: string; interval_seconds: number };
  };
  vault: { entries: number };
  reveals_24h: { requests: number; tokens: number };
}

export interface PiiPreview {
  protected: string;
  findings: { text: string; category: PiiCategory; token: string; source: string; score: number }[];
  enabled: boolean;
}

export interface PiiSessionSummary {
  counts: Partial<Record<PiiCategory, number>>;
  total: number;
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
  // Set once the transcript refiner has rewritten the entry: the
  // transcriber's own text and when the current text was produced.
  raw_text?: string | null;
  refined_at?: string | null;
}

export interface SynthesisSectionItem {
  title: string;
  summary: string;
  rationale?: string;
  owner?: string;
  status?: string;
  /**
   * Live strategic signals only: the model's own ranking across all of its
   * sections, 1 being the most important right now. 0 or absent means it did
   * not rank the item, which sorts it after everything it did.
   */
  priority?: number;
  evidence_refs?: Record<string, unknown>[];
}

export interface SignalHistoryItem extends SynthesisSectionItem {
  section: string;
  first_seen: string;
  last_seen: string;
  count: number;
  model_id?: string;
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
  signal_history?: SignalHistoryItem[];
  signal_history_count: number;
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
  // "background": the socket went quiet without closing, so the drain is very
  // likely still running server-side and the view polls for completion.
  state: "idle" | "running" | "completed" | "background" | "timeout" | "error";
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

export type AgentActivityState =
  | "running"
  | "waiting"
  | "blocked"
  | "off"
  | "failing";

export interface AgentActivityOutcome {
  kind: string;
  detail: string;
  items: number;
  at: string;
  deduped?: number;
}

export interface AgentActivityError {
  kind: "timeout" | "truncated" | "api_error" | "refusal";
  detail: string;
  remedy: string;
  at: string;
}

export interface AgentActivityRecord {
  slug: string;
  name: string;
  trigger: "interval" | "event" | "stream" | "post_call";
  state: AgentActivityState;
  enabled: boolean;
  blocked_reason: string;
  remedy: string;
  interval_seconds: number | null;
  last_run_started_at: string | null;
  last_run_ms: number | null;
  next_due_at: string | null;
  last_outcome: AgentActivityOutcome | null;
  last_error: AgentActivityError | null;
  /** Active lens count; present only on the consolidated_analyst record. */
  lens_count?: number;
  counts: {
    runs: number;
    insights: number;
    /** Runs whose outcome saved new or adjusted insights. */
    productive?: number;
    deduped: number;
    errors: number;
  };
}

export interface CallHealth {
  privacy_first: boolean;
  degraded: boolean;
  degraded_reasons: string[];
  gateway: { state: "ok" | "reconnecting" | "off"; detail: string };
  transcription: { jobs: number; failed: number; last_error: string };
  diarization: { queued: number; shed: number };
}

export interface AgentActivitySnapshot {
  session_id: string;
  at: string;
  agents: AgentActivityRecord[];
  call: CallHealth;
}

export type WSMessage =
  | { type: "question"; data: Omit<Question, "session_id" | "starred" | "dismissed" | "created_at" | "answered" | "answer_summary" | "needs_followup" | "followup_question"> & { timestamp: string; is_followup?: boolean; item_type?: string } }
  | { type: "transcript"; data: TranscriptEntry }
  // The transcript refiner rewrote an entry; replaces the entry with that id.
  | { type: "transcript_updated"; data: TranscriptEntry }
  | { type: "interim_transcript"; data: { text: string } }
  | { type: "status"; data: WSStatusData }
  | { type: "agent_activity"; data: AgentActivitySnapshot }
  | { type: "synthesis_updated"; data: SessionSynthesis }
  | { type: "question_answered"; data: { id: string; answer_summary: string; needs_followup: boolean; followup_question: string } }
  | { type: "insight_updated"; data: Record<string, any> }
  | { type: "insight_elevated"; data: Record<string, any> & { old_type: string } };
