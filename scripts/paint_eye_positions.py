"""Interactive tool: manually mark each eye's center on a bundle's pixel
art. Saves the result via app/eye_overrides.py as a canvas-fraction
override that app/bundle.py's process_bundle() prefers over
blink.detect_eyes()'s automatic heuristic whenever one exists for a given
character+view - added 2026-08-21 for characters (test-character-a/c/d,
docs/project-status.md §7/§12) where that heuristic's saturation-based guess
keeps landing on hair rather than the eye no matter how its thresholds are
tuned.

    .venv/Scripts/python.exe scripts/paint_eye_positions.py test_char_a_wizard
    .venv/Scripts/python.exe scripts/paint_eye_positions.py test_char_a_wizard --view front

The first argument is a bundle directory (an img_to_pixcel_app output bundle
holding manifest.json + the view PNGs) - either a name relative to
scripts/, or a path to any bundle directory elsewhere.

Click the first eye, then the second (labeled "left"/"right" only as two
distinct keys - nothing downstream treats them asymmetrically). Each click
snaps to the nearest pixel-art grid cell so the saved position is exact
rather than sub-pixel-fuzzy. Keys:
  Enter - save, then generate + show a blink-frame preview
  R     - clear both points and re-click
  Q     - quit without saving
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import blink, eye_overrides  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent


def resolve_bundle_dir(raw: str) -> Path:
    direct = Path(raw)
    if (direct / "manifest.json").exists():
        return direct
    by_name = SCRIPTS_DIR / raw
    if (by_name / "manifest.json").exists():
        return by_name
    raise SystemExit(f"manifest.json not found under '{raw}' or '{by_name}'")


def snap_to_cell(px: float, cell_size: float) -> float:
    if cell_size < 1:
        return px
    idx = int(px // cell_size)
    return (idx + 0.5) * cell_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle", help="bundle directory (name under scripts/, or a path)")
    parser.add_argument("--view", default="front", help="view name within the bundle's manifest.json (default: front)")
    args = parser.parse_args()

    bundle_dir = resolve_bundle_dir(args.bundle)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    character_id = manifest["characterId"]
    grid_size = manifest["gridSize"]
    output_size = manifest["outputSize"]
    view_info = manifest["views"].get(args.view)
    if view_info is None:
        raise SystemExit(f"view '{args.view}' not in {bundle_dir}/manifest.json (has: {list(manifest['views'])})")

    final_image = Image.open(bundle_dir / view_info["final"]).convert("RGBA")
    cell_size = output_size / grid_size

    existing = eye_overrides.load_override(character_id, args.view)

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(final_image, interpolation="nearest")
    ax.set_title(f"{character_id} / {args.view}  -  1つ目(左目)をクリック")

    if cell_size >= 2:
        for gx in np.arange(0, output_size + 1, cell_size):
            ax.axvline(gx - 0.5, color="white", alpha=0.25, linewidth=0.5)
        for gy in np.arange(0, output_size + 1, cell_size):
            ax.axhline(gy - 0.5, color="white", alpha=0.25, linewidth=0.5)

    if existing:
        for key in ("left", "right"):
            pt = existing[key]
            ax.plot(pt["x"] * output_size, pt["y"] * output_size, marker="x", color="gray", markersize=10, alpha=0.6)

    points: list[tuple[float, float]] = []
    markers = []

    def redraw_markers():
        for m in markers:
            m.remove()
        markers.clear()
        for (px, py), color in zip(points, ("#00ff88", "#ff4488")):
            (dot,) = ax.plot(px, py, marker="o", color=color, markersize=8)
            markers.append(dot)
        fig.canvas.draw_idle()

    def on_click(event):
        if event.inaxes != ax or event.xdata is None or len(points) >= 2:
            return
        points.append((snap_to_cell(event.xdata, cell_size), snap_to_cell(event.ydata, cell_size)))
        redraw_markers()
        if len(points) == 1:
            ax.set_title(f"{character_id} / {args.view}  -  2つ目(右目)をクリック")
        else:
            ax.set_title(f"{character_id} / {args.view}  -  Enter:保存  R:やり直し  Q:キャンセル")
        fig.canvas.draw_idle()

    result = {"saved": False}

    def on_key(event):
        if event.key == "r":
            points.clear()
            redraw_markers()
            ax.set_title(f"{character_id} / {args.view}  -  1つ目(左目)をクリック")
            fig.canvas.draw_idle()
        elif event.key == "enter" and len(points) == 2:
            result["saved"] = True
            plt.close(fig)
        elif event.key in ("q", "escape"):
            plt.close(fig)

    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("key_press_event", on_key)
    plt.show()

    if not result["saved"]:
        print("キャンセルしました。保存していません。")
        return

    left_frac = (points[0][0] / output_size, points[0][1] / output_size)
    right_frac = (points[1][0] / output_size, points[1][1] / output_size)
    saved_path = eye_overrides.save_override(character_id, args.view, left_frac, right_frac)
    print(f"保存しました: {saved_path}")
    print(f"  left:  x={left_frac[0]:.4f} y={left_frac[1]:.4f}")
    print(f"  right: x={right_frac[0]:.4f} y={right_frac[1]:.4f}")

    pre_image = Image.open(bundle_dir / view_info["pre"]).convert("RGBA")
    override = eye_overrides.load_override(character_id, args.view)
    eye_boxes = eye_overrides.eye_boxes_from_override(override, pre_image)
    blink_frame = blink.make_blink_frame(final_image, eye_boxes, view_info["scale"], grid_size, output_size)

    if blink_frame is None:
        print("警告: 保存した位置がキャラクターの不透明領域に重なっておらず、まばたきフレームを生成できませんでした。")
        return

    preview_path = bundle_dir / f"{args.view}_blink_preview.png"
    blink_frame.save(preview_path)
    print(f"プレビューを保存しました: {preview_path}")

    fig2, axes = plt.subplots(1, 2, figsize=(10, 5))
    axes[0].imshow(final_image, interpolation="nearest")
    axes[0].set_title("通常")
    axes[0].axis("off")
    axes[1].imshow(blink_frame, interpolation="nearest")
    axes[1].set_title("まばたき (プレビュー)")
    axes[1].axis("off")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
