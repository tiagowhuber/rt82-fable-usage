"""Pixel-art Clawd for the RT82 panel, with a face that tracks usage.

Every cell is drawn as a SCALE x SCALE square and the sprite is meant to be
placed at a multiple of SCALE. With SCALE = 4 each cell is exactly one DXT1
block, so the QGIF encoder reproduces the sprite pixel-perfect instead of
smearing three colours into a two-colour block.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

SCALE = 4
SIZE = 16  # cells per side

BODY = (217, 119, 87)     # Claude terracotta
BODY_DK = (168, 84, 58)
INK = (38, 30, 26)
WHITE = (245, 240, 232)
RED = (248, 81, 73)
DROP = (110, 170, 230)
DIM = (150, 140, 128)

PALETTE = {
    "o": BODY, "d": BODY_DK, "k": INK, "w": WHITE,
    "r": RED, "b": DROP, "g": DIM,
}

# fmt: off
SPRITES = {
    "happy": [
        "................",
        "................",
        "...oooooooooo...",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "..oookkoookkoo..",
        "..oookkoookkoo..",
        "..oooooooooooo..",
        "..oookoooookoo..",
        "..ooookkkkoooo..",
        "..oooooooooooo..",
        "..dddddddddddd..",
        "...dddddddddd...",
        "....dd....dd....",
        "....dd....dd....",
        "................",
    ],
    "worried": [
        "................",
        "................",
        "...oooooooooo...",
        "..oooooooooooob.",
        "..ooookookoooob.",
        "..oookkoookkoo..",
        "..oookkoookkoo..",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "..oooookkkooooo.",
        "..oooooooooooo..",
        "..dddddddddddd..",
        "...dddddddddd...",
        "....dd....dd....",
        "....dd....dd....",
        "................",
    ],
    "alarmed": [
        "..............r.",
        "..............r.",
        "...oooooooooo.r.",
        "..oooooooooooo..",
        "..oowwwoowwwoor.",
        "..oowkwoowkwoo..",
        "..oowwwoowwwoo..",
        "..oooooooooooo..",
        "..oooookkkkoooo.",
        "..oooookkkkoooo.",
        "..oooooooooooo..",
        "..dddddddddddd..",
        "...dddddddddd...",
        "....dd....dd....",
        "....dd....dd....",
        "................",
    ],
    "asleep": [
        ".............ggg",
        "..............g.",
        "...ooooooooooggg",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "..oookkoookkoo..",
        "..oooooooooooo..",
        "..oooooooooooo..",
        "..oooookkooooo..",
        "..oooooooooooo..",
        "..dddddddddddd..",
        "...dddddddddd...",
        "....dd....dd....",
        "....dd....dd....",
        "................",
    ],
}
# fmt: on


def mood_for(pct: float | None) -> str:
    if pct is None:
        return "asleep"
    if pct >= 90:
        return "alarmed"
    if pct >= 70:
        return "worried"
    return "happy"


def draw(img: Image.Image, x: int, y: int, mood: str, scale: int = SCALE) -> None:
    """Paint the sprite with its top-left cell at (x, y)."""
    rows = SPRITES[mood]
    dr = ImageDraw.Draw(img)
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            colour = PALETTE.get(ch)
            if colour is None:
                continue
            x0, y0 = x + c * scale, y + r * scale
            dr.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=colour)


def _check() -> None:
    for name, rows in SPRITES.items():
        assert len(rows) == SIZE, f"{name}: {len(rows)} rows"
        for i, row in enumerate(rows):
            assert len(row) == SIZE, f"{name} row {i}: {len(row)} cells"
            bad = set(row) - set(PALETTE) - {"."}
            assert not bad, f"{name} row {i}: unknown cells {bad}"


_check()
