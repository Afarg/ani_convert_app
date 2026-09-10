"""FastAPI app (docs/design/01-architecture.md §2). Minimal preview UI:
upload a character bundle (img_to_pixcel_app's output folder), see the
generated blink/walk frames immediately.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.bundle import process_bundle

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "jobs"
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="PixelAnimator (仮称)")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/animate")
async def animate(files: list[UploadFile]):
    job_id = uuid.uuid4().hex[:12]
    input_dir = OUTPUT_DIR / job_id / "input"
    output_dir = OUTPUT_DIR / job_id / "output"
    input_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        # browsers send folder-relative paths in `filename` when the input used
        # webkitdirectory (e.g. "test_bundle_phase1/front.png") - keep only the
        # basename, the bundle is flat (docs/design/06-multi-angle-input.md §6)
        name = Path(f.filename).name
        (input_dir / name).write_bytes(await f.read())

    if not (input_dir / "manifest.json").exists():
        return JSONResponse(
            {"ok": False, "error": "manifest.json が見つかりません。バンドルのフォルダごと選択してください。"},
            status_code=400,
        )

    t0 = time.time()
    try:
        anim_manifest = process_bundle(input_dir, output_dir)
    except Exception as e:  # noqa: BLE001 - surface unexpected errors to the UI rather than a bare 500
        return JSONResponse({"ok": False, "error": f"生成中にエラーが発生しました: {e}"}, status_code=500)
    elapsed = time.time() - t0

    frames = {}
    for view_name, view_data in anim_manifest["views"].items():
        frames[view_name] = {
            "idle": [f"/output/{job_id}/output/{fn}" for fn in view_data["idle"]],
            "walk": [f"/output/{job_id}/output/{fn}" for fn in view_data.get("walk", [])],
        }

    return JSONResponse(
        {
            "ok": True,
            "jobId": job_id,
            "elapsedSeconds": round(elapsed, 2),
            "characterId": anim_manifest["characterId"],
            "views": frames,
            "manifestUrl": f"/output/{job_id}/output/anim-manifest.json",
        }
    )
