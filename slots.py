"""The user's own GIFs for screens 2 and 3.

The firmware only keeps what a transfer declares, so anything that should
survive a panel push has to be sent along with it. Drop files into
`slots/` next to push.py:

    slots/slot1.qgif   shown on screen 2 (already encoded, e.g. lifted from
    slots/slot2.qgif   a WebHID capture of the official tool)
    slots/slot1.gif    or a plain GIF/PNG; encoded on first use and cached as
                       slot1.qgif next to it, re-encoded when the source is newer

Slot 0 is always the usage panel. Missing slots are simply not sent.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

import qgif

HERE = Path(__file__).parent
SLOTS = HERE / "slots"
SOURCES = (".gif", ".png", ".jpg", ".jpeg", ".webp")


def _frames(path: Path) -> tuple[list[Image.Image], int]:
    """Frames letterboxed onto black at the panel size, plus an fps guess."""
    im = Image.open(path)
    n = getattr(im, "n_frames", 1)
    frames, durations = [], []
    for i in range(n):
        im.seek(i)
        durations.append(im.info.get("duration", 100) or 100)
        f = im.convert("RGBA")
        f.thumbnail((qgif.WIDTH, qgif.HEIGHT), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (qgif.WIDTH, qgif.HEIGHT), (0, 0, 0, 255))
        canvas.paste(f, ((qgif.WIDTH - f.width) // 2, (qgif.HEIGHT - f.height) // 2), f)
        frames.append(canvas)
    fps = max(1, min(30, round(1000 / (sum(durations) / len(durations)))))
    return frames, fps


def load(log=lambda *_: None) -> list[bytes]:
    """QGIF bytes for slot1, slot2 in order, stopping at the first gap."""
    out = []
    for k in (1, 2):
        cached = SLOTS / f"slot{k}.qgif"
        src = next((SLOTS / f"slot{k}{ext}" for ext in SOURCES
                    if (SLOTS / f"slot{k}{ext}").exists()), None)
        if src and (not cached.exists() or src.stat().st_mtime > cached.stat().st_mtime):
            frames, fps = _frames(src)
            qgif.encode(frames, cached, fps=fps)
            log(f"encoded {src.name}: {len(frames)} frames at {fps} fps")
        if not cached.exists():
            break
        out.append(cached.read_bytes())
    return out
