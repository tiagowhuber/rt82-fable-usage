"""PNG frames -> QGIF, via the prebuilt encoder shipped in the rt82display wheel.

The encoder is a wasm2c build of the same code the official web tool runs, so
its output is known-good. We only borrow the binary; the Python package around
it cannot be imported on Windows.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

WIDTH, HEIGHT = 240, 136  # the encoder requires both divisible by 4
# The "~64KB firmware buffer" in upstream's README is wrong: a capture of
# the official tool shows it pushing a 176,050-byte QGIF without complaint.
SIZE_LIMIT = 1024 * 1024

_ENCODER = Path(__file__).parent / "venv/Lib/site-packages/rt82display/_bin/test_qgif.exe"


class EncodeError(RuntimeError):
    pass


def encoder_path() -> Path:
    if not _ENCODER.exists():
        raise EncodeError(
            f"encoder not found at {_ENCODER}\n"
            "  reinstall with: venv/Scripts/pip install rt82display")
    return _ENCODER


def encode(frames: list[Image.Image], out: Path, fps: int = 8) -> bytes:
    """Encode frames to a QGIF file and return its bytes."""
    if not frames:
        raise EncodeError("no frames")
    enc = encoder_path()
    out = Path(out)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for i, f in enumerate(frames):
            if f.size != (WIDTH, HEIGHT):
                f = f.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
            f.convert("RGBA").save(td / f"input_{i}.png", "PNG")
        r = subprocess.run(
            [str(enc), str(td / "input_X.png"), str(out.absolute()), str(fps)],
            capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise EncodeError(f"encoder failed (rc={r.returncode}): "
                          f"{(r.stdout + r.stderr).strip()[:400]}")
    data = out.read_bytes()
    if data[:4] != b"QGIF":
        raise EncodeError(f"output is not QGIF (magic={data[:4]!r})")
    if len(data) > SIZE_LIMIT:
        raise EncodeError(
            f"{len(data)} bytes exceeds the {SIZE_LIMIT}-byte ceiling")
    return data
