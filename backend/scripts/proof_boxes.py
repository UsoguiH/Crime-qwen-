"""Final proof for the boxing refactor + photo Q&A, against the user's own image:
1) new photo analysis (detect → decoupled grounding) via the live API,
2) draws the STORED boxes onto the image server-side → proof_boxes.jpg,
3) asks two real questions and prints the grounded answers.
"""
import os
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

BASE = os.environ.get("ATHAR_API", "http://localhost:8000/api")
OUT = Path("/app/proof_boxes.jpg")

COLORS = {"weapons": "#c25e4c", "biological": "#a94464", "impressions": "#7b6fa8",
          "documents_devices": "#4e7fa5", "scene_markers": "#8a7b3c",
          "trace": "#5e8f6c", "human_presence": "#6b6b6b"}


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=180)
    inv = next(u for u in c.get("/auth/users").raise_for_status().json()
               if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]}).raise_for_status()

    case = next(x for x in c.get("/cases").raise_for_status().json()
                if x["case_number"] == "1212")
    media = next(m for m in c.get(f"/cases/{case['id']}/media")
                 .raise_for_status().json() if m["kind"] == "image")
    print(f"target: {media['original_filename']}")

    r = c.post(f"/media/{media['id']}/analyze", json={"thinking": True})
    if r.status_code == 409:
        print("analysis already running; waiting on it")
    else:
        r.raise_for_status()
        print("new analysis started (detect + grounding)")
    latest = None
    for _ in range(160):
        latest = c.get(f"/media/{media['id']}/analyses").raise_for_status().json()[0]
        if latest["status"] not in ("queued", "running"):
            break
        time.sleep(3)
    print(f"run status: {latest['status']}")
    dets = c.get(f"/runs/{latest['id']}/detections?media_id={media['id']}"
                 ).raise_for_status().json()
    print(f"detections: {len(dets)}")

    img_bytes = c.get(f"/files/original/{media['id']}").raise_for_status().content
    import io
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    scale = 900 / max(img.size)
    img = img.resize((round(img.width * scale), round(img.height * scale)))
    W, H = img.size
    d = ImageDraw.Draw(img)
    for i, det in enumerate(dets, 1):
        b = det["bbox"]
        color = COLORS.get(det["category"], "#26251e")
        d.rectangle((b[0]*W, b[1]*H, b[2]*W, b[3]*H), outline=color, width=3)
        d.text((b[0]*W + 3, max(0, b[1]*H - 14)), str(i), fill=color)
        print(f"  {i}. {det['name_ar'][:30]} bbox={[round(v,2) for v in b]}")
    img.save(OUT, "JPEG", quality=90)
    print(f"proof image → {OUT}")

    for q in ["كم عدد علامات الأدلة المرقمة الظاهرة في الصورة؟",
              "ما نوع السلاح الظاهر وأين يقع بالضبط؟"]:
        a = c.post(f"/media/{media['id']}/ask",
                   json={"question_ar": q, "thinking": True}).raise_for_status().json()
        print(f"\nQ: {q}")
        print(f"A: {a['answer_ar']}")
        print(f"   confidence={a['confidence']} cannot_determine={a['cannot_determine']} "
              f"boxes={len(a['grounded_boxes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
