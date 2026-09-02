import type { AgentConfig, AppMeta, AsrFitReport, CallSegment, CustomEndpoint, DiarizationBenchmarkResult, DiarizationDiagnostics, Directive, Document, EndpointProbeResult, EnhanceInsightsResult, KnowledgeRecord, KnowledgeSource, LocalFitReport, LocalFitSummary, MeetingType, ModelInfo, ModelPricingResponse, Offering, PiiEgressEntry, PiiPreview, PiiSessionSummary, PiiShieldSettings, PiiShieldStatus, PrivacyConfig, Question, ReleaseNote, Session, SessionAgent, SessionGroup, SessionSynthesis, Speaker, TokenUsageSummary, TranscriptionConfig, TranscriptEntry } from "../types";

const BASE = "/api";

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // Non-JSON error body (e.g. a bare proxy error page); show it as-is.
    }
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Sessions
export const createSession = (name: string, data?: { meeting_type?: MeetingType; meeting_context?: string }) =>
  request<Session>("/sessions", { method: "POST", body: JSON.stringify({ name, ...data }) });

export const listSessions = () => request<Session[]>("/sessions");

export const getSession = (id: string) => request<Session>(`/sessions/${id}`);

export const updateSession = (id: string, data: Partial<Session>) =>
  request<Session>(`/sessions/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const deleteSession = (id: string) =>
  request<void>(`/sessions/${id}`, { method: "DELETE" });

export const enhanceInsights = (id: string) =>
  request<EnhanceInsightsResult>(`/sessions/${id}/enhance-insights`, { method: "POST" });

export const getEnhancementStatus = (id: string, runId: string) =>
  request<EnhanceInsightsResult>(`/sessions/${id}/enhance-insights/${runId}`);

export const getLatestEnhancement = (id: string) =>
  request<EnhanceInsightsResult | null>(`/sessions/${id}/enhance-insights/latest`);

export async function waitForEnhancement(
  id: string,
  initial: EnhanceInsightsResult,
  onProgress: (result: EnhanceInsightsResult) => void,
): Promise<EnhanceInsightsResult> {
  let result = initial;
  while (result.status === "running" && result.run_id) {
    onProgress(result);
    await new Promise((resolve) => setTimeout(resolve, 1000));
    result = await getEnhancementStatus(id, result.run_id);
  }
  return result;
}

export const getSynthesis = (id: string, mode = "post_call", includeHistory = false) =>
  request<SessionSynthesis | null>(
    `/sessions/${id}/synthesis?mode=${encodeURIComponent(mode)}&include_history=${includeHistory}`,
  );

export const refreshSynthesis = (id: string, mode = "post_call") =>
  request<SessionSynthesis>(`/sessions/${id}/synthesis/refresh?mode=${encodeURIComponent(mode)}`, { method: "POST" });

export const analyzeSession = (id: string) =>
  request<{ analyzed: number; session_id: string }>(`/sessions/${id}/analyze`, { method: "POST" });

export const getTokenUsage = (id: string) =>
  request<TokenUsageSummary>(`/sessions/${id}/token-usage`);

// Directives
export const createDirective = (sessionId: string, text: string) =>
  request<Directive>(`/sessions/${sessionId}/directives`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export const listDirectives = (sessionId: string) =>
  request<Directive[]>(`/sessions/${sessionId}/directives`);

export const updateDirective = (sessionId: string, id: string, data: Partial<Directive>) =>
  request<Directive>(`/sessions/${sessionId}/directives/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteDirective = (sessionId: string, id: string) =>
  request<void>(`/sessions/${sessionId}/directives/${id}`, { method: "DELETE" });

// Documents
export const uploadDocument = async (sessionId: string, file: File): Promise<Document> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/sessions/${sessionId}/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json()).detail ?? "";
    } catch {
      // non-JSON error body
    }
    throw new Error(detail || `Upload failed: ${res.status}`);
  }
  return res.json();
};

export const listDocuments = (sessionId: string) =>
  request<Document[]>(`/sessions/${sessionId}/documents`);

export const deleteDocument = (sessionId: string, id: string) =>
  request<void>(`/sessions/${sessionId}/documents/${id}`, { method: "DELETE" });

// Questions
export const listQuestions = (sessionId: string) =>
  request<Question[]>(`/sessions/${sessionId}/questions`);

export const updateQuestion = (sessionId: string, id: string, data: Partial<Question>) =>
  request<Question>(`/sessions/${sessionId}/questions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

// Speakers
export const createSpeaker = (
  sessionId: string,
  data: { name: string; role?: string; color?: string; is_user?: boolean; speaker_type?: "team" | "external" },
) =>
  request<Speaker>(`/sessions/${sessionId}/speakers`, { method: "POST", body: JSON.stringify(data) });

export const listSpeakers = (sessionId: string) =>
  request<Speaker[]>(`/sessions/${sessionId}/speakers`);

export const updateSpeaker = (sessionId: string, id: string, data: Partial<Speaker>) =>
  request<Speaker>(`/sessions/${sessionId}/speakers/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const mergeSpeaker = (sessionId: string, sourceId: string, targetId: string) =>
  request<{ source_speaker_id: string; target_speaker_id: string; transcript_entries_updated: number; questions_updated: number }>(
    `/sessions/${sessionId}/speakers/${sourceId}/merge`,
    { method: "POST", body: JSON.stringify({ target_speaker_id: targetId }) },
  );

export const deleteSpeaker = (sessionId: string, id: string) =>
  request<void>(`/sessions/${sessionId}/speakers/${id}`, { method: "DELETE" });

export const updateTranscriptSpeaker = (sessionId: string, transcriptId: string, speakerId: string | null) =>
  request<TranscriptEntry>(`/sessions/${sessionId}/transcripts/${transcriptId}`, { method: "PATCH", body: JSON.stringify({ speaker_id: speakerId }) });

export const listTranscripts = (sessionId: string) =>
  request<TranscriptEntry[]>(`/sessions/${sessionId}/transcripts`);

// Call Segments
export const listSegments = (sessionId: string) =>
  request<CallSegment[]>(`/sessions/${sessionId}/segments`);

// Import transcript/audio
export const importTranscript = async (sessionId: string, file: File): Promise<{ imported: number; filename: string }> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/sessions/${sessionId}/import/transcript`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`Import failed: ${res.status}`);
  return res.json();
};

export const importAudio = async (sessionId: string, file: File): Promise<{ imported: number; filename: string }> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/sessions/${sessionId}/import/audio`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`Import failed: ${res.status}`);
  return res.json();
};

// Models
export const listModels = () => request<ModelInfo[]>("/models");

export const getModelPricing = () => request<ModelPricingResponse>("/models/pricing");

// App metadata (version + release notes)
export const getAppMeta = () => request<AppMeta>("/meta");

export const listReleaseNotes = () => request<ReleaseNote[]>("/meta/release-notes");

export const segmentAudioUrl = (sessionId: string, segmentNumber: number) =>
  `${BASE}/sessions/${sessionId}/segments/${segmentNumber}/audio`;

export const retranscribeSession = (sessionId: string, modelId: string) =>
  request<{ entries: number }>(`/sessions/${sessionId}/retranscribe`, {
    method: "POST",
    body: JSON.stringify({ model_id: modelId }),
  });

export const chat = (modelId: string, sessionIds: string[], messages: { role: string; content: string }[]) =>
  request<{ reply: string }>("/chat", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, session_ids: sessionIds, messages }),
  });

// A self-hosted endpoint can hang for LLM_SELF_HOSTED_TIMEOUT_SECONDS (900s)
// and the cloud path has no explicit timeout either; the live ask bar's
// target is 4 seconds, so a client-side abort keeps a stuck request from
// blocking every later ask for minutes (ALP-178). request() already forwards
// any RequestInit field, including signal, so no change there is needed.
const ASK_TIMEOUT_MS = 60_000;

export const askSession = (sessionId: string, modelId: string, question: string) =>
  request<Question>(`/sessions/${sessionId}/ask`, {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, question }),
    signal: AbortSignal.timeout(ASK_TIMEOUT_MS),
  });

// Credentials (workspace API keys)
export interface CredentialInfo {
  provider: string;
  configured: boolean;
  env_fallback: boolean;
  masked: string;
  connected: boolean;
}

export const listCredentials = () => request<CredentialInfo[]>("/credentials");

export const saveCredential = (provider: string, apiKey: string) =>
  request<CredentialInfo & { message?: string }>(`/credentials/${provider}`, {
    method: "PUT",
    body: JSON.stringify({ api_key: apiKey }),
  });

export const deleteCredential = (provider: string) =>
  request<void>(`/credentials/${provider}`, { method: "DELETE" });

export const testCredential = (provider: string) =>
  request<{ ok: boolean; message: string }>(`/credentials/${provider}/test`, { method: "POST" });

// Self-hosted OpenAI-compatible endpoints (LM Studio, Ollama, vLLM, LiteLLM).
// Each endpoint's models become named entries in the model list, so they are
// managed here rather than as a single provider credential.
export const OPENAI_COMPATIBLE_PROVIDER = "openai-compatible";

export interface EndpointPayload {
  name?: string;
  base_url?: string;
  /** Omit to keep the stored key; empty string clears it. */
  api_key?: string;
  models?: { id: string; label?: string }[];
  enabled?: boolean;
  confirm_off_prem?: boolean;
}

export const listEndpoints = () => request<CustomEndpoint[]>("/endpoints");

export const createEndpoint = (data: EndpointPayload) =>
  request<CustomEndpoint>("/endpoints", { method: "POST", body: JSON.stringify(data) });

export const updateEndpoint = (id: string, data: EndpointPayload) =>
  request<CustomEndpoint>(`/endpoints/${id}`, { method: "PUT", body: JSON.stringify(data) });

export const deleteEndpoint = (id: string) =>
  request<void>(`/endpoints/${id}`, { method: "DELETE" });

export const testEndpoint = (id: string) =>
  request<EndpointProbeResult & { endpoint: CustomEndpoint }>(`/endpoints/${id}/test`, {
    method: "POST",
  });

/** Check a base URL before saving it, and list the models it serves. */
export const probeEndpoint = (baseUrl: string, apiKey = "") =>
  request<EndpointProbeResult>("/endpoints/probe", {
    method: "POST",
    body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
  });

// Diagnostics
export const getDiarizationDiagnostics = () =>
  request<DiarizationDiagnostics>("/diagnostics/diarization");

export const updateDiarizationConfig = (data: { selected_live_diarizer?: "lightweight" | "sortformer"; speaker_similarity_threshold?: number }) =>
  request<DiarizationDiagnostics>("/diagnostics/diarization/config", {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export interface VoiceProfileStatus {
  enrolled: boolean;
}

export const getVoiceProfileStatus = () =>
  request<VoiceProfileStatus>("/diagnostics/diarization/voice-profile");

export const replaceVoiceProfile = async (file: File): Promise<VoiceProfileStatus> => {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${BASE}/diagnostics/diarization/voice-profile`, {
    method: "PUT",
    body: form,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
};

export const deleteVoiceProfile = () =>
  request<void>("/diagnostics/diarization/voice-profile", { method: "DELETE" });

// Local Model Fit Test
export const getLocalFitSummary = () =>
  request<LocalFitSummary>("/diagnostics/local-fit");

export const runLocalFit = () =>
  request<LocalFitReport>("/diagnostics/local-fit/run", { method: "POST" });

export const applyLocalFitIntervals = (
  modelId: string,
  updates: { slug: string; interval_seconds: number }[],
) =>
  request<{ applied: Record<string, number> }>("/diagnostics/local-fit/apply", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, updates }),
  });

export const runAsrFit = async (file: File): Promise<AsrFitReport> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/diagnostics/local-fit/asr`, { method: "POST", body: form });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // Non-JSON error body; show it as-is.
    }
    throw new Error(detail);
  }
  return res.json();
};

export const getPrivacyConfig = () => request<PrivacyConfig>("/privacy");

export const updatePrivacyConfig = (localOnly: boolean) =>
  request<PrivacyConfig>("/privacy", {
    method: "PUT",
    body: JSON.stringify({ local_only: localOnly }),
  });

export const getPiiShield = () => request<PiiShieldStatus>("/pii-shield");

export const updatePiiShield = (update: Partial<PiiShieldSettings>) =>
  request<PiiShieldStatus>("/pii-shield", { method: "PUT", body: JSON.stringify(update) });

export const previewPiiShield = (text: string, sessionId?: string) =>
  request<PiiPreview>("/pii-shield/preview", {
    method: "POST",
    body: JSON.stringify({ text, session_id: sessionId ?? null }),
  });

export const getPiiEgress = (limit = 50) =>
  request<{ enabled: boolean; entries: PiiEgressEntry[] }>(`/pii-shield/egress?limit=${limit}`);

export const clearPiiEgress = () => request<void>("/pii-shield/egress", { method: "DELETE" });

export const installPiiNer = () =>
  request<PiiShieldStatus["ner"]>("/pii-shield/ner/install", { method: "POST" });

export const getSessionPiiSummary = (sessionId: string) =>
  request<PiiSessionSummary>(`/sessions/${sessionId}/pii/summary`);

export const protectSessionPii = (sessionId: string) =>
  request<{ changed: Record<string, number>; vault_entries: number }>(`/sessions/${sessionId}/pii/protect`, {
    method: "POST",
  });

export const getTranscriptionConfig = () =>
  request<TranscriptionConfig>("/diagnostics/transcription");

export interface TranscriptionReadiness {
  ready: boolean;
  model_id: string;
  provider: string;
  reason: string;
}

export const getTranscriptionReadiness = () =>
  request<TranscriptionReadiness>("/diagnostics/transcription/readiness");

export const updateTranscriptionConfig = (data: { batch_model_id?: string; live_preview_model_id?: string }) =>
  request<TranscriptionConfig>("/diagnostics/transcription/config", {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const runSortformerBenchmark = async (file: File): Promise<DiarizationBenchmarkResult> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/diagnostics/diarization/sortformer/benchmark`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Benchmark failed ${res.status}: ${text}`);
  }
  return res.json();
};

// Offerings
export const listOfferings = (vendor?: string, category?: string) => {
  const params = new URLSearchParams();
  if (vendor) params.set("vendor", vendor);
  if (category) params.set("category", category);
  params.set("active_only", "false");
  const qs = params.toString();
  return request<Offering[]>(`/offerings${qs ? `?${qs}` : ""}`);
};

export const createOffering = (data: Omit<Offering, "id" | "created_at" | "updated_at">) =>
  request<Offering>("/offerings", { method: "POST", body: JSON.stringify(data) });

export const updateOffering = (id: string, data: Partial<Offering>) =>
  request<Offering>(`/offerings/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const deleteOffering = (id: string) =>
  request<void>(`/offerings/${id}`, { method: "DELETE" });

export const importOfferings = async (file: File): Promise<{ created: number; skipped: number; total_rows: number }> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/offerings/import`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Import failed: ${res.status}`);
  return res.json();
};

export const seedOfferings = (replace = false) =>
  request<{ created?: number; replaced?: boolean; message?: string }>(`/offerings/seed${replace ? "?replace=true" : ""}`, { method: "POST" });

export const listOfferingVendors = () => request<string[]>("/offerings/vendors");
export const listOfferingCategories = () => request<string[]>("/offerings/categories");
export const listOfferingTags = () => request<string[]>("/offerings/tags");

// Knowledge Sources
export const listKnowledgeSources = () => request<KnowledgeSource[]>("/knowledge");

export const createKnowledgeSource = (data: { name: string; source_type: string; description?: string }) =>
  request<KnowledgeSource>("/knowledge", { method: "POST", body: JSON.stringify(data) });

export const updateKnowledgeSource = (id: string, data: Partial<KnowledgeSource>) =>
  request<KnowledgeSource>(`/knowledge/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const deleteKnowledgeSource = (id: string) =>
  request<{ ok: boolean }>(`/knowledge/${id}`, { method: "DELETE" });

export const listKnowledgeRecords = (sourceId: string) =>
  request<KnowledgeRecord[]>(`/knowledge/${sourceId}/records`);

export const createKnowledgeRecord = (sourceId: string, data: { title: string; body: string }) =>
  request<KnowledgeRecord>(`/knowledge/${sourceId}/records`, { method: "POST", body: JSON.stringify(data) });

export const updateKnowledgeRecord = (recordId: string, data: Partial<KnowledgeRecord>) =>
  request<KnowledgeRecord>(`/knowledge/records/${recordId}`, { method: "PATCH", body: JSON.stringify(data) });

export const deleteKnowledgeRecord = (recordId: string) =>
  request<{ ok: boolean }>(`/knowledge/records/${recordId}`, { method: "DELETE" });

export const importKnowledgeRecords = async (sourceId: string, file: File): Promise<{ created: number; skipped: number; total_rows: number }> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/knowledge/${sourceId}/records/import`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Import failed: ${res.status}`);
  return res.json();
};

export const uploadKnowledgeFile = async (sourceId: string, file: File): Promise<{ record_id: string; title: string; chars: number }> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/knowledge/${sourceId}/files`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
};

// Agents
export const listAgents = () => request<AgentConfig[]>("/agents");
export const updateAgent = (slug: string, data: Partial<AgentConfig>) =>
  request<AgentConfig>(`/agents/${slug}`, { method: "PATCH", body: JSON.stringify(data) });
export const resetAgentPrompt = (slug: string) =>
  request<AgentConfig>(`/agents/reset/${slug}`, { method: "POST" });

// Session Agent Overrides
export const listSessionAgents = (sessionId: string) =>
  request<SessionAgent[]>(`/sessions/${sessionId}/agents`);
export const setSessionAgents = (sessionId: string, overrides: { agent_slug: string; enabled: boolean }[]) =>
  request<SessionAgent[]>(`/sessions/${sessionId}/agents`, { method: "PUT", body: JSON.stringify(overrides) });

// Session Groups
export const listGroups = () => request<SessionGroup[]>("/groups");
export const createGroup = (name: string) =>
  request<SessionGroup>("/groups", { method: "POST", body: JSON.stringify({ name }) });
export const updateGroup = (id: string, data: Partial<SessionGroup>) =>
  request<SessionGroup>(`/groups/${id}`, { method: "PATCH", body: JSON.stringify(data) });
export const deleteGroup = (id: string) =>
  request<void>(`/groups/${id}`, { method: "DELETE" });
