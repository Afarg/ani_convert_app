"""Blink frame generation (docs/design/02-generation-pipeline.md §2).

Eye detection method: heuristic saturation-based blob detection within the
head region (cv2.connectedComponentsWithStats, no external model file
needed), then refined onto the eye's own color to pinpoint its true center
(see detect_eyes()'s "History of refinements" for how each step was found).

Design note (deviation from the original doc): the doc's primary plan was a
Haar cascade (`haarcascade_eye.xml`) with this heuristic as a fallback. In
practice, the installed OpenCV build (5.0.0) does not bundle any haarcascades
data files, and downloading the file from opencv's GitHub repo was blocked by
the harness's tool-permission layer. Rather than block on that, the
heuristic-only approach was promoted to primary. Haar cascade support can be
added later as an optional improvement if the XML file becomes available
(manual download, or a future opencv-python build that bundles it) - see
05-constraints-and-limitations.md.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

OUTLINE_COLOR = (0x1A, 0x1C, 0x2C, 0xFF)


def _refine_eye_center(
    rgb: np.ndarray,
    opaque: np.ndarray,
    guess_x: float,
    guess_y: float,
    ref_color: np.ndarray,
    radius_x: float,
    radius_y: float,
    color_tolerance: int = 90,
    dark_fraction: float = 0.35,
) -> tuple[float, float]:
    """Refines an approximate eye center to the eye's actual dark core (the
    pupil/iris): within a window around `(guess_x, guess_y)`, finds opaque
    pixels close to `ref_color` (the eye's own color, established from a
    reliably-detected eye), then returns the centroid of the darkest
    `dark_fraction` of those matches. Centering on color match narrows the
    search to "this is actually an eye, not skin/hair/clothing that happens
    to be nearby"; centering on the darkest subset of that match then avoids
    drifting toward a bright highlight/shine or the eye's soft edge, landing
    on the pupil instead. Falls back to `(guess_x, guess_y)` unchanged if no
    pixels match within the window - fail soft rather than move to a worse
    guess.
    """
    h, w = opaque.shape
    x0, x1 = max(0, int(guess_x - radius_x)), min(w, int(guess_x + radius_x) + 1)
    y0, y1 = max(0, int(guess_y - radius_y)), min(h, int(guess_y + radius_y) + 1)
    if x0 >= x1 or y0 >= y1:
        return (guess_x, guess_y)

    window_opaque = opaque[y0:y1, x0:x1]
    window_rgb = rgb[y0:y1, x0:x1].astype(np.int32)
    color_dist = np.abs(window_rgb - ref_color).sum(axis=2)
    match = window_opaque & (color_dist <= color_tolerance)
    ys, xs = np.where(match)
    if len(ys) == 0:
        return (guess_x, guess_y)

    luminance = window_rgb[ys, xs].sum(axis=1)
    cutoff = np.percentile(luminance, dark_fraction * 100)
    dark = luminance <= cutoff
    if not dark.any():
        dark = np.ones(len(ys), dtype=bool)
    return (float(xs[dark].mean() + x0), float(ys[dark].mean() + y0))


def detect_eyes(
    pre_image: Image.Image,
    face_band: tuple[float, float] = (0.38, 0.72),
    min_area: int = 4,
    max_area: int | None = None,
) -> list[tuple[int, int, int, int]]:
    """Returns up to 2 eye boxes (x, y, w, h) in `pre_image` pixel coordinates.

    Looks for small, highly-saturated, roughly eye-shaped blobs within a
    horizontal band of the character's own bounding box (`face_band`, as a
    fraction of bbox WIDTH, measured down from the bbox's own top edge - not
    the whole canvas, there's transparent padding around the character, and
    not bbox HEIGHT, see refinement 5 below for why). Returns [] if nothing
    plausible is found; callers must treat that as "skip blink for this
    view" rather than guessing (docs/design/05-constraints-and-limitations.md
    §1).

    History of refinements (each found by testing against a real character,
    see docs/design/05-constraints-and-limitations.md §1 for the write-up):

    1. First tried "darkest blob in the upper 35%". Failed: this character's
       eyes are bright red, so the darkest head-region pixels were hair/hat
       shading, not the eyes - detected boxes landed on the hat.
    2. Switched to SATURATION instead of darkness (skin is usually
       desaturated; a vivid anime eye color usually isn't). Better - found
       one real eye - but the other "winning" candidate was a saturated hair
       highlight streak, because it happened to have a larger pixel area.
    3. Added two more filters: an aspect-ratio check (the hair streak was
       tall and thin, ~2.6x taller than wide; real eyes are wider-than-tall
       or roughly square) and restricting the search to a face-height BAND
       (`face_band`, originally 25%-65% down the bbox, as a fraction of bbox
       HEIGHT) instead of "the whole upper 60%", which was including the
       hairline/hat area where saturated hair streaks live.
    4. The mirror-fallback position for the second eye (see below) was found
       to land visibly off the real eye on an asymmetric character (bat
       wings extending further on one side skewed the whole-bbox horizontal
       center away from the true facial midline by ~20px). Manual pixel
       inspection also showed the real second eye's saturated region had
       fragmented into dozens of 1-9px connected-component pieces during
       labeling (anti-aliasing/shading breaking up what should be one
       blob), so no candidate in `boxes` was ever close enough to the
       mirrored guess to match against, either. Added `_refine_eye_center()`:
       color-matches against the primary eye's own color within a window
       around whatever initial guess we have (matched candidate or mirror),
       then centers on the darkest matches - this finds the real eye
       regardless of how fragmented its region is, since it doesn't require
       one clean connected blob. Also used to refine the primary eye's own
       center (within its own box) rather than trusting that raw bounding
       box's geometric center, which can itself drift toward a highlight.
    5. `face_band` was originally a fraction of bbox HEIGHT (25%-65% down).
       Testing against 4 new characters spanning different proportions
       (docs/project-status.md §10, 2026-08-15) found this put the eyes
       outside the band entirely on 3 of the 4: a taller, less chibi
       character (bbox height dominated by a long coat) landed the band on
       the coat's buttons; a character with waist-length hair (bbox height
       stretched by hair well below the face) landed the band on a hip
       ribbon; an extremely squashed super-deformed character (head is
       almost the whole body) landed the band on the ears. In every case the
       real eyes were much closer to the bbox's own TOP edge than a
       height-fraction assumes, because hair length and overall body
       proportion change bbox height substantially without moving the face
       away from the top. Measured precisely (pixel-grid overlays, not just
       the detector's own output) across all 5 characters, eye position from
       the top edge divided by bbox WIDTH landed in a 0.40-0.66 range despite
       bbox height varying by nearly 2x - bbox width (roughly the head's own
       diameter for a front-facing bust) tracks the face position far more
       reliably than bbox height does. `face_band` is now interpreted as a
       fraction of bbox width instead (0.38-0.72, a little wider than the
       measured range so per-character variation doesn't cause a miss).
    6. Even with the band fixed, `primary = boxes[0]` (just the single
       largest saturated blob in-band) still preferred a lone, off-center
       saturated feature over the real eyes on 2 of 4 new characters: a coat
       button (centered on the midline, not paired) and a hip ribbon (a
       single bow, not paired). Both are exactly the kind of thing pure area
       can't distinguish from an eye, but a real eye pair has a property
       neither does: two similarly-sized blobs straddling the character's
       own horizontal center at roughly the same height. Now looks for the
       best such mirrored pair FIRST, among all candidates (not just as a
       fallback search for a second eye once one is already picked, which
       was the old order and is why a single strong false positive could win
       outright). Falls back to the old single-largest-blob behavior when no
       plausible pair exists (e.g. a genuine single-eye view).
    7. The pair search itself went through several bad iterations before
       landing on the current rule, each caught by testing all 5 characters
       together rather than stopping at the first one that improved:
       - Scoring pairs mainly by how closely their sizes/positions matched
         backfired on a character whose hair-shading highlight produced 3
         near-identical, near-mirrored blobs along the fringe - those
         matched each other better than the real eyes did (one eye's blob
         had partly merged with an eyebrow shadow, a natural ~30% size
         difference from the other eye).
       - Switching to "prefer the biggest qualifying pair" (dropping size-
         match from the score) fixed that, but then a pair tolerance that
         scaled off each CANDIDATE blob's own size let one abnormally tall
         false-positive blob (a hair-shadow streak) buy itself extra slack
         and out-rank the real, tightly eye-height-matched eyes. Tolerances
         are now fixed fractions of bbox WIDTH instead (x: 0.20, y: 0.06 -
         eyes sit at nearly the same height, so y needs to be tight; x, the
         mirror match, can be a little looser since AI-generated art is
         rarely pixel-symmetric).
       - An edge-distance filter (candidates within 10% of bbox width from
         the left/right silhouette edge are ear territory, not eye
         territory) was needed for a super-deformed character whose ears
         mirrored each other at a plausible eye height, but 10% wasn't
         enough for a different character with a narrower head shape whose
         ears sat further in; widened to 20%.
       Even after all of the above, the super-deformed character's own eyes
       are pale/low-saturation enough that they may not clear the top-15th-
       percentile saturation threshold in the first place - a different,
       already-documented limitation (`05-constraints-and-limitations.md`
       §1), not this band/pairing issue. `detect_eyes()` still returns its
       best guess rather than [] in that case (matching pre-existing
       behavior for "some candidate exists, just not a great one") - a
       stricter "give up if no candidate looks confident" mode is a
       possible future improvement, not implemented here.
    """
    arr = np.array(pre_image.convert("RGBA"))
    alpha = arr[:, :, 3]
    opaque = alpha > 0
    ys, xs = np.where(opaque)
    if len(ys) == 0:
        return []

    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    bbox_width = x1 - x0
    band_y0 = y0 + int(bbox_width * face_band[0])
    band_y1 = min(y1, y0 + int(bbox_width * face_band[1]))

    # 8. `max_area` was a fixed 600px, calibrated against the reference
    # character. On a different character (docs/project-status.md §11,
    # 2026-08-15) the real eye's saturated region measured 1300+ px - it had
    # fused with the eyebrow/eyelashes into one connected blob - so it was
    # silently rejected as "too big to be an eye" and a much smaller,
    # coincidental blob (an ear, a hair highlight) won instead, landing the
    # blink noticeably off the real eyes. Like `face_band`, this scales with
    # bbox WIDTH SQUARED (an area should scale with the square of a linear
    # head-size measure) rather than being a fixed pixel count.
    if max_area is None:
        max_area = int(bbox_width**2 * 0.015)

    face_mask = np.zeros_like(opaque)
    face_mask[band_y0 : band_y1 + 1, :] = opaque[band_y0 : band_y1 + 1, :]
    if not face_mask.any():
        return []

    hsv = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1].astype(np.float64)

    face_sat_values = saturation[face_mask]
    sat_threshold = np.percentile(face_sat_values, 85)
    sat_mask = (face_mask & (saturation >= sat_threshold)).astype(np.uint8)

    num_labels, labels, stats, _centroids = cv2.connectedComponentsWithStats(sat_mask, connectivity=4)

    boxes = []
    for i in range(1, num_labels):  # label 0 is background
        x, y, w, h, area = stats[i]
        if area < min_area or area > max_area:
            continue
        aspect = h / w if w else float("inf")
        if not (0.4 <= aspect <= 2.5):
            continue  # too elongated to be an eye (a saturated hair strand etc.)
        boxes.append((int(x), int(y), int(w), int(h), int(area), i))

    if not boxes:
        return []

    boxes.sort(key=lambda b: -b[4])

    # Refinements 6-7 above: look for the best mirrored PAIR first (falling
    # back to the single-largest-blob behavior below when none qualifies),
    # among candidates that are big enough to plausibly be an eye (not a tiny
    # noise speck) and not hugging the silhouette's own left/right edge (ear
    # territory).
    center_x = (x0 + x1) / 2
    edge_margin = bbox_width * 0.20
    pairing_candidates = [
        b for b in boxes if b[4] >= boxes[0][4] * 0.15 and edge_margin <= (b[0] + b[2] / 2) - x0 <= bbox_width - edge_margin
    ]
    # Qualifying pairs (within position tolerance) are ranked by size
    # (largest smaller-member first, refinement 7) - not by how closely
    # matched their sizes/positions are to each other.
    best_pair = None
    best_pair_key = None  # (min area of the two, summed area) - both maximized
    for i in range(len(pairing_candidates)):
        ax, ay, aw, ah, aa, _al = pairing_candidates[i]
        acx, acy = ax + aw / 2, ay + ah / 2
        # 10. This midline-exclusion distance used to scale off the
        # candidate's OWN size (`max(aw, ah)`), which was fine while eye
        # components stayed small, but refinement 8's larger `max_area`
        # let a real eye's own bounding box grow past 100px - at that size
        # `max(aw, ah)` itself exceeded how far off-center the eye actually
        # sits, so the real eye got excluded as "too close to the midline"
        # (confirmed: a genuine eye 83px off-center was rejected because its
        # own box was 130px tall). Scaled off bbox WIDTH instead, like every
        # other distance threshold in this function (refinement 5).
        if abs(acx - center_x) < bbox_width * 0.08:
            continue  # too close to the midline itself to be one of a pair (e.g. a button)
        for j in range(i + 1, len(pairing_candidates)):
            bx, by, bw, bh, ba, _bl = pairing_candidates[j]
            bcx, bcy = bx + bw / 2, by + bh / 2
            if (acx - center_x) * (bcx - center_x) > 0:
                continue  # same side of center - not a mirrored pair
            mirror_of_a = 2 * center_x - acx
            x_mismatch = abs(mirror_of_a - bcx)
            y_mismatch = abs(acy - bcy)
            # Tolerances are fixed fractions of bbox WIDTH (the stable
            # head-scale proxy, refinement 5), not of the candidate blobs'
            # own size - scaling off a candidate's own size let one
            # abnormally tall/wide false-positive blob (e.g. a hair-shadow
            # streak) buy itself extra slack and out-rank the real, tightly
            # eye-height-matched eyes (docs/project-status.md §10). Eyes sit
            # at almost exactly the same height, so y needs to be tight;
            # x (the mirror match) can be a bit more forgiving since
            # asymmetric character designs can shift it slightly.
            if x_mismatch > bbox_width * 0.20 or y_mismatch > bbox_width * 0.06:
                continue
            key = (min(aa, ba), aa + ba)
            if best_pair_key is None or key > best_pair_key:
                best_pair_key = key
                best_pair = (pairing_candidates[i], pairing_candidates[j])

    if best_pair is not None:
        primary, secondary_box = sorted(best_pair, key=lambda b: -b[4])
    else:
        primary = boxes[0]
        secondary_box = None

    rgb = arr[:, :, :3]
    px, py, pw, ph, pa, primary_label = primary

    # Establish the eye's own color and refine primary's center to a darker
    # shade of that same color (see refinement 4 above), using the actual
    # connected-component pixels (`labels == primary_label`) rather than the
    # rectangular bounding box - the box's corners can include a few
    # non-component pixels (e.g. a bit of the dark pupil/outline right next
    # to the saturated red iris), which pulled the reference color toward
    # near-black in testing rather than the vivid red the eye actually is.
    primary_mask = labels == primary_label
    pys, pxs = np.where(primary_mask)
    # 9. Restrict to the BOTTOM half of the component's own y-range before
    # picking the darkest pixels. Refinement 8's larger `max_area` lets the
    # eye's connected component fuse with the eyebrow above it (a common,
    # anatomically-correct shape - eyebrow sits directly above the eye) -
    # but the eyebrow is itself dark and can outnumber the pupil's own dark
    # pixels, so the unrestricted "darkest 35% of the whole component"
    # centroid was landing on the eyebrow instead of the eye (confirmed
    # visually, docs/project-status.md §11: the painted patch erased hair/
    # eyebrow pixels just above the still-visible iris). The eyebrow can
    # only be above the eye for a front-facing character, never below, so
    # restricting the search to the bottom half is a safe, anatomically-
    # grounded way to land back on the pupil regardless of how large the
    # fused component is.
    y_mid = (pys.min() + pys.max()) / 2
    bottom_half = pys >= y_mid
    if bottom_half.any():
        pys, pxs = pys[bottom_half], pxs[bottom_half]
    primary_pixels = rgb[pys, pxs].astype(np.int32)
    primary_luminance = primary_pixels.sum(axis=1)
    # 11. Averaging the darkest 35% BY PERCENTILE (rather than by spatial
    # proximity) mixed pixels from wherever they happened to be darkest
    # across the whole bottom half, not necessarily from the pupil itself -
    # on a character with a busy/detailed hair texture, the connected
    # component's bottom half can still contain scattered dark hair-shadow
    # pixels far from the eye, and averaging those together with actual
    # pupil pixels produced a muddy color that matched neither (confirmed:
    # a purple-eyed character's `ref_color` came out dark reddish-brown,
    # which doesn't exist anywhere on that character). Anchoring on the
    # single darkest pixel first (almost always the pupil's own core -
    # pupils are the darkest point in the eye by design) and then averaging
    # only a small, spatially local neighborhood around it keeps the sample
    # confined to one coherent region instead of blending disparate ones.
    darkest_idx = int(np.argmin(primary_luminance))
    darkest_x, darkest_y = int(pxs[darkest_idx]), int(pys[darkest_idx])
    near = (np.abs(pxs - darkest_x) <= 3) & (np.abs(pys - darkest_y) <= 3)
    if near.sum() < 3:
        near = np.zeros(len(pys), dtype=bool)
        near[darkest_idx] = True
    ref_color = primary_pixels[near].mean(axis=0)
    primary_center = (float(pxs[near].mean()), float(pys[near].mean()))

    # Mirror-symmetry fallback for the second eye. If refinement 6 above
    # already found a good mirrored pair, `secondary_box` (the other member
    # of that pair) is the obvious choice - no need to search again. If it
    # didn't (no plausible pair - e.g. a genuine single-eye view), fall back
    # to the original approach: find whichever OTHER candidate sits closest
    # to the primary eye's mirror position (reflected across the character's
    # horizontal center), or the mirror position itself as a last resort -
    # independently detecting both eyes by area alone was unreliable in
    # testing (one eye was partly covered by a hair highlight/bangs, so its
    # saturated area lost to an actual hair-highlight blob for the "2nd
    # largest" slot, docs/design/05-constraints-and-limitations.md §1).
    # Either way, `_refine_eye_center()` below corrects the guess against the
    # real eye color rather than trusting the geometry outright (refinement 4).
    mirror_center_x = 2 * center_x - primary_center[0]

    if secondary_box is not None:
        mx, my, mw, mh, _ma, _ml = secondary_box
        secondary_guess = (mx + mw / 2, my + mh / 2)
    else:
        best_match = None
        best_dist = float("inf")
        for cand in boxes[1:]:
            cx, cy, cw, ch, ca, _cand_label = cand
            if ca < pa * 0.4:
                continue  # too small relative to the primary eye - would under-cover it (verified empirically: an early version accepted a tiny 6x4 match here and the resulting blink frame only fully closed one eye)
            cand_center_x = cx + cw / 2
            dist = abs(cand_center_x - mirror_center_x) + abs(cy - py)
            if dist < best_dist:
                best_dist = dist
                best_match = cand

        tolerance = pw * 2 + 10  # generous - just needs to be roughly on the mirrored side at a similar height
        if best_match is not None and best_dist <= tolerance:
            mx, my, mw, mh, _ma, _ml = best_match
            secondary_guess = (mx + mw / 2, my + mh / 2)
        else:
            mw, mh = pw, ph
            secondary_guess = (mirror_center_x, primary_center[1])

    # 12. The search radius used to scale off the PRIMARY box's own size
    # (`pw`/`ph`), which blew up past 100-250px once refinement 8 let that
    # box grow to fit a fused eye+eyebrow component - wide enough to reach
    # all the way to the primary eye's own position and pull the "secondary"
    # center right back onto it (confirmed: a secondary guess 84px away from
    # its starting point, having drifted toward the primary eye). Scaled off
    # bbox WIDTH instead, sized to comfortably cover one eye's own
    # neighborhood without reaching across the face to the other one.
    secondary_center = _refine_eye_center(
        rgb,
        opaque,
        secondary_guess[0],
        secondary_guess[1],
        ref_color,
        radius_x=bbox_width * 0.15,
        radius_y=bbox_width * 0.08,
    )

    def box_from_center(cx: float, cy: float, bw: int, bh: int) -> tuple[int, int, int, int]:
        return (int(round(cx - bw / 2)), int(round(cy - bh / 2)), bw, bh)

    return [box_from_center(*primary_center, pw, ph), box_from_center(*secondary_center, mw, mh)]


def _dominant_color(
    pixels: np.ndarray, exclude: tuple[tuple[int, int, int], ...] = ()
) -> tuple[int, int, int] | None:
    """Most common exact RGB color among `pixels` (an (N, 3) array), ignoring
    any color in `exclude`. Returns None if nothing qualifies."""
    if exclude:
        keep = np.ones(len(pixels), dtype=bool)
        for c in exclude:
            keep &= ~np.all(pixels == np.array(c), axis=1)
        pixels = pixels[keep]
    if len(pixels) == 0:
        return None
    colors, counts = np.unique(pixels, axis=0, return_counts=True)
    dominant = colors[np.argmax(counts)]
    return (int(dominant[0]), int(dominant[1]), int(dominant[2]))


def make_blink_frame(
    final_image: Image.Image,
    eye_boxes_pre: list[tuple[int, int, int, int]],
    scale: float,
    grid_size: int,
    output_size: int,
    face_band: tuple[float, float] = (0.25, 0.65),
    outline_color: tuple[int, int, int, int] = OUTLINE_COLOR,
) -> Image.Image | None:
    """Paints over the detected eye position(s) on `final_image` (the
    upscaled, ⑥-stage output), simulating closed eyes.

    All eyes are painted with one shared fill color: the most common color
    pooled across the small rings immediately surrounding every eye (a
    `unit`-sized margin around each eye's painted patch, `unit` sized off
    `output_size` alone - see the patch-sizing note below), sampled from
    `final_image`'s already-quantized palette so the result is always a
    color the character actually uses - concretely, the skin right around
    the eyes. Pooling both eyes' rings together (rather
    than coloring each eye independently) keeps the two eyes visually
    consistent even if one eye's immediate neighborhood is a little off
    (e.g. a hair strand or ear right next to it), and gives the dominant-color
    pick more data to work with.

    An eye-local ring was chosen over a single face-wide dominant color
    (naively, "most common color within `face_band`") because that broader
    approach was tried first and found to pick up whichever bulk color also
    happens to sit in that Y-range - e.g. a jacket collar - rather than skin,
    on a chibi-proportioned character where the band (sized for `detect_eyes()`'s
    saturation search, which doesn't have this problem) extends past the face
    into the shoulders. Sampling right around the eyes avoids that regardless
    of body proportions, since skin necessarily borders the eyes. Falls back to
    the `face_band` dominant color if the pooled ring has no other opaque
    pixels (e.g. the eyes sit right at the image edge), then to
    `outline_color` as a last resort. `outline_color` itself is always
    excluded from the candidate pool (it borders every region, so it would
    otherwise often win as "most common").

    Painting with a fixed dark outline color (the original approach) made
    blinks read as a black smudge rather than a closed eyelid.

    `eye_boxes_pre` are in pre.png coordinates (same space `detect_eyes()`
    returns). `scale` converts pre.png px -> grid px (docs/design/06-multi-angle-input.md
    §6 manifest field, same value img_to_pixcel_app computed as
    `pre.width / grid_size`). `grid_size`/`output_size` convert grid px ->
    final.png px (upscale ratio = output_size / grid_size).

    Returns None if no eye boxes were given, or none of them land on an
    opaque part of the final image (nothing to paint - fail soft rather than
    guess, per docs/design/05-constraints-and-limitations.md §1).
    """
    if not eye_boxes_pre:
        return None

    upscale_ratio = output_size / grid_size
    arr = np.array(final_image.convert("RGBA"))
    h, w = arr.shape[:2]
    alpha = arr[:, :, 3]
    opaque = alpha > 0
    ys, _xs = np.where(opaque)
    if len(ys) == 0:
        return None

    face_y0 = int(ys.min() + (ys.max() - ys.min()) * face_band[0])
    face_y1 = int(ys.min() + (ys.max() - ys.min()) * face_band[1])
    face_mask = np.zeros_like(opaque)
    face_mask[face_y0 : face_y1 + 1, :] = opaque[face_y0 : face_y1 + 1, :]

    # Pass 1: resolve every eye box to final-image coordinates and pool the
    # rings immediately surrounding all of them into one combined sample, so
    # both eyes are painted the same shade even if one eye's own immediate
    # neighborhood is a little off (e.g. a hair strand or ear right next to
    # it) - using more pooled data also makes the result more stable than
    # relying on each eye's small local ring independently.
    boxes: list[tuple[int, int, int, int]] = []
    ring_mask = np.zeros((h, w), dtype=bool)
    # `unit` approximates one visually-meaningful "chunk" in the FINAL image,
    # sized off `output_size` alone rather than `upscale_ratio` (= output_size
    # / grid_size). A given eye's footprint in final pixels is governed by
    # `output_size` (the display scale) - `grid_size` only changes how finely
    # the character is quantized internally before that same final size is
    # rendered, so it shouldn't shrink or grow how big the painted patch
    # needs to be. Found empirically: with grid_size=output_size=64
    # (upscale_ratio=1), sizing off `upscale_ratio` (as an earlier version
    # did) made `block`, and therefore the painted patch, half as wide as at
    # grid_size=32/output_size=64 (upscale_ratio=2) even though the eye's
    # actual final-pixel size was the same in both cases - leaving a stray
    # unpainted eye pixel at the smaller patch size.
    unit = max(1, round(output_size / 32))
    paint_size = unit + 2  # a couple pixels of slack beyond one unit, same reasoning as before: better to overshoot onto skin than leave a stray eye pixel uncovered
    for x, y, box_w, box_h in eye_boxes_pre:
        cx_pre, cy_pre = x + box_w / 2, y + box_h / 2
        gx, gy = cx_pre / scale, cy_pre / scale
        fx, fy = int(round(gx * upscale_ratio)), int(round(gy * upscale_ratio))

        bx0, bx1 = max(0, fx - paint_size // 2), min(w, fx + paint_size // 2 + 1)
        by0, by1 = max(0, fy - paint_size // 2), min(h, fy + paint_size // 2 + 1)
        if bx0 >= bx1 or by0 >= by1:
            continue
        if arr[by0:by1, bx0:bx1, 3].max() == 0:
            continue  # this box doesn't land on the character at all - skip it

        boxes.append((bx0, bx1, by0, by1))
        rx0, rx1 = max(0, bx0 - unit), min(w, bx1 + unit)
        ry0, ry1 = max(0, by0 - unit), min(h, by1 + unit)
        ring_mask[ry0:ry1, rx0:rx1] = opaque[ry0:ry1, rx0:rx1]

    if not boxes:
        return None

    for bx0, bx1, by0, by1 in boxes:
        ring_mask[by0:by1, bx0:bx1] = False  # exclude the eyes themselves

    fill_rgb = (
        _dominant_color(arr[ring_mask][:, :3], exclude=(outline_color[:3],))
        or _dominant_color(arr[face_mask][:, :3], exclude=(outline_color[:3],))
        or outline_color[:3]
    )

    # Pass 2: paint every eye box with the shared fill color.
    for bx0, bx1, by0, by1 in boxes:
        arr[by0:by1, bx0:bx1, :3] = fill_rgb
        arr[by0:by1, bx0:bx1, 3] = 255

    return Image.fromarray(arr, mode="RGBA")
