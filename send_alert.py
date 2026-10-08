"""Quick tester.  python send_alert.py "message" [--no-call] [--url https://app.onrender.com]"""

import argparse
import json
import os
import urllib.request
from pathlib import Path

for line in Path(__file__).with_name(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

p = argparse.ArgumentParser()
p.add_argument("message", nargs="?")
p.add_argument("--no-call", action="store_true")
p.add_argument("--ring", type=int)
p.add_argument("--url", default="http://127.0.0.1:8000")
a = p.parse_args()

body = {"call": not a.no_call}
if a.message:
    body["message"] = a.message
if a.ring:
    body["ring_seconds"] = a.ring

req = urllib.request.Request(
    a.url.rstrip("/") + "/v1/alert",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json", "X-API-Key": os.environ["ALERT_API_KEY"]},
)
with urllib.request.urlopen(req, timeout=15) as r:
    print(r.status, r.read().decode())
