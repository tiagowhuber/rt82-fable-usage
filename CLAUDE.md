# Working notes

Read `README.md` first — it documents the protocol. This file is the operational
context: how to test without wasting cycles, what is actually verified, and what
not to waste time re-deriving.

## Before touching the device

The keyboard **must be in wired mode**: cable connected *and* the underside
slide switch in the **middle** position. 2.4GHz and wired are mutually exclusive
by that switch. Check first — it costs nothing:

```python
import hid
hid.enumerate(0x36B0, 0x30A3)   # empty => not wired, stop here
hid.enumerate(0x1919, 0x1919)   # non-empty BEFORE activation => wedged, replug
```

**Every failed transfer wedges the keyboard** in download mode and the only
recovery is a physical unplug/replug by the user. That makes each failed attempt
expensive in human terms, not just wall-clock. `upload.preflight()` already
refuses to start against a wedged device; do not bypass it, and prefer proving a
change against `replay.py` (known-good bytes) before risking a live push.

Iterate with a **solid-colour test image**, not the real panel — "is the screen
red?" needs no interpretation, and an all-one-colour frame is the same 16,840
bytes anyway. For layout work use `python render.py --pct N` (or `--pct none`)
and look at `preview_3x.png`; no device needed.

## Verified

- Full push: 301 packets, **2.5s**, on Windows 11, Python 3.14, hidapi 0.15.0.
- Mascot redesign (2026-09-15): pushed live, sprite crisp, warm palette reads well.
- Replay of the captured session: 3,184 reports, 5.6s, zero rejections.
- Gates: hourly timer and content signature both exercised.
- Hook returns in ~0.2s; detached child confirmed to run and release its lock.

## NOT verified

- **The "not wired" path.** It is a `hid.enumerate` check that exits before
  touching anything, but it has never actually run with the keyboard absent.
- **`screen_index` other than 0.** `upload()` takes the parameter and the
  protocol has the field, but every test wrote slot 0. Writing to slots 1/2 to
  preserve an existing GIF is plausible, unproven, and would need a live test.
- **Multi-frame QGIF.** Only single frames have been pushed.
- Any firmware other than the one on this keyboard.

## Dead ends — do not retry

- **`import rt82display`** fails on Windows. Its `__init__` pulls in `.cli`,
  which does `import fcntl` at module scope. Import submodules by path with
  `importlib` if you need them, or just call the binary.
- **The pure-Python `rt82display/qgif.py`** emits the RLE format from
  `QGIF.md`. That format is fiction; the screen will not display it. It looks
  convincing because solid colours compress to ~806 bytes and noise expands —
  correct RLE behaviour for a format the hardware does not use.
- **Removing the post-write read** to speed up the data phase. Without it the
  endpoint buffer fills and writes start returning -1 mid-transfer. 10ms is the
  tuned value; 500ms (upstream) costs 451 seconds.
- **Sending undocumented opcodes to the `0xFF60` keyboard interface.** Probing
  that command space once left the RGB in a strange state. Only `AA E2`,
  `AA E0`, and `AA E3` belong there.

## The encoder

`test_qgif.exe`, from the rt82display wheel at
`venv/Lib/site-packages/rt82display/_bin/`. Undocumented CLI:

```
test_qgif.exe <input_pattern> <output.qgif> <fps>
```

`input_pattern` contains a literal `X` which the encoder substitutes with
`0, 1, 2, …` to discover frames — so `frames/input_X.png` with `input_0.png`,
`input_1.png` present encodes two frames. `qgif.py` writes those to a temp dir.
Input must be **240×136** (both divisible by 4; the panel is 240×135 but the
encoder wants 136).

## Open questions

- **QGIF header bytes 4–7.** Ours reads `51 47 49 46 00 0f 00 01 3b 21`, the
  official tool's `51 47 49 46 00 13 00 27 3b 21`. `3b 21` is constant. The two
  differing 16-bit fields are probably frame count and delay/fps in some order,
  but that is untested. **This needs answering before multi-frame animation
  will work** — the rotating multi-stat idea depends on it. Encode with varying
  `fps` and frame counts and diff the headers; no device needed.
- Whether `AA 1C` repetition counts matter (3 before `1B`, 9 in the trailer) or
  whether they are just the web UI polling status.

## Ideas not built

- **Rotating multi-stat**: one animation whose frames cycle Fable weekly /
  5-hour session / spend. The keyboard loops frames itself, so it costs no extra
  USB traffic — upload once, rotate forever. Blocked on the header question.
- **Threshold alerts**: leave a normal GIF up, only push a loud red panel above
  85%. Near-zero flash writes.
- **Slot preservation**: write to slot 1 and leave the user's own GIF in slot 0.

## Gotchas

- `~/.claude/rt82/` is the **live deployment** and an independent copy of this
  repo. They drift. A directory junction (`mklink /J`, no admin needed on
  Windows) would fix that if it becomes annoying.
- The gauge reads a cache owned by `~/.claude/statusline.mjs`. Do not add a
  second caller of the usage API; shell out to its `--fetch-usage` flag instead.
- The content signature is the rounded percentage and nothing else. The panel
  draws a clock that ticks every minute, so a pixel hash would never match and
  the change gate would never fire. The mascot's mood derives from the
  percentage, so it is covered.
- **Keep the mascot on the 4px grid.** QGIF is DXT1: one 4×4 block holds two
  colours. `mascot.SCALE = 4` and a 4-aligned origin make every sprite cell one
  block, verified by decoding the encoder output (0 mixed blocks under the
  sprite, all four moods). Move it to an odd offset or scale and the edges
  smear. The sprite is 24×21 cells = 96×84px; the number column starts at
  x=116 and `_fit()` shrinks the font so `100%` still fits.
- The mascot body is traced from a 9-frame bobbing GIF (rest pose = frames 0
  and 4; the others shift the body by one cell). When multi-frame QGIF works,
  those frames are a ready-made animation. The sampling recipe is 24×21 cells
  of 12.5px from origin (78,118) in the 480px GIF, majority vote over a 5×5
  patch per cell.
- QGIF single-frame layout: 10-byte header, 255 × `0xFF`, 16,320 block bytes
  starting at offset 265, 255 × `0x00` trailer. Useful for decoding our own
  output offline; a naive "header is 520 bytes" assumption is wrong.
- Right after a successful push `1919:1919` stays enumerable for a few seconds
  before detaching. `preflight()` run in that window would call it wedged. The
  hourly gate runs first so the hook never hits this, but a manual `--force`
  immediately after another push might.
- Each push erases and rewrites keyboard flash. Respect the gates.
- The hook uses `pythonw.exe`, not `python.exe` — the latter flashes a console
  window on every turn.
