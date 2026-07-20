"""STRICT schemas for every Qwen3-VL structured output.

All fields are required (nullable-by-union where needed, never defaulted) so the
same schema drives OpenAI-style strict json_schema enforcement on OpenRouter/vLLM
and Pydantic validation client-side. `strict_response_format()` scrubs constraint
keywords that some providers reject — numeric bounds stay enforced by Pydantic.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "weapons", "biological", "impressions", "documents_devices",
    "scene_markers", "trace", "human_presence",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TriageItem(StrictModel):
    frame_ref: str
    relevance: float = Field(ge=0, le=1)
    scene_type_ar: str
    contains_evidence: bool
    complexity: Literal["low", "medium", "high"]
    human_presence_suspected: bool


class TriageBatch(StrictModel):
    items: list[TriageItem]


class DetectionItem(StrictModel):
    local_id: str
    name_ar: str
    category: Category
    bbox_2d: list[int] = Field(min_length=4, max_length=4)  # [x1,y1,x2,y2] relative 0–1000
    confidence: float = Field(ge=0, le=1)
    description_ar: str
    location_description_ar: str
    forensic_significance_ar: str
    handling_recommendation_ar: str
    visible_text_ar: str        # any text visible in the image, described as data ("" if none)
    uncertainty_notes_ar: str   # explicit uncertainty ("" if none)


class DetectionResult(StrictModel):
    detections: list[DetectionItem]
    scene_summary_ar: str


class AggregateEntity(StrictModel):
    member_cluster_ids: list[str]
    canonical_name_ar: str
    category: Category
    description_ar: str
    forensic_significance_ar: str
    handling_recommendation_ar: str
    merge_rationale_ar: str


class AggregateResult(StrictModel):
    entities: list[AggregateEntity]


class ComparisonItem(StrictModel):
    kind: Literal["multi_source_match", "time_conflict", "present_absent"]
    entity_codes: list[str]
    detail_ar: str
    confidence: float = Field(ge=0, le=1)


class ComparisonResult(StrictModel):
    findings: list[ComparisonItem]


class NarrativeSection(StrictModel):
    content_ar: str
    cited_entity_codes: list[str]


class BoxRefine(StrictModel):
    bbox_2d: list[int] = Field(min_length=4, max_length=4)
    visible: bool


class GroundedBox(StrictModel):
    label_ar: str
    bbox_2d: list[int] = Field(min_length=4, max_length=4)


class PhotoAnswer(StrictModel):
    answer_ar: str
    confidence: float = Field(ge=0, le=1)
    cannot_determine: bool
    grounded_boxes: list[GroundedBox]


class QueryTranslation(StrictModel):
    """Arabic search query → English retrieval variants for the CLIP-family
    text encoder + a sensitivity flag (weapons/violence ⇒ double verification)."""
    english_variants: list[str]
    sensitive: bool


class VideoVerify(StrictModel):
    """Verdict on one candidate CCTV frame against the search query.
    bbox_2d is the single most relevant object (relative 0–1000) or null."""
    match: bool
    confidence: float = Field(ge=0, le=1)
    label_ar: str
    description_ar: str
    bbox_2d: list[int] | None


_ALLOWED_KEYS = {
    "type", "properties", "required", "additionalProperties", "items",
    "enum", "anyOf", "$defs", "$ref", "description",
}
_NAMED_MAPS = {"properties", "$defs"}  # keys here are arbitrary names — keep them


def _scrub(node: Any, named: bool = False) -> Any:
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if named:
                out[key] = _scrub(value)
            elif key in _NAMED_MAPS:
                out[key] = _scrub(value, named=True)
            elif key in _ALLOWED_KEYS:
                out[key] = _scrub(value)
        return out
    if isinstance(node, list):
        return [_scrub(v) for v in node]
    return node


def strict_response_format(model: type[BaseModel], name: str) -> dict:
    schema = _scrub(model.model_json_schema())
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }
