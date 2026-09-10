"""Walk-cycle frame generation (docs/design/02-generation-pipeline.md §3).

Generates two contralateral walk frames - "right leg up + left hand up" and
"left leg up + right hand up" - by cutting the waist-down leg region (split
left/right at the character's own midline) and the detected hand regions out
of the standing pose and pasting each shifted a few pixels up, leaving the
vacated pixels transparent. This only ever rearranges/removes existing
pixels within the same view; it never invents new geometry, consistent with
the "first-gen sprite-swap" approach referenced in
docs/design/01-visual-concept.md §3.2.

Hand detection follows the same pattern as app/blink.py's detect_eyes():
run on `pre.png` (the high-resolution, pre-pixelation image) rather than the
tiny final grid, then convert the detected box to final-image coordinates via
`scale`/`output_size`/`grid_size` (docs/design/06-multi-angle-input.md §6).
Detection looks for a color that stands out from the locally-dominant color
near each side's outer edge (a minority-color blob, e.g. skin against a
sleeve) rather than assuming a fixed skin tone, so it degrades gracefully for
gloves/long sleeves/non-human designs - see detect_hands() docstring.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.blink import OUTLINE_COLOR


def detect_hands(
    pre_image: Image.Image,
    band: tuple[float, float] = (0.55, 0.85),
    edge_fraction: float = 0.4,
    min_area: int = 6,
    max_area: int = 4000,
    outline_color: tuple[int, int, int] = OUTLINE_COLOR[:3],
) -> dict[str, tuple[int, int, int, int] | None]:
    """Returns up to one hand box per side (`{"left": ..., "right": ...}`,
    each `(x, y, w, h)` in `pre_image` pixel coordinates, or None if that
    side has no plausible hand).

    Searches a horizontal band (`band`, as a fraction of the character's own
    bbox height - hands hang roughly hip-height on a standing character with
    arms down, docs/design/04-constraints-and-limitations.md's "arms down"
    input requirement) restricted to a narrow strip at each side's outer
    edge (`edge_fraction` of the half-width). Restricting to the edge strip
    - rather than the whole band - avoids confusing the torso/leg colors
    with each other when computing "the locally dominant color", since a
    sleeve's hand is a small minority blob only where the arm actually is.

    Within each strip, pixels whose color differs meaningfully from that
    strip's own dominant color (and isn't the outline color) are candidate
    hand pixels; connected candidate pixels are grouped, filtered by area,
    and the candidate closest to the bottom of the band is picked (hands
    hang below the sleeve, closest to the waist). Returns None for a side
    with no qualifying candidate - callers must treat that as "skip this
    hand" rather than guessing (same fail-soft philosophy as
    app/blink.py's detect_eyes()).
    """
    arr = np.array(pre_image.convert("RGBA"))
    alpha = arr[:, :, 3]
    opaque = alpha > 0
    ys, xs = np.where(opaque)
    if len(ys) == 0:
        return {"left": None, "right": None}

    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    half_width = (x1 - x0) / 2
    edge_w = max(1, int(half_width * edge_fraction))

    band_y0 = y0 + int((y1 - y0) * band[0])
    band_y1 = y0 + int((y1 - y0) * band[1])
    if band_y0 >= band_y1:
        return {"left": None, "right": None}

    rgb = arr[:, :, :3].astype(np.int16)
    outline_arr = np.array(outline_color, dtype=np.int16)

    def find_in_strip(strip_x0: int, strip_x1: int) -> tuple[int, int, int, int] | None:
        strip_mask = np.zeros_like(opaque)
        strip_mask[band_y0 : band_y1 + 1, strip_x0 : strip_x1 + 1] = opaque[
            band_y0 : band_y1 + 1, strip_x0 : strip_x1 + 1
        ]
        if not strip_mask.any():
            return None

        strip_pixels = rgb[strip_mask]
        quantized = (strip_pixels // 8) * 8
        colors, counts = np.unique(quantized, axis=0, return_counts=True)
        dominant = colors[np.argmax(counts)]

        dist_from_dominant = np.abs(rgb - dominant).sum(axis=2)
        dist_from_outline = np.abs(rgb - outline_arr).sum(axis=2)
        distinct_mask = (strip_mask & (dist_from_dominant > 60) & (dist_from_outline > 24)).astype(np.uint8)
        if not distinct_mask.any():
            return None

        num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(distinct_mask, connectivity=4)
        candidates = []
        for i in range(1, num_labels):
            x, y, w, h, area = stats[i]
            if area < min_area or area > max_area:
                continue
            candidates.append((int(x), int(y), int(w), int(h), int(y + h)))
        if not candidates:
            return None

        # closest to the bottom of the band wins - a hand hangs below the
        # sleeve, so the lowest distinct-color blob is the more plausible one
        candidates.sort(key=lambda c: -c[4])
        x, y, w, h, _bottom = candidates[0]
        return (x, y, w, h)

    return {
        "left": find_in_strip(x0, x0 + edge_w),
        "right": find_in_strip(x1 - edge_w, x1),
    }


def _shift_masked_pixels_up(out: np.ndarray, mask: np.ndarray, shift: int) -> None:
    """Moves the pixels selected by `mask` up by `shift` rows, in place.

    The source footprint is cleared to transparent first (the "cut"), then
    the moved pixels are pasted at their new position - but only where the
    moved pixel is itself opaque, so shifting doesn't punch a transparent
    hole into whatever's already sitting just above the region (e.g. the
    torso hem right above the leg region, or the sleeve right above a
    hand)."""
    if shift <= 0 or not mask.any():
        return
    ys, xs = np.where(mask)
    src_pixels = out[ys, xs, :].copy()
    out[ys, xs, :] = 0

    dest_ys = ys - shift
    valid = dest_ys >= 0
    dest_ys, dest_xs, src_pixels = dest_ys[valid], xs[valid], src_pixels[valid]

    opaque_px = src_pixels[:, 3] > 0
    dest_ys, dest_xs, src_pixels = dest_ys[opaque_px], dest_xs[opaque_px], src_pixels[opaque_px]

    out[dest_ys, dest_xs, :] = src_pixels


def make_walk_frames(
    final_image: Image.Image,
    pre_image: Image.Image,
    scale: float,
    grid_size: int,
    output_size: int,
    leg_fraction: float = 0.35,
    shift_fraction: float = 0.65,
    shift_px: int | None = None,
) -> tuple[Image.Image | None, Image.Image | None]:
    """Returns two walk frames, `(right_leg_and_left_hand_up, left_leg_and_right_hand_up)`,
    or `(None, None)` if the character is too small/flat for a meaningful leg
    region to exist (fail soft rather than produce a nonsensical result,
    docs/design/05-constraints-and-limitations.md §2).

    `leg_fraction` of the character's own bbox height (from the bottom) is
    treated as "waist-down"; the leg region is split left/right at the
    character's horizontal midline. Hands are detected via `detect_hands()`
    on `pre_image` and converted to final-image coordinates via `scale` and
    `output_size/grid_size` - the same coordinate transform app/blink.py's
    make_blink_frame() uses for eyes. Any hand pixels are excluded from the
    leg region so a pixel is never shifted twice.

    Only the bottom `shift_fraction` of the "waist-down" region actually
    moves - not the whole `leg_fraction` span. Found necessary empirically: a
    long-coat character's jacket hem extends past the `leg_fraction` cutoff,
    so shifting the entire waist-down region as one rigid block dragged
    jacket-hem pixels up along with the leg, notching the jacket's bottom
    silhouette (looked like the torso itself had collapsed). Leaving the
    upper part of the waist-down region (closer to the torso, more likely to
    still be clothing rather than bare leg) anchored in place avoids that,
    while the lower portion that does move still reads as a visible foot
    lift.

    `shift_px` defaults to `round(output_size / 16)`, scaled to the *final*
    canvas rather than the grid - this lands on exactly 4px at the 64px
    output size that's both the UI default (img_to_pixcel_app/static/index.html)
    and every real sample this was tuned against, matching the ~3-4px
    step/arm-swing the shift was specified against, while still shrinking
    proportionally for smaller output sizes so it doesn't overshoot a tiny
    16px sprite's whole leg region.
    """
    arr = np.array(final_image.convert("RGBA"))
    h, w = arr.shape[:2]
    alpha = arr[:, :, 3]
    opaque = alpha > 0
    ys, xs = np.where(opaque)
    if len(ys) == 0:
        return None, None

    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    leg_y0 = int(y1 - (y1 - y0) * leg_fraction)
    if leg_y0 >= y1 or x0 >= x1:
        return None, None
    shift_y0 = int(y1 - (y1 - leg_y0) * shift_fraction)

    if shift_px is None:
        shift_px = max(1, round(output_size / 16))

    center_x = (x0 + x1) / 2
    leg_mid = int(round(center_x))
    upscale_ratio = output_size / grid_size

    def hand_mask_in_final_space(box_pre: tuple[int, int, int, int] | None) -> np.ndarray | None:
        if box_pre is None:
            return None
        px, py, pw, ph = box_pre
        gx0, gy0 = px / scale, py / scale
        gx1, gy1 = (px + pw) / scale, (py + ph) / scale
        fx0 = max(0, int(round(gx0 * upscale_ratio)) - 1)
        fy0 = max(0, int(round(gy0 * upscale_ratio)) - 1)
        fx1 = min(w, int(round(gx1 * upscale_ratio)) + 1)
        fy1 = min(h, int(round(gy1 * upscale_ratio)) + 1)
        if fx0 >= fx1 or fy0 >= fy1:
            return None
        mask = np.zeros((h, w), dtype=bool)
        mask[fy0:fy1, fx0:fx1] = opaque[fy0:fy1, fx0:fx1]
        return mask if mask.any() else None

    hands_pre = detect_hands(pre_image)
    left_hand_mask = hand_mask_in_final_space(hands_pre["left"])
    right_hand_mask = hand_mask_in_final_space(hands_pre["right"])

    leg_band = np.zeros((h, w), dtype=bool)
    leg_band[shift_y0 : y1 + 1, x0 : x1 + 1] = opaque[shift_y0 : y1 + 1, x0 : x1 + 1]
    for hand_mask in (left_hand_mask, right_hand_mask):
        if hand_mask is not None:
            leg_band &= ~hand_mask

    left_leg_mask = leg_band.copy()
    left_leg_mask[:, leg_mid:] = False
    right_leg_mask = leg_band.copy()
    right_leg_mask[:, :leg_mid] = False

    if not left_leg_mask.any() and not right_leg_mask.any():
        return None, None

    def build_frame(leg_mask: np.ndarray, hand_mask: np.ndarray | None) -> Image.Image:
        out = arr.copy()
        _shift_masked_pixels_up(out, leg_mask, shift_px)
        if hand_mask is not None:
            _shift_masked_pixels_up(out, hand_mask, shift_px)
        return Image.fromarray(out, mode="RGBA")

    frame_right_leg_left_hand = build_frame(right_leg_mask, left_hand_mask)
    frame_left_leg_right_hand = build_frame(left_leg_mask, right_hand_mask)
    return frame_right_leg_left_hand, frame_left_leg_right_hand
