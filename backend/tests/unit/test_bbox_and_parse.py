import pytest

from app.modelclient.client import VLMClient
from app.pipeline.stages.s3_detect import _sanitize_bbox
from app.schemas.model_io import DetectionResult, strict_response_format
from app.services.annotate import BoxSpec, _pixels


def test_sanitize_bbox_clamps_and_orders():
    assert _sanitize_bbox([100, 200, 300, 400]) == (100, 200, 300, 400)
    assert _sanitize_bbox([300, 400, 100, 200]) == (100, 200, 300, 400)
    assert _sanitize_bbox([-50, 0, 1200, 900]) == (0, 0, 1000, 900)
    assert _sanitize_bbox([10, 10, 10, 10]) is None
    assert _sanitize_bbox([1, 2, 3]) is None


def test_pixel_mapping_relative_to_original():
    # rel-1000 → normalized → pixels of the ORIGINAL image
    box = BoxSpec(x1=417 / 1000, y1=419 / 1000, x2=717 / 1000, y2=469 / 1000,
                  entity_seq=1)
    x1, y1, x2, y2 = _pixels(box, 1200, 800)
    assert (x1, y1) == (500, 335)
    assert (x2, y2) == (860, 375)


def test_parse_handles_fences_and_prose():
    raw = 'نتيجة:\n```json\n{"detections": [], "scene_summary_ar": "لا شيء"}\n```'
    value = VLMClient._parse(raw, DetectionResult)
    assert value.scene_summary_ar == "لا شيء"

    raw2 = 'مقدمة {"detections": [], "scene_summary_ar": "نص"} خاتمة'
    value2 = VLMClient._parse(raw2, DetectionResult)
    assert value2.scene_summary_ar == "نص"


def test_parse_rejects_wrong_schema():
    with pytest.raises(Exception):
        VLMClient._parse('{"wrong": true}', DetectionResult)


def test_strict_schema_scrubbed():
    rf = strict_response_format(DetectionResult, "detect")
    assert rf["json_schema"]["strict"] is True
    schema = rf["json_schema"]["schema"]
    flat = str(schema)
    for banned in ("minimum", "maximum", "minItems", "maxItems", "minLength",
                   "default", "title"):
        assert banned not in flat
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())
