"""HID transport for the Epomaker RT82 LCD, Windows-native.

Protocol reverse-engineered by guysoft/rt82display (GPLv3); this is an
independent implementation because that package cannot be imported on Windows
(rt82display/__init__.py -> .cli -> `import fcntl`).

Two things upstream gets wrong on Windows, both fixed here:

1. Report framing. hidapi treats byte 0 of every write as the report number.
   Upstream writes a bare buffer starting 0xAA, so Windows sees a request for
   report 0xAA on an interface that only has report 0, and the keyboard
   ignores it. Correct framing is [0x00] + payload padded to
   OutputReportByteLength - 1, which we read from HidP_GetCaps rather than
   assume.

2. Unchecked writes. hid.write() returns -1 on a rejected buffer size. Ignoring
   that turns a total failure into a silent success that takes 451 seconds and
   changes nothing on screen.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

import hid

KBD_VID, KBD_PID = 0x36B0, 0x30A3
LCD_VID, LCD_PID = 0x1919, 0x1919
KBD_USAGE_PAGE = 0xFF60
LCD_USAGE_PAGE = 0x00FF

MAGIC = 0xAA
CMD_INIT, CMD_HANDSHAKE = 0xE2, 0xE0
SCREEN_PARAM = 0x38

_hid = ctypes.WinDLL("hid")
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
HIDP_STATUS_SUCCESS = 0x00110000


class _CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort), ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


class TransportError(RuntimeError):
    pass


def report_caps(path) -> tuple[int, int] | None:
    """(InputReportByteLength, OutputReportByteLength) straight from Windows."""
    p = path.decode() if isinstance(path, bytes) else path
    h = _k32.CreateFileW(ctypes.c_wchar_p(p), 0xC0000000, 0x3, None, 3, 0, None)
    if h == -1:
        h = _k32.CreateFileW(ctypes.c_wchar_p(p), 0, 0x3, None, 3, 0, None)
        if h == -1:
            return None
    try:
        pp = ctypes.c_void_p()
        if not _hid.HidD_GetPreparsedData(wintypes.HANDLE(h), ctypes.byref(pp)):
            return None
        try:
            c = _CAPS()
            if _hid.HidP_GetCaps(pp, ctypes.byref(c)) != HIDP_STATUS_SUCCESS:
                return None
            return c.InputReportByteLength, c.OutputReportByteLength
        finally:
            _hid.HidD_FreePreparsedData(pp)
    finally:
        _k32.CloseHandle(wintypes.HANDLE(h))


@dataclass
class Link:
    """An open HID interface that knows its own report size and checks writes."""

    dev: "hid.device"
    out_len: int
    label: str

    @property
    def payload(self) -> int:
        return self.out_len - 1

    def drain(self, timeout_ms: int = 1) -> None:
        """Consume any pending input report.

        The device answers writes during a transfer. Leaving those unread
        eventually makes it refuse further writes, which surfaces as
        hid.write() returning -1 partway through the data phase.
        """
        try:
            self.dev.read(self.out_len - 1, timeout_ms=timeout_ms)
        except Exception:
            pass

    def send(self, pkt, delay: float = 0.0, retries: int = 6,
             context: str = "", flow_ms: int = 50) -> None:
        """Write one report, reading the reply back for flow control.

        The read is not optional. Without it the host blasts packets
        back-to-back, the device's endpoint buffer fills and WriteFile starts
        returning -1 partway through the data phase. Upstream used a 500ms
        timeout here, which is what made a 16KB push take 451 seconds; a short
        timeout keeps the pacing without the stall.
        """
        if len(pkt) > self.payload:
            raise TransportError(
                f"{self.label}: {len(pkt)}-byte packet exceeds {self.payload}")
        buf = bytes([0x00]) + bytes(pkt) + bytes(self.payload - len(pkt))
        last = None
        for attempt in range(retries):
            n = self.dev.write(buf)
            if n >= 0:
                self.drain(flow_ms)
                if delay:
                    time.sleep(delay)
                return
            last = n
            self.drain(timeout_ms=5)
            time.sleep(0.02 * (attempt + 1))
        where = f" [{context}]" if context else ""
        raise TransportError(
            f"{self.label}: write rejected (returned {last}) after {retries} "
            f"attempts for a {len(buf)}-byte report{where}; "
            f"OutputReportByteLength={self.out_len}")

    def close(self) -> None:
        try:
            self.dev.close()
        except Exception:
            pass


def _pick(devs, usage_page):
    """Vendor interface only - never a mouse/keyboard collection.

    Windows owns Generic Desktop mouse (0x01/0x02) and keyboard (0x01/0x06)
    collections exclusively; opening either fails with access denied.
    """
    for d in devs:
        if d.get("usage_page") == usage_page:
            return d
    for d in devs:
        if d.get("usage_page", 0) >= 0xFF00:
            return d
    for d in devs:
        if d.get("interface_number") == 1 and d.get("usage_page") != 0x0001:
            return d
    return None


def _open(info, label) -> Link:
    caps = report_caps(info["path"])
    if caps is None:
        raise TransportError(f"{label}: could not read report caps")
    _, out_len = caps
    if out_len < 2:
        raise TransportError(f"{label}: no output reports (out_len={out_len})")
    d = hid.device()
    d.open_path(info["path"])
    d.set_nonblocking(True)
    return Link(d, out_len, label)


def open_keyboard(log=print) -> Link:
    devs = list(hid.enumerate(KBD_VID, KBD_PID))
    if not devs:
        raise TransportError(
            f"{KBD_VID:04X}:{KBD_PID:04X} not on the bus - the keyboard is not "
            "in wired mode. Set the underside slide switch to the middle "
            "position with the cable connected.")
    info = _pick(devs, KBD_USAGE_PAGE)
    if info is None:
        raise TransportError("no raw-HID interface on the keyboard")
    link = _open(info, "keyboard")
    log(f"  keyboard if={info['interface_number']} "
        f"usage_page=0x{info['usage_page']:04X} out_len={link.out_len}")
    return link


def open_lcd(timeout_s: float = 8.0, log=print) -> Link:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.3)
        devs = list(hid.enumerate(LCD_VID, LCD_PID))
        if not devs:
            continue
        info = _pick(devs, LCD_USAGE_PAGE)
        if info is None:
            raise TransportError(
                "LCD attached but exposes only protected collections")
        link = _open(info, "lcd")
        log(f"  lcd if={info['interface_number']} "
            f"usage_page=0x{info['usage_page']:04X} out_len={link.out_len}")
        return link
    raise TransportError(
        f"LCD {LCD_VID:04X}:{LCD_PID:04X} never enumerated after activation")


def preflight() -> None:
    """Refuse to start against a keyboard left in download mode.

    A failed transfer leaves 1919:1919 attached and the firmware wedged; the
    only recovery is a physical replug. Starting anyway wastes the attempt and
    produces a misleading failure further down the sequence.
    """
    if hid.enumerate(LCD_VID, LCD_PID):
        raise TransportError(
            "LCD is already attached, so the keyboard is stuck in download "
            "mode from an earlier attempt. Unplug it for ~5 seconds, plug it "
            "back in, and retry.")


def activate(kbd: Link) -> None:
    """The only two opcodes we send to the keyboard interface.

    Anything else on this interface risks hitting an unrelated firmware
    handler - an unrecognised opcode is the likeliest explanation for the RGB
    state change observed while probing.
    """
    kbd.send([MAGIC, CMD_INIT], delay=0.02)
    for _ in range(7):  # the official tool sends seven, upstream says five
        kbd.send([MAGIC, CMD_HANDSHAKE], delay=0.02)


def upload(data: bytes, screen_index: int = 0, log=print,
           progress_every: int = 100) -> float:
    """Push a QGIF to the screen. Returns elapsed seconds."""
    preflight()
    size = len(data)
    erase = (size + 65535) // 65536 + 1
    t0 = time.time()

    log("activating")
    kbd = open_keyboard(log)
    activate(kbd)
    lcd = open_lcd(log=log)

    chunk_size = lcd.payload - 8
    if chunk_size < 1:
        raise TransportError(f"lcd payload {lcd.payload} too small for data packets")

    try:
        log("entering download mode")
        lcd.send([MAGIC, 0x10])
        lcd.send(_clock_packet())
        lcd.send([MAGIC, 0x11])
        lcd.send([MAGIC, 0x1C])
        lcd.send([MAGIC, 0x10])
        lcd.send([MAGIC, 0x12, 0, 0, 0, SCREEN_PARAM])
        lcd.send([MAGIC, 0x11])
        for _ in range(3):
            lcd.send([MAGIC, 0x1C])

        lcd.send([MAGIC, 0x1B, 0, 0, 0, SCREEN_PARAM])
        # getGifCount, on the keyboard, after 0x1B - and only here. Upstream
        # also sends an 0xE3 on the LCD interface, which the official tool
        # never does and which makes the device reject the first data packet.
        kbd.send([MAGIC, 0xE3, 0, 0, 0, 1, 0, 0, 1])
        kbd.close()

        lcd.send([MAGIC, 0x14, 0, 0, 0, SCREEN_PARAM])

        log(f"transfer setup: {size} bytes, {erase} flash blocks, "
            f"{chunk_size}-byte chunks")
        lcd.send([MAGIC, 0x15, 0, 0, 0, SCREEN_PARAM, 0, 0,
                  screen_index, 1, erase, 0, 0,
                  size & 0xFF, (size >> 8) & 0xFF, (size >> 16) & 0xFF])
        lcd.send([MAGIC, 0x15, SCREEN_PARAM, 0, 0, SCREEN_PARAM])
        lcd.send([MAGIC, 0x15, 0x70, 0, 0, 0x10])
        lcd.send([MAGIC, 0x16, 0, 0, 0, SCREEN_PARAM])
        lcd.send([MAGIC, 0x18, 0, 0, 0, 1, 0, 0, erase])
        wait = 0.5 * erase + 0.5
        log(f"erasing, waiting {wait:.1f}s")
        time.sleep(wait)

        total = (size + chunk_size - 1) // chunk_size
        log(f"sending {total} packets")
        off = 0
        n = 0
        while off < size:
            chunk = data[off:off + chunk_size]
            clen = len(chunk)
            lcd.send([MAGIC, 0x19, off & 0xFF, (off >> 8) & 0xFF,
                      (off >> 16) & 0xFF, clen, 0, 0]
                     + list(chunk) + [0] * (chunk_size - clen),
                     context=f"data packet {n + 1}/{total} offset {off}",
                     flow_ms=10)
            off += chunk_size
            n += 1
            if progress_every and (n % progress_every == 0 or n == total):
                log(f"  {n}/{total} ({n * 100 // total}%)")

        log("finalizing")
        lcd.send([MAGIC, 0x1A])
        lcd.send([MAGIC, 0x10])
        lcd.send(_clock_packet())
        lcd.send([MAGIC, 0x11])
        lcd.send([MAGIC, 0x11])
        for _ in range(9):
            lcd.send([MAGIC, 0x1C])
    finally:
        lcd.close()
        kbd.close()

    return time.time() - t0


def _clock_packet(now=None) -> list[int]:
    """0xAA 0x17 - wall clock as BCD-ish digits, one nibble value per byte.

    Upstream treats this as a static "config" packet and sends a hardcoded
    constant lifted from its own capture, which is simply a stale timestamp.
    The official tool sends the current time here, both before the transfer and
    again in the trailer.

    Layout after the 8-byte header: year(4) month(2) weekday(1) day(2)
    hour(2) minute(2) second(2). The capture shows weekday=2 on a Tuesday,
    matching isoweekday() with Sunday wrapped to 0.
    """
    import datetime
    now = now or datetime.datetime.now()
    y = now.year
    return [MAGIC, 0x17, 0, 0, 0, SCREEN_PARAM, 0, 0,
            (y // 1000) % 10, (y // 100) % 10, (y // 10) % 10, y % 10,
            now.month // 10, now.month % 10,
            now.isoweekday() % 7,
            now.day // 10, now.day % 10,
            now.hour // 10, now.hour % 10,
            now.minute // 10, now.minute % 10,
            now.second // 10, now.second % 10]
