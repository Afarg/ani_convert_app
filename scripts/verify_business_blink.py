"""Pixel-level verification of blink frames for the 4 business characters
(docs/project-status.md §12's lesson: verify actual painted position/color
numerically, not just by eye - "見た目は変わったが実は違う場所/色だった" happened before).

For each character:
  1. Diff front.png vs front_blink.png -> find painted regions (should be 2,
     left+right eye, not 0 or 1).
  2. Report each region's center (so it can be cross-checked against the
     character's actual eye position visually).
  3. Compare the fill color actually used against a HAIR reference color
     (sampled near the top of the head) and a SKIN reference color (sampled
     from the middle of the face, away from eyes/hair) - flags "hair-ish"
     fills, the exact failure mode seen on characters B/C in §12.2.
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

CHARACTERS = ["business_character_a", "business_character_b", "business_character_c", "business_character_d"]
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "output"


def bbox_regions(diff_mask: np.ndarray, gap: int = 3):
    """Groups True pixels in diff_mask into contiguous x-ranges (simple 1D
    clustering along x, sufficient since left/right eye regions are always
    well-separated horizontally for a front-facing character)."""
    ys, xs = np.where(diff_mask)
    if len(xs) == 0:
        return []
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    regions = []
    start = 0
    for i in range(1, len(xs) + 1):
        if i == len(xs) or xs[i] - xs[i - 1] > gap:
            seg_x, seg_y = xs[start:i], ys[start:i]
            regions.append(
                {
                    "x_range": (int(seg_x.min()), int(seg_x.max())),
                    "y_range": (int(seg_y.min()), int(seg_y.max())),
                    "center": (float(seg_x.mean()), float(seg_y.mean())),
                    "pixel_count": int(len(seg_x)),
                }
            )
            start = i
    return regions


def color_dist(a, b) -> float:
    return float(np.linalg.norm(np.array(a, dtype=np.float64) - np.array(b, dtype=np.float64)))


def main() -> None:
    results = []
    for char_dir_name in CHARACTERS:
        anim_dir = OUTPUT_ROOT / f"{char_dir_name}-anim"
        front = np.array(Image.open(anim_dir / "front.png").convert("RGBA"))
        blink = np.array(Image.open(anim_dir / "front_blink.png").convert("RGBA"))

        diff_mask = np.any(front[:, :, :3] != blink[:, :, :3], axis=2) & (front[:, :, 3] > 0)
        regions = bbox_regions(diff_mask)

        fill_color = None
        if diff_mask.any():
            ys, xs = np.where(diff_mask)
            fill_color = tuple(int(v) for v in blink[ys[0], xs[0], :3])

        alpha = front[:, :, 3] > 0
        ys_all, xs_all = np.where(alpha)
        y0, y1 = ys_all.min(), ys_all.max()
        x0, x1 = xs_all.min(), xs_all.max()
        bbox_h = y1 - y0

        # hair reference: opaque pixel nearest the top edge, at the horizontal center
        cx = (x0 + x1) // 2
        hair_y = None
        for y in range(y0, y0 + max(1, bbox_h // 10)):
            if alpha[y, cx]:
                hair_y = y
                break
        hair_color = tuple(int(v) for v in front[hair_y, cx, :3]) if hair_y is not None else None

        # skin reference: opaque pixel at roughly nose height (55% down bbox), scanning
        # outward from center for the first opaque pixel not part of a painted region
        nose_y = y0 + int(bbox_h * 0.55)
        skin_color = None
        for dx in range(0, (x1 - x0) // 2):
            for cand_x in (cx - dx, cx + dx):
                if alpha[nose_y, cand_x] and not diff_mask[nose_y, cand_x]:
                    skin_color = tuple(int(v) for v in front[nose_y, cand_x, :3])
                    break
            if skin_color is not None:
                break

        entry = {
            "character": char_dir_name,
            "num_painted_regions": len(regions),
            "regions": regions,
            "fill_color": fill_color,
            "hair_reference_color": hair_color,
            "skin_reference_color": skin_color,
            "dist_fill_to_hair": color_dist(fill_color, hair_color) if fill_color and hair_color else None,
            "dist_fill_to_skin": color_dist(fill_color, skin_color) if fill_color and skin_color else None,
        }
        entry["looks_like_skin_not_hair"] = (
            entry["dist_fill_to_skin"] is not None
            and entry["dist_fill_to_hair"] is not None
            and entry["dist_fill_to_skin"] < entry["dist_fill_to_hair"]
        )
        results.append(entry)

    print(json.dumps(results, indent=2, ensure_ascii=False))

    print("\n--- summary ---")
    for r in results:
        status = "OK" if r["num_painted_regions"] == 2 and r["looks_like_skin_not_hair"] else "CHECK"
        print(
            f"{r['character']}: regions={r['num_painted_regions']} "
            f"fill={r['fill_color']} skin_ref={r['skin_reference_color']} hair_ref={r['hair_reference_color']} "
            f"dist(fill,skin)={r['dist_fill_to_skin']:.1f} dist(fill,hair)={r['dist_fill_to_hair']:.1f} "
            f"-> {status}"
        )


if __name__ == "__main__":
    main()
