"""Load explicit local credentials; never inspect unrelated project directories."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY_NAMES = (
    "JUNFLOW_API_KEY", "COMFY_API_KEY", "COMFY_BASE_URL", "DASHSCOPE_API_KEY",
    "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "ARK_API_KEY",
)

def load_keys():
    path = ROOT / "secrets.json"
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    if not isinstance(data, dict):
        raise RuntimeError("secrets.json must contain a JSON object.")
    return {name: str(os.environ.get(name) or data.get(name) or "").strip() for name in KEY_NAMES}

def require(name):
    value = load_keys().get(name, "")
    if not value:
        raise RuntimeError("Missing " + name + ". Configure secrets.json or an environment variable.")
    return value
