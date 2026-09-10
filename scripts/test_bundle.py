"""Manual smoke test: process a character bundle end to end.

    .venv/Scripts/python.exe scripts/test_bundle.py test_bundle_phase1
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bundle import process_bundle

BUNDLE_NAME = sys.argv[1] if len(sys.argv) > 1 else "test_bundle_phase1"
INPUT_DIR = Path(__file__).parent / BUNDLE_NAME
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / f"{BUNDLE_NAME}-anim"


def main():
    if not INPUT_DIR.exists():
        print(f"missing {INPUT_DIR}")
        sys.exit(1)

    anim_manifest = process_bundle(INPUT_DIR, OUTPUT_DIR)
    print(f"wrote to {OUTPUT_DIR}")
    import json

    print(json.dumps(anim_manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
