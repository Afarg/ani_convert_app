"""Manual eye-position overrides (docs/design/02-generation-pipeline.md §4 -
2026-08-21 user-requested alternative to detect_eyes()'s automatic
saturation heuristic, for characters where that heuristic can't tell the eye
apart from hair/clothing no matter how it's tuned - see blink.py's
`detect_eyes()` "History of refinements" for how far that tuning was pushed).

A manual override is one (x, y) CENTER POINT per eye, painted onto a
bundle's FINAL pixel art by `scripts/paint_eye_positions.py`, then stored as
a FRACTION of that image's own canvas (0-1 across its full width/height) -
not a fixed pixel count, and not relative to the character's own bounding
box either.

Why a plain canvas fraction is exactly (not just approximately) portable to
any other grid_size/output_size render of the SAME character: the pipeline
maps canvas position linearly at every stage -
img_to_pixcel_app/app/pipeline.py's `convert()` computes
`scale = pre.width / grid_size`, and blink.py's `make_blink_frame()` computes
`upscale_ratio = output_size / grid_size` - so for the same physical point on
the character, `final_x / output_size == grid_x / grid_size == pre_x /
pre.width` regardless of which grid_size/output_size a given bundle was
rendered at. `pre.png` itself is also identical across every
grid_size/colors/output_size combination for a given source photo (it's
produced at pipeline.py stage 2, before any of those three parameters have
any effect - rembg's background removal is deterministic, so re-running it
doesn't change it either). Painting once therefore keeps applying
automatically if the representative bundle is later regenerated at a
different setting - no re-painting needed.

Only the two eyes' CENTER points are stored (not a painted region/size):
`make_blink_frame()` already derives its own fixed paint-patch size from
`output_size` alone, and `detect_eyes()`'s own returned box width/height only
ever fed a `+= w/2` center calculation downstream - box extent was never
actually load-bearing, so there was nothing to gain from also capturing it
here.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

OVERRIDES_DIR = Path(__file__).resolve().parent.parent / "data" / "eye_overrides"

# Synthetic eye-box size handed back in detect_eyes()'s (x, y, w, h) shape so
# eye_boxes_from_override() is a drop-in substitute wherever detect_eyes()'s
# return value is consumed. Only needs to be non-zero (see module docstring
# on why box extent isn't otherwise load-bearing).
_BOX_FRACTION = 0.03


def _override_path(character_id: str) -> Path:
    return OVERRIDES_DIR / f"{character_id}.json"


def load_override(character_id: str, view_name: str) -> dict | None:
    """Returns `{"left": {"x": .., "y": ..}, "right": {"x": .., "y": ..}}`
    (canvas fractions, 0-1) for this character+view, or None if nothing has
    been painted for it yet - callers should fall back to detect_eyes()."""
    path = _override_path(character_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    view = data.get(view_name)
    if not view or "left" not in view or "right" not in view:
        return None
    return view


def save_override(
    character_id: str,
    view_name: str,
    left: tuple[float, float],
    right: tuple[float, float],
) -> Path:
    """Records one eye pair (canvas-fraction x, y) for `view_name`, merging
    into any existing overrides already saved for this character's other
    views. Returns the file it wrote to."""
    path = _override_path(character_id)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[view_name] = {
        "left": {"x": left[0], "y": left[1]},
        "right": {"x": right[0], "y": right[1]},
    }
    OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def eye_boxes_from_override(override: dict, pre_image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Converts a loaded override's canvas fractions into detect_eyes()-
    shaped `[left_box, right_box]` (x, y, w, h) in `pre_image` pixel
    coordinates - the same space blink.make_blink_frame()'s `eye_boxes_pre`
    parameter expects."""
    w, h = pre_image.size
    box_w = max(2, round(w * _BOX_FRACTION))
    box_h = max(2, round(h * _BOX_FRACTION))

    def box(point: dict) -> tuple[int, int, int, int]:
        cx, cy = point["x"] * w, point["y"] * h
        return (int(round(cx - box_w / 2)), int(round(cy - box_h / 2)), box_w, box_h)

    return [box(override["left"]), box(override["right"])]
