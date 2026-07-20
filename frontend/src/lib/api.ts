const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, {
    credentials: "same-origin",
    headers:
      init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : undefined,
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch { /* noop */ }
    throw new ApiError(resp.status, detail);
  }
  const ct = resp.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? resp.json() : resp.text()) as Promise<T>;
}

export const get = <T,>(path: string) => request<T>(path);
export const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
export const put = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const postForm = <T,>(path: string, form: FormData) =>
  request<T>(path, { method: "POST", body: form });

/* ─── types ─── */
export interface User {
  id: string; username: string; display_name_ar: string; role: string;
}
export interface Case {
  id: string; case_number: string; title_ar: string; location_ar: string;
  investigator_name_ar: string; notes_ar: string;
  incident_date_gregorian: string | null; incident_date_hijri: string | null;
  status: string; face_blur_enabled: boolean; created_at: string;
  media_count?: number; pending_review?: number;
  last_run?: { id: string; status: string; run_number: number } | null;
  runs?: RunSummary[];
}
export interface RunSummary {
  id: string; run_number: number; status: string; model_mode: string;
  started_at: string; finished_at: string | null;
}
export interface Media {
  id: string; case_id: string; kind: "image" | "video";
  original_filename: string; content_sha256: string; size_bytes: number;
  mime: string; width: number | null; height: number | null;
  duration_s: number | null; fps: number | null;
  source_label_ar: string; source_type: string; excluded: boolean;
  metadata_creation_time: string | null;
  exif: Record<string, unknown> & { gps?: { lat: number; lon: number } };
  uploaded_at: string; duplicate?: boolean;
}
export interface Step {
  stage: number; stage_name_ar: string; status: string;
  progress_current: number; progress_total: number; error: string | null;
}
export interface Run {
  id: string; case_id: string; run_number: number; status: string;
  model_mode: string; started_at: string; finished_at: string | null;
  error: string | null; steps?: Step[];
  model_snapshot?: Record<string, string>;
  options?: { thinking_policy?: string };
}
export interface Entity {
  id: string; run_id: string; entity_seq: number; code: string; label_ar: string;
  canonical_name_ar: string; category: string; category_ar: string;
  description_ar: string; forensic_significance_ar: string;
  handling_recommendation_ar: string; merge_rationale_ar: string;
  confidence_max: number; confidence_mean: number;
  needs_human_review: boolean; review_status: string; review_note_ar: string;
  reviewed_at: string | null; best_frame_id: string | null;
  has_crop: boolean; has_before_after: boolean;
  sources: string[]; observations: number;
}
export interface Observation {
  id: string; frame_id: string; media_file_id: string; media_label: string;
  timestamp_source_s: number | null; timestamp_global_s: number | null;
  bbox: [number, number, number, number]; confidence: number; state: string;
}
export interface EntityDetail extends Entity {
  observations: any; events: TimelineEventItem[];
}
export interface TimelineEventItem {
  id?: string; entity_id: string; entity_seq?: number; label_ar?: string;
  name_ar?: string; category?: string; event_type: string;
  timestamp_source_s: number | null; timestamp_global_s: number | null;
  media_file_id?: string | null; frame_id?: string | null; description_ar: string;
}
export interface ReportRow {
  id: string; kind: string; version: number; file_sha256: string;
  size_bytes: number; pdf_variant: string | null; audit_head_hash: string;
  generated_at: string;
}
export interface AuditRow {
  id: number; ts: string; actor_label: string; action: string;
  object_type: string; object_id: string; detail: Record<string, unknown>;
  entry_hash: string;
}
export interface OffsetRow {
  media_file_id: string; media_label: string; offset_seconds: number;
  method: string; note_ar: string;
}
export interface ModelCallsSummary {
  totals: { calls: number; input_tokens: number; output_tokens: number;
    cost_usd: number; failed: number; repaired: number };
  by_purpose: Record<string, { calls: number; cost_usd: number;
    input_tokens: number; output_tokens: number }>;
  calls: Array<Record<string, unknown>>;
}
export interface ComparisonRow {
  id: string; kind: string; entity_id: string | null; detail_ar: string;
  confidence: number;
}
export interface PhotoQuestion {
  id: string; media_file_id: string; question_ar: string; answer_ar: string;
  confidence: number; cannot_determine: boolean;
  grounded_boxes: Array<{ label_ar: string; bbox: [number, number, number, number] }>;
  thinking_used: boolean; created_at: string;
}
export interface VideoIndexInfo {
  status: string; // none | queued | building | ready | failed
  id?: string; media_file_id?: string; embedder_name?: string; dim?: number;
  fps?: number; frames_seen?: number; frames_indexed?: number;
  progress_current?: number; progress_total?: number;
  duration_s?: number | null; error?: string | null; built_at?: string | null;
}
export interface VideoClip {
  media_file_id: string; media_label: string;
  ts_in: number; ts_out: number; ts_best: number; retrieval_score: number;
  status: "confirmed" | "uncertain" | "rejected"; confidence: number;
  label_ar: string; description_ar: string;
  bbox: [number, number, number, number] | null;
  thumb_path: string; model_call_ids: string[];
}
export interface VideoSearchResults {
  clips: VideoClip[]; rejected: VideoClip[];
  coverage: {
    fps: number; frames_seen: number; frames_indexed: number;
    media_searched: number;
    skipped_media: Array<{ media_file_id: string; label: string; reason: string }>;
    statement_ar: string;
  };
  stats: {
    candidates: number; confirmed: number; uncertain: number; rejected: number;
    translate_ms?: number; retrieve_ms?: number; verify_ms?: number;
  };
}
export interface VideoSearchRow {
  id: string; case_id: string; query_ar: string; status: string;
  sensitive: boolean; progress_current: number; progress_total: number;
  query_variants: string[]; media_ids: string[];
  results: VideoSearchResults | null; latency_ms: number;
  error: string | null; created_at: string; finished_at: string | null;
}
