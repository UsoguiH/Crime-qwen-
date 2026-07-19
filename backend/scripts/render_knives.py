"""Render GT (green) vs AI (red) weapon boxes for the knife images already
analyzed in REAL-WEAPONS-01, to diagnose knife localization."""
import io
import json
import os
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

BASE = os.environ.get("ATHAR_API", "http://localhost:8000/api")
GT = Path("/app/eval/realdata/weapons_gt.json")
OUT = Path("/app/eval/realdata/proof")


def main():
    gt = json.loads(GT.read_text(encoding="utf-8"))
    knives = [x for x in gt["images"] if any(g["cls"] == "knife" for g in x["gt"])][:4]
    c = httpx.Client(base_url=BASE, timeout=120)
    inv = next(u for u in c.get("/auth/users").json() if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]})
    case = next(x for x in c.get("/cases").json() if x["case_number"] == "REAL-WEAPONS-01")
    media = {m["original_filename"]: m for m in c.get(f"/cases/{case['id']}/media").json()}
    for i, im in enumerate(knives):
        m = media.get(im["file"])
        if not m:
            continue
        a = c.get(f"/media/{m['id']}/analyses").json()
        if not a:
            continue
        dets = c.get(f"/runs/{a[0]['id']}/detections?media_id={m['id']}").json()
        weap = [d for d in dets if d["category"] == "weapons"]
        img = Image.open(io.BytesIO(c.get(f"/files/original/{m['id']}").content)).convert("RGB")
        sc = 700/max(img.size); img = img.resize((round(img.width*sc), round(img.height*sc)))
        W, H = img.size; d = ImageDraw.Draw(img)
        for g in im["gt"]:
            b = [v/1000 for v in g["rel1000"]]
            d.rectangle((b[0]*W, b[1]*H, b[2]*W, b[3]*H), outline="#1f8a65", width=4)
        for det in weap:
            b = det["bbox"]
            d.rectangle((b[0]*W, b[1]*H, b[2]*W, b[3]*H), outline="#cf2d56", width=2)
        img.save(OUT / f"knife_{i}.jpg", "JPEG", quality=88)
        print(f"knife_{i}: {im['file']} weapon-dets={len(weap)} gt={len(im['gt'])}")
    print("rendered → /app/eval/realdata/proof/knife_*.jpg")


if __name__ == "__main__":
    main()
