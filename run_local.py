"""Local runner: loads .env then starts the server.   python run_local.py"""

import os
from pathlib import Path

import uvicorn

for line in Path(__file__).with_name(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

uvicorn.run("asgi:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
