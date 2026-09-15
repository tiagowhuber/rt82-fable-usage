"""Pixel-art Clawd with headphones for the RT82 panel; the face tracks usage.

The body is traced from a 24x21-cell reference animation (rest pose). Every
cell is drawn as a SCALE x SCALE square and the sprite is placed at a multiple
of SCALE: with SCALE = 4 each cell is exactly one DXT1 block, so the QGIF
encoder reproduces it pixel-perfect instead of blending colours in a block.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

SCALE = 4
COLS, ROWS = 24, 21

ORANGE = (229, 115, 71)
BLUE = (20, 65, 124)
INK = (14, 8, 8)
WHITE = (255, 255, 255)
RED = (248, 81, 73)
DROP = (110, 170, 230)
DIM = (150, 140, 128)

PALETTE = {
    "o": ORANGE, "b": BLUE, "k": INK, "w": WHITE,
    "r": RED, "c": DROP, "g": DIM,
}

# fmt: off
BASE = [
    "........bbbbbbbb........",
    "......bbwwwwwwwwbb......",
    ".....bwwwwwwwwwwwwb.....",
    "....bwwwwwwwwwwwwwwb....",
    "....bwwwwwwwwwwwwwwb....",
    "...bboooooooooooooobb...",
    "..bbboooooooooooooobbb..",
    "..bbboooooooooooooobbb..",
    "..bbboooooooooooooobbb..",
    "..bbboooooooooooooobbb..",
    "...bboooooooooooooobb...",
    "oooooooooooooooooooooooo",
    "oooooooooooooooooooooooo",
    "oooooooooooooooooooooooo",
    "oooooooooooooooooooooooo",
    "....oooooooooooooooo....",
    "....oooooooooooooooo....",
    "....oo..oo....oo..oo....",
    "....oo..oo....oo..oo....",
    "....oo..oo....oo..oo....",
    "....oo..oo....oo..oo....",
]

# (row, col, cells) overlays on BASE. Eyes sit at cols 5-8 and 15-18.
FACES = {
    "happy": [                       # the reference's contented closed eyes
        (7, 5, "k..k"), (7, 15, "k..k"),
        (8, 5, ".kk."), (8, 15, ".kk."),
    ],
    "worried": [                     # same eyes upside down, a mouth, a drop
        (7, 5, ".kk."), (7, 15, ".kk."),
        (8, 5, "k..k"), (8, 15, "k..k"),
        (10, 11, "kk"),
        (6, 22, "c"), (7, 22, "c"),
    ],
    "alarmed": [                     # eyes wide open, mouth open, red !
        (6, 5, "wwww"), (6, 15, "wwww"),
        (7, 5, "wkkw"), (7, 15, "wkkw"),
        (8, 5, "wkkw"), (8, 15, "wkkw"),
        (9, 5, "wwww"), (9, 15, "wwww"),
        (10, 10, "kkkk"), (11, 10, "kkkk"),
        (0, 22, "r"), (1, 22, "r"), (2, 22, "r"), (4, 22, "r"),
    ],
    "asleep": [                      # flat eyes and a z
        (8, 5, "kkkk"), (8, 15, "kkkk"),
        (0, 21, "ggg"), (1, 22, "g"), (2, 21, "ggg"),
    ],
}
# fmt: on


def sprite(mood: str) -> list[str]:
    rows = [list(r) for r in BASE]
    for r, c, cells in FACES[mood]:
        for i, ch in enumerate(cells):
            if ch != ".":
                rows[r][c + i] = ch
            else:
                rows[r][c + i] = "o"     # "." in a patch means body, not hole
    return ["".join(r) for r in rows]


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
    dr = ImageDraw.Draw(img)
    for r, row in enumerate(sprite(mood)):
        for c, ch in enumerate(row):
            colour = PALETTE.get(ch)
            if colour is None:
                continue
            x0, y0 = x + c * scale, y + r * scale
            dr.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=colour)


def _check() -> None:
    assert len(BASE) == ROWS
    for i, row in enumerate(BASE):
        assert len(row) == COLS, f"base row {i}: {len(row)} cells"
    for mood in FACES:
        for i, row in enumerate(sprite(mood)):
            bad = set(row) - set(PALETTE) - {"."}
            assert not bad, f"{mood} row {i}: unknown cells {bad}"


_check()
