"""Create local runtime configuration without replacing existing settings."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    target = ROOT / "config.json"
    if target.exists():
        print("Existing config.json preserved.")
        return
    data = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8-sig"))
    data["cache_root"] = str((ROOT / "cache").resolve())
    # Exclusive creation prevents replacing settings if two installers start together.
    with target.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("Created config.json; configure the API key in the app or use JUNFLOW_API_KEY.")

if __name__ == "__main__":
    main()
