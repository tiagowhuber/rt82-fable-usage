"""Render the Fable usage panel for the RT82 LCD.

Gauge data comes from the cache ~/.claude/statusline.mjs already maintains, so
there is exactly one process talking to the usage API. History comes from the
local transcripts.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 240, 136
HERE = Path(__file__).parent
CLAUDE = Path.home() / ".claude"
PROJECTS = CLAUDE / "projects"
STATUSLINE = CLAUDE / "statusline.mjs"
USAGE_CACHE = Path(os.environ.get("TEMP", "/tmp")) / "cc-statusline-usage.json"

MODEL = "claude-fable-5-1"
HISTORY_DAYS = 7
CACHE_MAX_AGE = 600  # seconds before we ask statusline.mjs to refresh

BG = (13, 17, 23)
FG = (230, 237, 243)
DIM = (120, 133, 148)
TRACK = (33, 41, 52)
BAR_IDLE = (56, 74, 94)


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


def weighted(usage: dict) -> float:
    """Cache reads bill at roughly a tenth, and dominate raw totals ~10:1.

    Left unweighted every bar is the same height and the chart says nothing.
    """
    return (usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + 0.1 * usage.get("cache_read_input_tokens", 0))


def daily_history(days: int = HISTORY_DAYS) -> list[tuple[str, float]]:
    """[(weekday_letter, weighted_tokens)] oldest first, for Fable only."""
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)
    cutoff = time.time() - (days + 1) * 86400

    totals: dict[object, float] = defaultdict(float)
    seen: set[str] = set()

    if PROJECTS.is_dir():
        for path in PROJECTS.rglob("*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            try:
                fh = path.open(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            with fh:
                for line in fh:
                    if '"usage"' not in line or MODEL not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    msg = row.get("message") or {}
                    usage = msg.get("usage")
                    if not usage or msg.get("model") != MODEL:
                        continue
                    mid = msg.get("id")
                    if mid:
                        if mid in seen:
                            continue
                        seen.add(mid)
                    ts = row.get("timestamp")
                    if not ts:
                        continue
                    try:
                        when = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")).astimezone().date()
                    except ValueError:
                        continue
                    if start <= when <= today:
                        totals[when] += weighted(usage)

    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        out.append((("M", "T", "W", "T", "F", "S", "S")[day.weekday()],
                    totals.get(day, 0.0)))
    return out


def human_left(ts: int | None) -> str:
    if not ts:
        return ""
    s = int(ts - time.time())
    if s <= 0:
        return "resetting"
    d, rem = divmod(s, 86400)
    h, m = divmod(rem // 60, 60)
    if d:
        return f"{d}d {h}h"
    return f"{h}h {m}m" if h else f"{m}m"


# ------------------------------------------------------------------------ drawing

def render(pct, resets_at, history) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    known = pct is not None
    accent = level_color(pct) if known else DIM

    dr.text((12, 6), "FABLE", font=font(BOLD, 19), fill=FG)

    label = f"{int(round(pct))}%" if known else "--"
    f_big = font(BOLD, 34)
    bb = dr.textbbox((0, 0), label, font=f_big)
    dr.text((W - 12 - (bb[2] - bb[0]), 2), label, font=f_big, fill=accent)

    # the stamp shares this line rather than sitting right-aligned: the screen
    # holds its last image indefinitely, so the time has to be visible, and the
    # right side belongs to the percentage
    sub = f"resets in {human_left(resets_at)}" if known else "usage unavailable"
    dr.text((12, 31), f"{sub}  ·  {datetime.now():%H:%M}",
            font=font(REG, 12), fill=DIM)

    x0, x1, y, th = 12, W - 12, 50, 12
    dr.rounded_rectangle([x0, y, x1, y + th], radius=6, fill=TRACK)
    if known and pct > 0:
        fill_w = int((x1 - x0) * min(1.0, pct / 100))
        if fill_w >= th:
            dr.rounded_rectangle([x0, y, x0 + fill_w, y + th], radius=6, fill=accent)

    _sparkline(dr, history, top=74, bottom=116)
    return img


def _sparkline(dr, history, top: int, bottom: int):
    n = len(history)
    if not n:
        return
    left, right = 12, W - 12
    gap = 5
    bw = (right - left - gap * (n - 1)) / n
    peak = max(v for _, v in history) or 1.0
    height = bottom - top

    for i, (letter, value) in enumerate(history):
        x = left + i * (bw + gap)
        h = int(height * (value / peak)) if value > 0 else 0
        h = max(h, 2) if value > 0 else 2
        colour = BAR_IDLE if value <= 0 else level_color(0)
        dr.rectangle([x, bottom - h, x + bw - 1, bottom], fill=colour)
        f = font(REG, 10)
        bb = dr.textbbox((0, 0), letter, font=f)
        dr.text((x + (bw - (bb[2] - bb[0])) / 2, bottom + 3), letter,
                font=f, fill=DIM)


def signature(pct, resets_at, history) -> str:
    """Stable key for "would this panel look meaningfully different?".

    Deliberately excludes the rendered clock: it ticks every minute, so hashing
    pixels would make every render unique and defeat the change gate entirely.
    The reset countdown is bucketed to whole hours for the same reason.
    """
    hours_left = int((resets_at - time.time()) // 3600) if resets_at else None
    return json.dumps({
        "pct": None if pct is None else round(pct),
        "resets_h": hours_left,
        "history": [round(v) for _, v in history],
    }, sort_keys=True)


def build(refresh: bool = True) -> tuple[Image.Image, str]:
    pct, resets = read_usage(refresh)
    history = daily_history()
    return render(pct, resets, history), signature(pct, resets, history)


if __name__ == "__main__":
    pct, resets = read_usage("--no-refresh" not in sys.argv)
    hist = daily_history()
    img = render(pct, resets, hist)
    img.save(HERE / "preview.png")
    img.resize((W * 3, H * 3), Image.NEAREST).save(HERE / "preview_3x.png")
    print(f"Fable {pct}%  resets in {human_left(resets)}")
    print("history (weighted tokens):")
    for letter, v in hist:
        print(f"  {letter}  {v:>12,.0f}")
    print(f"wrote {HERE / 'preview.png'}")
