"""Render the Fable usage panel for the RT82 LCD.

Gauge data comes from the cache ~/.claude/statusline.mjs already maintains, so
there is exactly one process talking to the usage API. The panel is one number
and a mascot whose face tracks it; the clock says when the frame was rendered,
which matters because the screen holds its last image in 2.4GHz mode.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import mascot

W, H = 240, 136
HERE = Path(__file__).parent
CLAUDE = Path.home() / ".claude"
STATUSLINE = CLAUDE / "statusline.mjs"
USAGE_CACHE = Path(os.environ.get("TEMP", "/tmp")) / "cc-statusline-usage.json"

CACHE_MAX_AGE = 600  # seconds before we ask statusline.mjs to refresh

BG = (31, 29, 27)
FG = (245, 240, 232)
DIM = (150, 140, 128)
ACCENT = (217, 119, 87)
TRACK = (56, 50, 46)

MASCOT_XY = (8, 12)           # multiples of 4: see mascot.py on DXT1 blocks
# the animation moves parts up to MAX_DX/MAX_DY cells; (8, 12) leaves room
MASCOT_W = mascot.COLS * mascot.SCALE
MASCOT_H = mascot.ROWS * mascot.SCALE
RIGHT = W - 8                 # right edge for the number column
COL_LEFT = MASCOT_XY[0] + MASCOT_W + 12


def level_color(pct: float):
    if pct >= 90:
        return (248, 81, 73)
    if pct >= 70:
        return (240, 158, 46)
    return (86, 211, 100)


def font(name: str, size: int):
    root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for candidate in (name, "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(str(root / candidate), size)
        except OSError:
            continue
    return ImageFont.load_default()


BOLD = "segoeuib.ttf"
REG = "segoeui.ttf"


# --------------------------------------------------------------------------- data

def read_usage(refresh: bool = True) -> tuple[float | None, int | None]:
    """(percent, resets_at) for the Fable weekly bucket."""
    if refresh and _cache_age() > CACHE_MAX_AGE and STATUSLINE.exists():
        try:
            subprocess.run(["node", str(STATUSLINE), "--fetch-usage"],
                           timeout=15, capture_output=True)
        except Exception:
            pass
    try:
        d = json.loads(USAGE_CACHE.read_text())
    except Exception:
        return None, None
    for limit in d.get("limits") or []:
        if limit.get("name") == "Fable":
            return limit.get("pct"), limit.get("resets_at")
    return None, None


def _cache_age() -> float:
    try:
        return time.time() - USAGE_CACHE.stat().st_mtime
    except OSError:
        return 1e9


# ------------------------------------------------------------------------ drawing

def _fit(dr, text, name, size, max_w):
    """Largest font at or below `size` whose rendering fits in max_w."""
    while size > 10:
        f = font(name, size)
        bb = dr.textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= max_w:
            return f, bb
        size -= 2
    f = font(name, size)
    return f, dr.textbbox((0, 0), text, font=f)


def render(pct, frame: int = 0, now: datetime | None = None) -> Image.Image:
    """One frame of the panel. `now` is shared across frames so the stamp
    cannot tick over between them."""
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    known = pct is not None
    accent = level_color(pct) if known else DIM
    now = now or datetime.now()

    mascot.draw(img, *MASCOT_XY, mascot.mood_for(pct), frame)

    # label, top of the number column: "FABLE  weekly", right-aligned
    f_lab, f_sub = font(BOLD, 12), font(REG, 12)
    lab, sub = "FABLE", "  weekly"
    lw = dr.textbbox((0, 0), lab, font=f_lab)[2]
    sw = dr.textbbox((0, 0), sub, font=f_sub)[2]
    dr.text((RIGHT - sw - lw, 8), lab, font=f_lab, fill=ACCENT)
    dr.text((RIGHT - sw, 8), sub, font=f_sub, fill=DIM)

    # the one number, right-aligned and centred on the mascot's height
    label = f"{int(round(pct))}%" if known else "--"
    f_big, bb = _fit(dr, label, BOLD, 60, RIGHT - COL_LEFT)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    cy = MASCOT_XY[1] + MASCOT_H / 2 + 6
    dr.text((RIGHT - tw - bb[0], cy - th / 2 - bb[1]), label,
            font=f_big, fill=accent)

    # gauge, full width
    x0, x1, y, th = 8, RIGHT, 100, 12
    dr.rounded_rectangle([x0, y, x1, y + th], radius=6, fill=TRACK)
    if known and pct > 0:
        fill_w = int((x1 - x0) * min(1.0, pct / 100))
        if fill_w >= th:
            dr.rounded_rectangle([x0, y, x0 + fill_w, y + th], radius=6,
                                 fill=accent)

    # when this frame was rendered; the screen may hold it for days
    stamp = f"{now:%H:%M}"
    foot = f"updated {stamp}" if known else f"usage unavailable  \u00b7  {stamp}"
    dr.text((8, 118), foot, font=font(REG, 12), fill=DIM)
    return img


def signature(pct) -> str:
    """Stable key for "would this panel look meaningfully different?".

    Deliberately excludes the rendered clock: it ticks every minute, so hashing
    pixels would make every render unique and defeat the change gate entirely.
    The mascot's mood is a pure function of pct, so pct alone covers it.
    """
    return json.dumps({"pct": None if pct is None else round(pct)})


def frames(pct) -> list[Image.Image]:
    """Every frame of the animation loop, sharing one clock stamp."""
    now = datetime.now()
    return [render(pct, i, now) for i in range(len(mascot.ANIMATION))]


def build(refresh: bool = True) -> tuple[list[Image.Image], str]:
    pct, _ = read_usage(refresh)
    return frames(pct), signature(pct)


def _arg_pct(argv) -> tuple[bool, float | None]:
    """--pct N | --pct none  => (given, value); lets every mood render offline."""
    if "--pct" in argv:
        v = argv[argv.index("--pct") + 1]
        return True, (None if v.lower() == "none" else float(v))
    return False, None


if __name__ == "__main__":
    given, pct = _arg_pct(sys.argv)
    if not given:
        pct, _ = read_usage("--no-refresh" not in sys.argv)
    fr = frames(pct)
    fr[0].save(HERE / "preview.png")
    fr[0].resize((W * 3, H * 3), Image.NEAREST).save(HERE / "preview_3x.png")
    big = [f.resize((W * 3, H * 3), Image.NEAREST) for f in fr]
    big[0].save(HERE / "preview.gif", save_all=True, append_images=big[1:],
                duration=1000 // mascot.FPS, loop=0)
    print(f"Fable {pct}%  mood={mascot.mood_for(pct)}  frames={len(fr)}")
    print(f"wrote {HERE / 'preview.png'} and preview.gif")
