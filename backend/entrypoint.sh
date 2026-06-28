#!/bin/sh
set -e

echo "[novflow] waiting for database..."
python - <<'PY'
import os
import sys
import time

from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if not url:
    print("DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

for i in range(30):
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[novflow] database is ready")
        sys.exit(0)
    except Exception as exc:
        print(f"[novflow] db wait {i + 1}/30: {exc}")
        time.sleep(2)

print("[novflow] database not ready after 60s", file=sys.stderr)
sys.exit(1)
PY

echo "[novflow] starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
