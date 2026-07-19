from app.db.models import EntityObservation, EvidenceEntity, Frame
from app.pipeline.stages.s5_timeline import _entity_events


class FakeMedia:
    def __init__(self, id_, label):
        self.id = id_
        self.source_label_ar = label
        self.original_filename = label


class FakeOffset:
    def __init__(self, offset=0.0, method="auto_metadata"):
        self.offset_seconds = offset
        self.method = method


def _obs(entity_id, frame_id, media_id, ts, box):
    return EntityObservation(
        id=f"o-{frame_id}", entity_id=entity_id, detection_id=f"d-{frame_id}",
        frame_id=frame_id, media_file_id=media_id,
        timestamp_source_s=ts, timestamp_global_s=ts,
        bbox_x1=box[0], bbox_y1=box[1], bbox_x2=box[2], bbox_y2=box[3],
        confidence=0.9, state="present")


def test_first_seen_moved_last_seen():
    entity = EvidenceEntity(id="e1", run_id="r1", entity_seq=1,
                            canonical_name_ar="سكين", category="weapons")
    media_id = "m1"
    frames = {f"f{i}": Frame(id=f"f{i}", media_file_id=media_id, frame_index=i,
                             timestamp_s=float(i) * 2, stored_path="x")
              for i in range(5)}
    frame_pos = {media_id: {f"f{i}": i for i in range(5)}}
    obs = [
        _obs("e1", "f0", media_id, 0.0, (0.1, 0.4, 0.4, 0.5)),
        _obs("e1", "f1", media_id, 2.0, (0.1, 0.4, 0.4, 0.5)),
        _obs("e1", "f2", media_id, 4.0, (0.55, 0.6, 0.85, 0.7)),  # jumped
        _obs("e1", "f3", media_id, 6.0, (0.55, 0.6, 0.85, 0.7)),
        _obs("e1", "f4", media_id, 8.0, (0.55, 0.6, 0.85, 0.7)),
    ]
    events = _entity_events(
        entity, obs, frames, frame_pos, {media_id: FakeMedia(media_id, "كاميرا")},
        {media_id: FakeOffset()}, move_thr=0.15, label="«سكين» (دليل ٠٠١)")
    kinds = [e.event_type for e in events]
    assert kinds[0] == "first_seen"
    assert "moved" in kinds
    assert kinds[-1] == "last_seen"
    moved = next(e for e in events if e.event_type == "moved")
    assert moved.timestamp_source_s == 4.0
    assert "دليل ٠٠١" in moved.description_ar


def test_disappearance_needs_two_later_frames():
    entity = EvidenceEntity(id="e1", run_id="r1", entity_seq=1,
                            canonical_name_ar="هاتف", category="documents_devices")
    media_id = "m1"
    frames = {f"f{i}": Frame(id=f"f{i}", media_file_id=media_id, frame_index=i,
                             timestamp_s=float(i), stored_path="x")
              for i in range(4)}
    frame_pos = {media_id: {f"f{i}": i for i in range(4)}}
    obs = [_obs("e1", "f0", media_id, 0.0, (0.1, 0.1, 0.2, 0.2))]
    events = _entity_events(
        entity, obs, frames, frame_pos, {media_id: FakeMedia(media_id, "م")},
        {media_id: FakeOffset()}, move_thr=0.15, label="«هاتف» (دليل ٠٠١)")
    assert [e.event_type for e in events].count("disappeared") == 1


def test_still_image_only_first_seen():
    entity = EvidenceEntity(id="e1", run_id="r1", entity_seq=1,
                            canonical_name_ar="أثر", category="impressions")
    media_id = "m1"
    frames = {"f0": Frame(id="f0", media_file_id=media_id, frame_index=0,
                          timestamp_s=None, stored_path="x")}
    frame_pos = {media_id: {"f0": 0}}
    o = _obs("e1", "f0", media_id, None, (0.1, 0.1, 0.2, 0.2))
    o.timestamp_global_s = None
    events = _entity_events(
        entity, [o], frames, frame_pos, {media_id: FakeMedia(media_id, "صورة")},
        {media_id: FakeOffset(method="unanchored")}, move_thr=0.15,
        label="«أثر» (دليل ٠٠١)")
    assert [e.event_type for e in events] == ["first_seen"]
