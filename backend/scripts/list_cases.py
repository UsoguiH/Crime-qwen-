"""List every case in the live app with media + analysis counts."""
import os

import httpx

c = httpx.Client(base_url=os.environ.get("ATHAR_API", "http://localhost:8000/api"),
                 timeout=30)
inv = next(u for u in c.get("/auth/users").json() if u["role"] == "investigator")
c.post("/auth/login", json={"user_id": inv["id"]})
cases = c.get("/cases").json()
print(f"TOTAL CASES IN APP: {len(cases)}")
for x in sorted(cases, key=lambda z: z["case_number"]):
    n = x.get("media_count", 0)
    print(f"  {x['case_number']:16} | {x['title_ar'][:38]:38} | media={n} status={x['status']}")
