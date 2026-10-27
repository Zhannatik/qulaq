"""Print the model ids your API key can use (so you can set LLM_MODEL in .env).

    python scripts/list_models.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from qulaq.config import get_settings  # noqa: E402

s = get_settings()
if not s.api_key:
    raise SystemExit("MODEL_API_KEY is not set in .env")
r = httpx.get(s.api_base + "/models", headers={"Authorization": f"Bearer {s.api_key}"}, timeout=30)
print(f"HTTP {r.status_code}")
try:
    data = r.json()
    items = data.get("data", data) if isinstance(data, dict) else data
    for m in items:
        print(m.get("id", m) if isinstance(m, dict) else m)
except ValueError:
    print(r.text[:1500])
