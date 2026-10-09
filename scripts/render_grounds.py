"""Render the site's cricket-ground imagery procedurally (numpy + Pillow).

A top-down ground at true scale: mown outfield, the square with old strips, a
worn pitch with painted creases and stumps, the fielding circle (two
semicircles of painted dots joined by straight lines, as on a real ground),
rope, boards, sight screens, two tiers of seating with a seat-by-seat crowd,
a roof canopy and six floodlight towers. Surfaces are painted as albedo and
then lit, so the night version is genuinely dark outside the light pools.

Outputs (site/assets/img/ground/):
  field-day.webp, field-night.webp   square bases for field plans (180 m across)
  hero-night.webp                    wide night view for the selection room
  social-night.jpg                   background for the social card
  field.json                         geometry, so overlays can place fielders in metres

Run:  python scripts/render_grounds.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, zoom

OUT = Path(__file__).resolve().parents[1] / "site" / "assets" / "img" / "ground"
RX, RY = 68.0, 72.0      # boundary semi-axes in metres; the long axis runs along the pitch
HALF_PITCH = 10.06       # middle of the pitch to the stumps
CIRCLE = 27.43           # fielding-circle radius around each set of stumps
SEED = 20261009
F32 = np.float32


def fractal(shape, scale_px, rng, octaves=4, persistence=0.55):
    """Smooth fractal noise in roughly [-1, 1]."""
    h, w = shape
    out = np.zeros(shape, F32)
    amp = total = 0.0
    amp = 1.0
    for o in range(octaves):
        cells = max(2, int(max(h, w) / max(1.0, scale_px / 2 ** o)))
        grid = rng.standard_normal((cells, cells)).astype(F32)
        out += amp * zoom(grid, (h / cells, w / cells), order=3)[:h, :w]
        total += amp
        amp *= persistence
    out /= total
    return np.clip(out / (np.abs(out).max() + 1e-6), -1, 1)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    t = np.asarray(t, F32)
    if t.ndim == a.ndim - 1:
        t = t[..., None]
    return a * (1 - t) + b * t


def hash2(a, b, salt=0):
    """Deterministic pseudo-random [0,1) per integer cell."""
    v = (a.astype(np.int64) * 73856093) ^ (b.astype(np.int64) * 19349663) ^ (salt * 83492791)
    v = (v * 2654435761) & 0xFFFFFFFF
    return (v / 4294967296.0).astype(F32)


def col(*rgb):
    return np.array(rgb, F32)


def render(size_px: int, span_m: float, night: bool, seed: int = SEED, cx: float = 0.0, cy: float = 0.0) -> np.ndarray:
    """Render `span_m` metres square, centred on ground point (cx, cy)."""
    rng = np.random.default_rng(seed)
    ppm = size_px / span_m
    c = (np.arange(size_px, dtype=F32) - size_px / 2 + 0.5) / ppm
    X, Y = np.meshgrid(c + cx, -c + cy)                # metres; +y up the image (bowler's end)
    R = np.sqrt((X / RX) ** 2 + (Y / RY) ** 2)         # 1 on the rope
    ANG = np.arctan2(Y, X)
    shape = X.shape
    low = fractal(shape, 80 * ppm, rng, 3)
    mid = fractal(shape, 12 * ppm, rng, 3)
    fine = gaussian_filter(rng.standard_normal(shape).astype(F32), (2.2, 0.5))   # grain along the mowing
    clumps = fractal(shape, max(3.0, 0.35 * ppm), rng, 2)                          # tufts, visible close up

    # ---------------------------------------------------------------- outfield
    band = np.tanh(3.0 * np.sin(np.pi * X / 5.5))                     # mown bands parallel to the pitch
    cross = np.tanh(2.0 * np.sin(np.pi * Y / 11.0))
    albedo = col(0.215, 0.36, 0.165)[None, None] * (1 + 0.085 * band + 0.022 * cross + 0.06 * low + 0.035 * mid + 0.025 * fine + 0.03 * clumps)[..., None]
    dry = smoothstep(0.25, 0.75, low * 0.5 + 0.5 + 0.25 * mid)
    albedo = mix(albedo, col(0.36, 0.40, 0.20) * (1 + 0.05 * fine[..., None]), dry * 0.22)
    run_up = np.exp(-(X ** 2) / 10 - (np.abs(Y) - 24) ** 2 / 60)      # worn bowlers' run-ups
    albedo = mix(albedo, col(0.40, 0.40, 0.24), run_up * 0.35)

    # ---------------------------------------------------------------- square
    sq = smoothstep(0.7, 0.0, np.maximum(np.abs(X) - 12.2, np.abs(Y) - 15.0))
    strip = np.floor((X + 12.2) / 3.05).astype(int)
    tone = (hash2(strip, np.zeros_like(strip), 7) - 0.5) * 0.06
    sq_alb = col(0.30, 0.43, 0.20)[None, None] * (1 + tone + 0.025 * np.tanh(2 * np.sin(np.pi * Y / 1.8)) + 0.03 * mid + 0.02 * clumps)[..., None]
    albedo = mix(albedo, sq_alb, sq * 0.6)
    seams = sum(np.exp(-((X - (k * 3.05 - 12.2)) ** 2) / 0.012) for k in range(1, 8)) * (np.abs(Y) < 14.5)
    albedo = albedo * (1 - 0.04 * seams[..., None])

    # ---------------------------------------------------------------- pitch
    pw, pl = 1.525, HALF_PITCH + 2.2
    in_pitch = smoothstep(0.1, -0.1, np.maximum(np.abs(X) - pw, np.abs(Y) - pl))
    pn = fractal(shape, 2.0 * ppm, rng, 3)
    pitch = col(0.70, 0.60, 0.44)[None, None] * (1 + 0.07 * pn + 0.04 * fine + 0.03 * clumps)[..., None]
    for e in (-1, 1):
        foot = np.exp(-((X + 0.55 * e) ** 2 / 0.35 + (Y - e * (HALF_PITCH - 3.0)) ** 2 / 3.0))
        guard = np.exp(-((X - 0.2 * e) ** 2 / 0.20 + (Y - e * (HALF_PITCH - 1.4)) ** 2 / 0.8))
        pitch = mix(pitch, col(0.50, 0.40, 0.28) * (1 + 0.2 * pn[..., None]), np.clip(foot * 0.6 + guard * 0.5, 0, 0.75))
    pitch = mix(pitch, sq_alb, smoothstep(pw - 0.4, pw, np.abs(X)) * 0.55)
    albedo = mix(albedo, pitch, in_pitch)

    paint = col(0.94, 0.93, 0.88)
    lw = max(0.07, 1.2 / ppm)

    def stroke(dist, strength=0.95):
        nonlocal albedo
        albedo = mix(albedo, paint, np.clip(1 - dist / lw, 0, 1) * strength)

    for e in (-1, 1):
        yb, yp = e * HALF_PITCH, e * (HALF_PITCH - 1.22)
        stroke(np.where(np.abs(X) < 1.32, np.abs(Y - yb), 99))
        stroke(np.where(np.abs(X) < 1.9, np.abs(Y - yp), 99))
        lo, hi = sorted((yp, e * (HALF_PITCH + 1.22)))
        for xr in (-1.32, 1.32):
            stroke(np.where((Y > lo) & (Y < hi), np.abs(X - xr), 99))
        sr = max(0.05, 1.6 / ppm)
        bail = (np.abs(Y - yb) < max(0.02, 0.6 / ppm)) & (np.abs(X) < 0.13)
        albedo = mix(albedo, col(0.55, 0.38, 0.20), bail.astype(F32))
        for xs in (-0.115, 0.0, 0.115):
            d = np.hypot(X - xs, Y - yb)
            albedo = mix(albedo, col(0.86, 0.80, 0.66), smoothstep(sr, sr * 0.5, d))
            albedo = mix(albedo, col(0.10, 0.08, 0.06), smoothstep(sr * 1.35, sr, d) * 0.6)

    # fielding circle: painted discs
    pts = []
    arc_n = int(math.pi * CIRCLE / 2.6)
    for k in range(arc_n + 1):
        t = math.pi * k / arc_n
        pts += [(CIRCLE * math.cos(t), HALF_PITCH + CIRCLE * math.sin(t)),
                (CIRCLE * math.cos(t + math.pi), -HALF_PITCH + CIRCLE * math.sin(t + math.pi))]
    for k in range(1, int(2 * HALF_PITCH / 2.6)):
        yy = -HALF_PITCH + k * 2 * HALF_PITCH / int(2 * HALF_PITCH / 2.6)
        pts += [(CIRCLE, yy), (-CIRCLE, yy)]
    dr = max(0.26, 1.7 / ppm)
    for dx, dy in pts:
        i0, j0 = int(size_px / 2 + (dx - cx) * ppm), int(size_px / 2 - (dy - cy) * ppm)
        if not (-50 < i0 < size_px + 50 and -50 < j0 < size_px + 50):
            continue
        r = int(dr * ppm) + 3
        sl = (slice(max(0, j0 - r), j0 + r), slice(max(0, i0 - r), i0 + r))
        d = np.hypot(X[sl] - dx, Y[sl] - dy)
        albedo[sl] = mix(albedo[sl], paint, smoothstep(dr, dr * 0.55, d) * 0.85)

    # ---------------------------------------------------------------- rope, boards, apron
    albedo = albedo * (1 - 0.30 * smoothstep(0.012, 0.0, np.abs(R - 1.006))[..., None])     # rope shadow
    albedo = mix(albedo, col(0.92, 0.89, 0.80), smoothstep(0.0035, 0.0012, np.abs(R - 1.0)))
    between = (R > 1.0) & (R < 1.058)
    albedo = np.where(between[..., None], albedo * 0.9, albedo)
    boards = (R >= 1.058) & (R < 1.072)
    seg = np.floor((ANG + np.pi) / (2 * np.pi) * 72).astype(int)
    brand = hash2(seg, np.ones_like(seg), 3)
    board = np.where((brand > 0.78)[..., None], col(0.62, 0.14, 0.14),
                     np.where((brand > 0.62)[..., None], col(0.85, 0.85, 0.82), col(0.06, 0.08, 0.12)))
    lettering = (np.sin((ANG + np.pi) * 72 * 10) > 0.6) & (np.abs(R - 1.065) < 0.0035)
    board = np.where(lettering[..., None], board * 0.5 + 0.35, board)
    albedo = np.where(boards[..., None], board, albedo)
    apron = (R >= 1.072) & (R < 1.105)
    albedo = np.where(apron[..., None], col(0.40, 0.40, 0.38)[None, None] * (1 + 0.05 * mid)[..., None], albedo)

    # ---------------------------------------------------------------- stands: seat-by-seat
    r_m = np.maximum(R - 1.105, 0) * 0.5 * (RX + RY)
    lower = (R >= 1.105) & (R < 1.30)
    walk = (R >= 1.30) & (R < 1.33)
    upper = R >= 1.33
    row = np.floor(np.where(upper, r_m - (1.33 - 1.105) * 70, r_m) / 0.85).astype(int)
    rowf = (np.where(upper, r_m - (1.33 - 1.105) * 70, r_m) / 0.85) % 1
    # every seat in a row shares one radius, so seats form clean cells rather than slanted streaks
    base_r = np.where(upper, 1.33, 1.105) * 0.5 * (RX + RY)
    radius_m = base_r + (row + 0.5) * 0.85
    arc = (ANG + np.pi) * radius_m
    seat = np.floor(arc / 0.52).astype(int)
    seatf = (arc / 0.52) % 1
    n_blocks = 16
    blk = np.floor((ANG + np.pi) / (2 * np.pi) * n_blocks).astype(int)
    blkf = ((ANG + np.pi) / (2 * np.pi) * n_blocks) % 1
    aisle = (blkf < 0.018) | (blkf > 0.982)
    tier = upper.astype(int)
    seat_col = np.array([[0.16, 0.20, 0.26], [0.12, 0.24, 0.20], [0.28, 0.12, 0.13], [0.22, 0.23, 0.25]], F32)
    plastic = seat_col[(blk // 3 + tier) % len(seat_col)]
    h1 = hash2(row + 1000 * tier, seat, 11)
    h2 = hash2(row, seat + 7, 23)
    h3 = hash2(seat, row + 3, 41)
    occupied = h1 < np.where(upper, 0.62, 0.78)
    shirts = np.array([[0.86, 0.86, 0.84], [0.14, 0.20, 0.36], [0.20, 0.21, 0.23], [0.55, 0.57, 0.60],
                       [0.12, 0.38, 0.24], [0.62, 0.20, 0.18], [0.40, 0.55, 0.72], [0.75, 0.62, 0.30],
                       [0.10, 0.10, 0.11], [0.80, 0.80, 0.78]], F32)
    shirt = shirts[(h2 * len(shirts)).astype(int) % len(shirts)] * (0.80 + 0.25 * h3[..., None])
    skin = col(0.62, 0.46, 0.34) * (0.55 + 0.6 * h3[..., None])
    head = (np.hypot(seatf - 0.5, rowf - 0.62) < 0.22)
    person = np.where(head[..., None], skin, shirt)
    cell_edge = (seatf < 0.12) | (seatf > 0.92) | (rowf < 0.18)
    seat_px = np.where(occupied[..., None], person, plastic)
    seat_px = np.where(cell_edge[..., None], seat_px * 0.45, seat_px)
    step = (rowf < 0.10)[..., None]
    seat_px = np.where(step, col(0.30, 0.30, 0.29), seat_px)
    seat_px = gaussian_filter(seat_px, (0.55, 0.55, 0))       # tame aliasing of sub-metre seats
    stand = np.where(aisle[..., None], col(0.34, 0.34, 0.33), seat_px)
    stand = np.where(walk[..., None], col(0.44, 0.44, 0.42)[None, None] * (1 + 0.04 * mid)[..., None], stand)
    # sight screens behind the bowler's arm at both ends
    screen = (np.abs(X) < 9.5) & (np.abs(Y) > RY * 1.075) & (np.abs(Y) < RY * 1.135)
    stand = np.where(screen[..., None], col(0.93, 0.93, 0.91), stand)
    # roof canopy over the upper tier: tensile panels between ribs, its edge casting shade
    roof = R >= 1.46
    ribs = np.abs(((ANG + np.pi) / (2 * np.pi) * 64) % 1 - 0.5) > 0.465
    roof_alb = col(0.78, 0.79, 0.78)[None, None] * (1 - 0.16 * ribs[..., None]) * (1 - 0.06 * smoothstep(1.46, 1.75, R)[..., None])
    stand = np.where(roof[..., None], roof_alb, stand)
    stand = stand * (1 - 0.35 * smoothstep(1.40, 1.46, R) * (R < 1.46))[..., None]
    in_stand = R >= 1.105
    albedo = np.where(in_stand[..., None], stand, albedo)

    towers = [math.radians(a) for a in (0, 60, 120, 180, 240, 300)]
    tower_r = 1.53

    # ---------------------------------------------------------------- lighting
    if not night:
        sun = np.array([-0.62, 0.78], F32)
        # stands shade the field edge on the sunward side
        shade = smoothstep(0.90, 1.03, R) * np.clip(-(X * sun[0] + Y * sun[1]) / 75, 0, 1) * (R < 1.105)
        light = 1.0 - 0.42 * shade
        light = light - 0.10 * smoothstep(1.0, 1.06, R) * (R < 1.105)          # occlusion by the boards
        img = albedo * light[..., None] * col(1.05, 1.03, 0.98)
        for a in towers:
            tx, ty = tower_r * RX * math.cos(a), tower_r * RY * math.sin(a)
            head = (np.abs((X - tx) * math.cos(a) + (Y - ty) * math.sin(a)) < 1.2) & \
                   (np.abs(-(X - tx) * math.sin(a) + (Y - ty) * math.cos(a)) < 4.0)
            img = np.where(head[..., None], col(0.30, 0.31, 0.32), img)
    else:
        ambient = col(0.030, 0.040, 0.062)
        illum = np.zeros(shape, F32)
        bloom = np.zeros(shape, F32)
        for a in towers:
            tx, ty = tower_r * RX * math.cos(a), tower_r * RY * math.sin(a)
            ax, ay = 0.15 * tx, 0.15 * ty
            illum += 0.42 * np.exp(-((X - ax) ** 2 + (Y - ay) ** 2) / (2 * 52 ** 2))
            illum += 0.10 * np.exp(-((X - tx) ** 2 + (Y - ty) ** 2) / (2 * 20 ** 2))
            d = np.hypot(X - tx, Y - ty)
            bloom += 1.2 * np.exp(-d ** 2 / (2 * 3.5 ** 2)) + 0.35 * np.exp(-d ** 2 / (2 * 13 ** 2))
        illum = illum * (1 - 0.55 * smoothstep(1.12, 1.6, R))                  # stands catch only spill
        illum = illum * np.where(roof, 0.25, 1.0)
        # exposure is set at mid-pitch whatever the camera frames
        centre = 0.0
        for a in towers:
            tx, ty = tower_r * RX * math.cos(a), tower_r * RY * math.sin(a)
            centre += 0.42 * math.exp(-((0.15 * tx) ** 2 + (0.15 * ty) ** 2) / (2 * 52 ** 2))
            centre += 0.10 * math.exp(-(tx ** 2 + ty ** 2) / (2 * 20 ** 2))
        img = albedo * (ambient[None, None] + illum[..., None] / centre * col(1.0, 0.98, 0.93) * 1.6)
        sheen = 0.07 * band * smoothstep(1.02, 0.6, R)                       # wet-look sheen on the mown bands
        img = img * (1 + sheen[..., None])
        boards_glow = boards & (brand > 0.62)
        img = np.where(boards_glow[..., None], img + col(0.10, 0.06, 0.05), img)
        for a in towers:
            tx, ty = tower_r * RX * math.cos(a), tower_r * RY * math.sin(a)
            lamp = (np.abs((X - tx) * math.cos(a) + (Y - ty) * math.sin(a)) < 1.0) & \
                   (np.abs(-(X - tx) * math.sin(a) + (Y - ty) * math.cos(a)) < 3.6)
            img = np.where(lamp[..., None], col(1.0, 0.98, 0.92), img)
        img = img + bloom[..., None] * col(1.0, 0.94, 0.80) * 0.45

    # ---------------------------------------------------------------- grade
    img = img * (1 - 0.30 * smoothstep(0.7, 1.9, R))[..., None]
    img = img + rng.standard_normal(shape).astype(F32)[..., None] * (0.010 if night else 0.006)
    k = 1.25
    img = (1 - np.exp(-k * np.clip(img, 0, None))) / (1 - math.exp(-k))
    return np.clip(img, 0, 1)


def save(arr, path, **kw):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((arr * 255 + 0.5).astype(np.uint8)).save(path, **kw)


CLOSEUP = {"span": 52.0, "cx": 0.0, "cy": -19.0}   # the striker's end, for the catchers' inset


def main(full=2400, close=1600, hero_px=2800):
    OUT.mkdir(parents=True, exist_ok=True)
    span = 180.0
    for night in (False, True):
        tag = "night" if night else "day"
        save(render(full, span, night), OUT / f"field-{tag}.webp", quality=92, method=6)
        save(render(close, CLOSEUP["span"], night, cx=CLOSEUP["cx"], cy=CLOSEUP["cy"]),
             OUT / f"closeup-{tag}.webp", quality=92, method=6)
    hero = np.rot90(render(hero_px, 196.0, True, SEED + 1))
    h = int(hero_px * 0.42)
    top = (hero_px - h) // 2
    band = hero[top:top + h]
    save(band, OUT / "hero-night.webp", quality=90, method=6)
    w = int(h * 1200 / 628)
    left = (hero_px - w) // 2 - int(hero_px * 0.05)
    crop = Image.fromarray((band * 255).astype(np.uint8)).crop((left, 0, left + w, h)).resize((1200, 628), Image.LANCZOS)
    crop.convert("RGB").save(OUT / "social-night.jpg", quality=90, optimize=True)
    (OUT / "field.json").write_text(json.dumps({
        "spanMetres": span, "boundary": {"rx": RX, "ry": RY}, "halfPitch": HALF_PITCH, "circleRadius": CIRCLE,
        "closeup": CLOSEUP,
        "note": "Image centre is the middle of the pitch; +y points to the top of the image (the bowler's end)."}, indent=1))
    print("rendered to", OUT)


if __name__ == "__main__":
    main()
