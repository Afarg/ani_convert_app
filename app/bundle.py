"""Bundle orchestration (docs/design/04-output-format-and-agent-village-handoff.md).

Reads an img_to_pixcel_app character bundle (manifest.json + PNGs), runs
blink/walk generation per view, and writes an animation bundle + anim-manifest.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app import blink, eye_overrides, walk


@dataclass
class ViewResult:
    idle_frames: list[str]  # filenames, relative to the output dir
    walk_frames: list[str]


def needs_walk_frame(view_name: str, all_view_names: list[str]) -> bool:
    """front only needs a walk frame if it's the ONLY view in the bundle
    (docs/design/02-generation-pipeline.md §3 update history 2) - otherwise
    front is the static idle-only portrait and diagonal/back/side carry
    movement."""
    if view_name != "front":
        return True
    return all_view_names == ["front"]


def process_bundle(input_dir: Path, output_dir: Path) -> dict:
    """Runs blink + walk generation over every view in `input_dir`'s
    manifest.json, writes frames + anim-manifest.json into `output_dir`.
    Returns the anim-manifest dict."""
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    grid_size = manifest["gridSize"]
    output_size = manifest["outputSize"]
    view_names = list(manifest["views"].keys())

    output_dir.mkdir(parents=True, exist_ok=True)
    anim_views: dict[str, dict] = {}

    for view_name, view_info in manifest["views"].items():
        final_path = input_dir / view_info["final"]
        pre_path = input_dir / view_info["pre"]
        scale = view_info["scale"]

        final_image = Image.open(final_path).convert("RGBA")
        pre_image = Image.open(pre_path).convert("RGBA")

        final_image.save(output_dir / f"{view_name}.png")
        idle_frames = [f"{view_name}.png"]

        # A manually-painted override (scripts/paint_eye_positions.py) always
        # wins over the automatic heuristic when one exists for this
        # character+view - see eye_overrides.py for why it's exact (not just
        # approximate) regardless of this bundle's own grid_size/output_size.
        override = eye_overrides.load_override(manifest["characterId"], view_name)
        eye_boxes = (
            eye_overrides.eye_boxes_from_override(override, pre_image)
            if override is not None
            else blink.detect_eyes(pre_image)
        )
        blink_frame = blink.make_blink_frame(final_image, eye_boxes, scale, grid_size, output_size)
        if blink_frame is not None:
            blink_frame.save(output_dir / f"{view_name}_blink.png")
            idle_frames.append(f"{view_name}_blink.png")

        walk_frames = []
        if needs_walk_frame(view_name, view_names):
            frame_a, frame_b = walk.make_walk_frames(final_image, pre_image, scale, grid_size, output_size)
            if frame_a is not None and frame_b is not None:
                frame_a.save(output_dir / f"{view_name}_walk1.png")
                frame_b.save(output_dir / f"{view_name}_walk2.png")
                walk_frames = [f"{view_name}_walk1.png", f"{view_name}_walk2.png"]

        anim_views[view_name] = {"idle": idle_frames}
        if walk_frames:
            anim_views[view_name]["walk"] = walk_frames

    anim_manifest = {"characterId": manifest["characterId"], "views": anim_views}
    (output_dir / "anim-manifest.json").write_text(
        json.dumps(anim_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return anim_manifest
