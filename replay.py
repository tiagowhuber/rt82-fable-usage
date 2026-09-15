"""Replay the captured WebHID session byte-for-byte.

Everything here is known-good: the exact reports the official tool sent, in
order, carrying a QGIF it produced itself. If the screen changes, the transport
works and any later failure is ours. Report length selects the interface -
32-byte payloads are the keyboard (0xFF60), 64-byte the LCD (0x00FF).
"""
import sys
import time
from pathlib import Path

import upload as up

DEFAULT = Path(__file__).parent / "captures" / "webhid-official-tool.txt"
CAPTURE = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT


def load(path):
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        _, _, rest = line.partition(":")
        out.append(bytes(int(b, 16) for b in rest.split()))
    return out


def main():
    up.preflight()
    reports = load(CAPTURE)
    print(f"{len(reports)} reports from {CAPTURE.name}")

    kbd = up.open_keyboard()
    lcd = None
    sent = 0
    t0 = time.time()

    try:
        for i, p in enumerate(reports):
            if len(p) == 32:
                link = kbd
            else:
                if lcd is None:
                    # the LCD only exists once AA E2 / AA E0 have gone out
                    lcd = up.open_lcd()
                link = lcd

            link.send(list(p), context=f"report {i} (aa {p[1]:02x})", flow_ms=10)
            sent += 1

            # the capture carries no timing; the device still needs the flash
            # erase window after AA 18 before it will accept data packets
            if p[1] == 0x18:
                erase = p[8] or 1
                wait = 0.5 * erase + 0.5
                print(f"  [{i}] AA 18 erase_count={erase}, waiting {wait:.1f}s")
                time.sleep(wait)

            if sent % 500 == 0:
                print(f"  {sent}/{len(reports)} ({time.time() - t0:.0f}s)")

        print(f"\nreplayed {sent} reports in {time.time() - t0:.1f}s")
        print("the screen should now show the GIF you uploaded via the web tool")
        return 0
    except up.TransportError as e:
        print(f"\nFAILED after {sent} reports: {e}")
        return 1
    finally:
        if lcd:
            lcd.close()
        kbd.close()


if __name__ == "__main__":
    sys.exit(main())
