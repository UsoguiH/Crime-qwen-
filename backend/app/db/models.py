from datetime import datetime

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer,
                        MetaData, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core import make_id, utcnow

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)


def pk() -> Mapped[str]:
    return mapped_column(String(32), primary_key=True, default=make_id)


def ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = pk()
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name_ar: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # investigator | reviewer | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ts()


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = pk()
    case_number: Mapped[str] = mapped_column(String(100), unique=True)
    title_ar: Mapped[str] = mapped_column(String(300))
    location_ar: Mapped[str] = mapped_column(String(300), default="")
    investigator_name_ar: Mapped[str] = mapped_column(String(200), default="")
    notes_ar: Mapped[str] = mapped_column(Text, default="")
    incident_date_gregorian: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    incident_date_hijri: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new | analyzing | complete
    face_blur_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (UniqueConstraint("case_id", "content_sha256"),)
    id: Mapped[str] = pk()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # image | video
    original_filename: Mapped[str] = mapped_column(String(400))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str] = mapped_column(String(500))  # relative to DATA_DIR
    size_bytes: Mapped[int] = mapped_column(Integer)
    mime: Mapped[str] = mapped_column(String(100))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    exif_json: Mapped[dict | None] = mapped_column(JSON)
    ffprobe_json: Mapped[dict | None] = mapped_column(JSON)
    metadata_creation_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_label_ar: Mapped[str] = mapped_column(String(200), default="")
    source_type: Mapped[str] = mapped_column(String(20), default="other")  # cctv|bodycam|handheld|photo|other
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = ts()


class Frame(Base):
    __tablename__ = "frames"
    id: Mapped[str] = pk()
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id"), index=True)
    frame_index: Mapped[int] = mapped_column(Integer, default=0)
    timestamp_s: Mapped[float | None] = mapped_column(Float, index=True)  # NULL for still images
    stored_path: Mapped[str] = mapped_column(String(500))
    phash: Mapped[str | None] = mapped_column(String(32), index=True)
    selection_reason: Mapped[str] = mapped_column(String(20), default="image")  # scene_change|uniform|image
    dropped_dedup: Mapped[bool] = mapped_column(Boolean, default=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (UniqueConstraint("case_id", "run_number"),)
    id: Mapped[str] = pk()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    run_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    # queued|running|paused|failed|completed|completed_with_errors|cancelled
    model_mode: Mapped[str] = mapped_column(String(10), default="mock")
    model_snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    prompt_hashes_json: Mapped[dict | None] = mapped_column(JSON)
    thresholds_json: Mapped[dict | None] = mapped_column(JSON)
    options_json: Mapped[dict | None] = mapped_column(JSON)
    integrity_check_json: Mapped[dict | None] = mapped_column(JSON)
    started_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = pk()
    kind: Mapped[str] = mapped_column(String(30))
    # run_pipeline|render_report|rebuild_timeline|index_video|video_search
    run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    created_at: Mapped[datetime] = ts()
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class RunStep(Base):
    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "stage"),)
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    stage: Mapped[int] = mapped_column(Integer)  # 0..9
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending|running|completed|completed_with_errors|failed|skipped
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint_json: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class TriageResult(Base):
    __tablename__ = "triage_results"
    __table_args__ = (UniqueConstraint("run_id", "frame_id"),)
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    frame_id: Mapped[str] = mapped_column(ForeignKey("frames.id"), index=True)
    relevance: Mapped[float] = mapped_column(Float, default=0.0)
    scene_type_ar: Mapped[str] = mapped_column(String(300), default="")
    contains_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    complexity: Mapped[str] = mapped_column(String(10), default="low")  # low|medium|high
    human_presence_suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    selected_for_detection: Mapped[bool] = mapped_column(Boolean, default=False)
    model_call_id: Mapped[str | None] = mapped_column(String(32))
    raw_json: Mapped[dict | None] = mapped_column(JSON)


class Detection(Base):
    __tablename__ = "detections"
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    frame_id: Mapped[str] = mapped_column(ForeignKey("frames.id"), index=True)
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id"), index=True)
    local_id: Mapped[str] = mapped_column(String(50), default="")
    name_ar: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(30), index=True)
    bbox_raw_json: Mapped[list | None] = mapped_column(JSON)
    bbox_x1: Mapped[float] = mapped_column(Float, default=0.0)  # normalized 0..1
    bbox_y1: Mapped[float] = mapped_column(Float, default=0.0)
    bbox_x2: Mapped[float] = mapped_column(Float, default=0.0)
    bbox_y2: Mapped[float] = mapped_column(Float, default=0.0)
    coord_space: Mapped[str] = mapped_column(String(20), default="rel1000")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    description_ar: Mapped[str] = mapped_column(Text, default="")
    location_description_ar: Mapped[str] = mapped_column(Text, default="")
    forensic_significance_ar: Mapped[str] = mapped_column(Text, default="")
    handling_recommendation_ar: Mapped[str] = mapped_column(Text, default="")
    visible_text_ar: Mapped[str] = mapped_column(Text, default="")
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    thinking_used: Mapped[bool] = mapped_column(Boolean, default=False)
    model_call_id: Mapped[str | None] = mapped_column(String(32))
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = ts()


class EvidenceEntity(Base):
    __tablename__ = "evidence_entities"
    __table_args__ = (UniqueConstraint("run_id", "entity_seq"),)
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    entity_seq: Mapped[int] = mapped_column(Integer)  # displayed «دليل ٠٠١», code E-001
    canonical_name_ar: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(30), index=True)
    description_ar: Mapped[str] = mapped_column(Text, default="")
    forensic_significance_ar: Mapped[str] = mapped_column(Text, default="")
    handling_recommendation_ar: Mapped[str] = mapped_column(Text, default="")
    confidence_max: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_mean: Mapped[float] = mapped_column(Float, default=0.0)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    best_frame_id: Mapped[str | None] = mapped_column(ForeignKey("frames.id"))
    best_detection_id: Mapped[str | None] = mapped_column(ForeignKey("detections.id"))
    merge_rationale_ar: Mapped[str] = mapped_column(Text, default="")
    merged_from_json: Mapped[list | None] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending|confirmed|rejected|edited
    review_edits_json: Mapped[dict | None] = mapped_column(JSON)
    review_note_ar: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntityObservation(Base):
    __tablename__ = "entity_observations"
    id: Mapped[str] = pk()
    entity_id: Mapped[str] = mapped_column(ForeignKey("evidence_entities.id"), index=True)
    detection_id: Mapped[str] = mapped_column(ForeignKey("detections.id"))
    frame_id: Mapped[str] = mapped_column(ForeignKey("frames.id"))
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id"), index=True)
    timestamp_source_s: Mapped[float | None] = mapped_column(Float)
    timestamp_global_s: Mapped[float | None] = mapped_column(Float, index=True)
    bbox_x1: Mapped[float] = mapped_column(Float, default=0.0)
    bbox_y1: Mapped[float] = mapped_column(Float, default=0.0)
    bbox_x2: Mapped[float] = mapped_column(Float, default=0.0)
    bbox_y2: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String(10), default="present")  # present|moved


class SourceOffset(Base):
    __tablename__ = "source_offsets"
    __table_args__ = (UniqueConstraint("run_id", "media_file_id"),)
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id"))
    offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(20), default="unanchored")  # auto_metadata|manual|unanchored
    set_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    note_ar: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("evidence_entities.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(20))
    # first_seen|moved|disappeared|reappeared|last_seen
    timestamp_global_s: Mapped[float | None] = mapped_column(Float, index=True)
    timestamp_source_s: Mapped[float | None] = mapped_column(Float)
    media_file_id: Mapped[str | None] = mapped_column(ForeignKey("media_files.id"))
    frame_id: Mapped[str | None] = mapped_column(ForeignKey("frames.id"))
    description_ar: Mapped[str] = mapped_column(Text, default="")
    source_observation_ids_json: Mapped[list | None] = mapped_column(JSON)


class ComparisonFinding(Base):
    __tablename__ = "comparison_findings"
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # multi_source_match|time_conflict|present_absent
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_entities.id"))
    media_file_ids_json: Mapped[list | None] = mapped_column(JSON)
    detail_ar: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    model_call_id: Mapped[str | None] = mapped_column(String(32))
    raw_json: Mapped[dict | None] = mapped_column(JSON)


class Narrative(Base):
    __tablename__ = "narratives"
    __table_args__ = (UniqueConstraint("run_id", "section", "version"),)
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    section: Mapped[str] = mapped_column(String(60))
    content_ar: Mapped[str] = mapped_column(Text, default="")
    cited_entity_ids_json: Mapped[list | None] = mapped_column(JSON)
    validator_report_json: Mapped[dict | None] = mapped_column(JSON)
    model_call_id: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = ts()


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("run_id", "kind", "version"),)
    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(15))  # pdf_a|docx|bundle_zip
    file_path: Mapped[str] = mapped_column(String(500))
    file_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    audit_head_hash: Mapped[str] = mapped_column(String(64), default="")
    manifest_json: Mapped[dict | None] = mapped_column(JSON)
    pdf_variant: Mapped[str | None] = mapped_column(String(20))
    generated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    generated_at: Mapped[datetime] = ts()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor_user_id: Mapped[str | None] = mapped_column(String(32))
    actor_label: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(60), index=True)
    object_type: Mapped[str] = mapped_column(String(30), default="")
    object_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), index=True)


class ModelCall(Base):
    __tablename__ = "model_calls"
    id: Mapped[str] = pk()
    run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    stage: Mapped[int | None] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(20))  # triage|detect|aggregate|compare|narrative|repair|health
    provider: Mapped[str] = mapped_column(String(20), default="mock")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_file: Mapped[str] = mapped_column(String(120), default="")
    prompt_sha256: Mapped[str] = mapped_column(String(64), default="")
    frame_id: Mapped[str | None] = mapped_column(String(32))
    media_file_id: Mapped[str | None] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(15), default="ok")  # ok|repaired|failed
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = ts()


class PhotoQuestion(Base):
    __tablename__ = "photo_questions"
    id: Mapped[str] = pk()
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    question_ar: Mapped[str] = mapped_column(Text)
    answer_ar: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    cannot_determine: Mapped[bool] = mapped_column(Boolean, default=False)
    grounded_boxes_json: Mapped[list | None] = mapped_column(JSON)
    thinking_used: Mapped[bool] = mapped_column(Boolean, default=True)
    model_call_id: Mapped[str | None] = mapped_column(String(32))
    asked_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts()


class VideoIndex(Base):
    """Retrieval index for one video: frames sampled at a fixed rate, embedded
    locally, vectors stored in an .npz sidecar under derived/. One per media."""
    __tablename__ = "video_indexes"
    id: Mapped[str] = pk()
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id"), unique=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued|building|ready|failed
    embedder_name: Mapped[str] = mapped_column(String(200), default="")
    dim: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=1.0)
    frames_seen: Mapped[int] = mapped_column(Integer, default=0)      # decoded
    frames_indexed: Mapped[int] = mapped_column(Integer, default=0)   # kept after still-skip
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    sidecar_path: Mapped[str] = mapped_column(String(500), default="")
    duration_s: Mapped[float | None] = mapped_column(Float)
    params_json: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = ts()
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VideoSearch(Base):
    """One natural-language search over a case's indexed videos: retrieve →
    cluster → VLM-verify. Results (clips + honest coverage) stored as JSON."""
    __tablename__ = "video_searches"
    id: Mapped[str] = pk()
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    query_ar: Mapped[str] = mapped_column(Text)
    query_variants_json: Mapped[dict | None] = mapped_column(JSON)
    media_ids_json: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued|translating|retrieving|verifying|done|failed
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    results_json: Mapped[dict | None] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value_json: Mapped[dict | None] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


EVIDENCE_CATEGORIES = [
    "weapons", "biological", "impressions", "documents_devices",
    "scene_markers", "trace", "human_presence",
]

CATEGORY_NAMES_AR = {
    "weapons": "أسلحة",
    "biological": "أدلة بيولوجية",
    "impressions": "انطباعات وآثار",
    "documents_devices": "وثائق وأجهزة",
    "scene_markers": "علامات المشهد",
    "trace": "مواد أثرية",
    "human_presence": "وجود بشري",
}
