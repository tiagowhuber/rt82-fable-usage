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


BLOCK = 65536  # flash erase block; every slot starts on a block boundary


@dataclass
class Plan:
    """Where each slot's bytes go and what the setup packets must say.

    From the official tool's three-GIF capture: slot k starts at the first
    block boundary after slot k-1 ends, the data phase sends only real bytes
    (offsets jump across the gaps), and the erase count is the number of
    blocks the last byte reaches into. Upstream's `+ 1` on the erase count
    matches neither capture.
    """

    slots: list[bytes]
    offsets: list[int]
    end: int
    erase: int

    @classmethod
    def build(cls, slots: list[bytes]) -> "Plan":
        if not slots:
            raise TransportError("nothing to upload")
        if len(slots) > 3:
            raise TransportError(f"{len(slots)} slots; the screen has 3")
        offsets, pos = [], 0
        for data in slots:
            offsets.append(pos)
            pos = -(-(pos + len(data)) // BLOCK) * BLOCK   # next block boundary
        end = offsets[-1] + len(slots[-1])
        return cls(slots, offsets, end, max(1, -(-end // BLOCK)))

    @property
    def count(self) -> int:
        return len(self.slots)

    def setup_packet(self) -> list[int]:
        # aa 15 00 00 00 38 00 00 | idx0 count erase 00 00 size0(3) | idx 00 size(3) ...
        pkt = [MAGIC, 0x15, 0, 0, 0, SCREEN_PARAM, 0, 0,
               0, self.count, self.erase, 0, 0] + _u24(len(self.slots[0]))
        for k in range(1, self.count):
            pkt += [k, 0] + _u24(len(self.slots[k]))
        return pkt


def _u24(n: int) -> list[int]:
    return [n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF]


def sequence(slots: list[bytes], chunk_size: int = 56, now=None):
    """Every packet of a transfer, in order: (iface, payload, opts).

    Pure, so a dry run can be diffed against a WebHID capture before anything
    is sent. `upload()` plays exactly this list.
    """
    plan = Plan.build(slots)
    K, L = "kbd", "lcd"
    seq = [(K, [MAGIC, CMD_INIT], {"delay": 0.02})]
    seq += [(K, [MAGIC, CMD_HANDSHAKE], {"delay": 0.02}) for _ in range(7)]

    seq += [
        (L, [MAGIC, 0x10], {}),
        (L, _clock_packet(now), {}),
        (L, [MAGIC, 0x11], {}),
        (L, [MAGIC, 0x1C], {}),
        (L, [MAGIC, 0x10], {}),
        (L, [MAGIC, 0x12, 0, 0, 0, SCREEN_PARAM], {}),
        (L, [MAGIC, 0x11], {}),
    ]
    seq += [(L, [MAGIC, 0x1C], {}) for _ in range(3)]
    seq.append((L, [MAGIC, 0x1B, 0, 0, 0, SCREEN_PARAM], {}))
    # getGifCount/setGifCount on the keyboard, after 0x1B - and only here.
    # Upstream also sends an 0xE3 on the LCD interface, which the official
    # tool never does and which makes the device reject the first data packet.
    seq.append((K, [MAGIC, 0xE3, 0, 0, 0, 1, 0, 0, plan.count],
                {"close_after": True}))
    seq += [
        (L, [MAGIC, 0x14, 0, 0, 0, SCREEN_PARAM], {}),
        (L, plan.setup_packet(), {"log": f"transfer setup: {plan.count} slot(s), "
                                          f"{plan.end} bytes, {plan.erase} flash blocks"}),
        (L, [MAGIC, 0x15, SCREEN_PARAM, 0, 0, SCREEN_PARAM], {}),
        (L, [MAGIC, 0x15, 0x70, 0, 0, 0x10], {}),
        (L, [MAGIC, 0x16, 0, 0, 0, SCREEN_PARAM], {}),
        (L, [MAGIC, 0x18, 0, 0, 0, 1, 0, 0, plan.erase],
         {"sleep_after": 0.5 * plan.erase + 0.5, "log": "erasing"}),
    ]
    for data, base in zip(plan.slots, plan.offsets):
        for off in range(0, len(data), chunk_size):
            chunk = data[off:off + chunk_size]
            pos = base + off
            seq.append((L, [MAGIC, 0x19] + _u24(pos) + [len(chunk), 0, 0] + list(chunk),
                        {"flow_ms": 10, "data": True,
                         "context": f"data packet offset {pos}"}))
    seq += [
        (L, [MAGIC, 0x1A], {}),
        (L, [MAGIC, 0x10], {}),
        (L, _clock_packet(now), {}),
        (L, [MAGIC, 0x11], {}),
        (L, [MAGIC, 0x11], {}),
    ]
    seq += [(L, [MAGIC, 0x1C], {}) for _ in range(9)]
    return seq


def upload(slots: bytes | list[bytes], log=print, progress_every: int = 100) -> float:
    """Push one or more QGIFs to the screen's slots. Returns elapsed seconds.

    Slot 0 is what the screen shows first; the user cycles with Fn+<key>.
    The firmware keeps only what this transfer declares, so every slot that
    should survive must be sent every time - that is what the official tool
    does too.
    """
    if isinstance(slots, (bytes, bytearray)):
        slots = [bytes(slots)]
    preflight()
    t0 = time.time()

    log("activating")
    kbd = open_keyboard(log)
    lcd = None
    try:
        total = n = 0
        for iface, pkt, opts in sequence(slots):
            if iface == "kbd":
                kbd.send(pkt, delay=opts.get("delay", 0.0))
                if opts.get("close_after"):
                    kbd.close()
                continue
            if lcd is None:
                lcd = open_lcd(log=log)
                chunk = lcd.payload - 8
                if chunk != 56:
                    # the sequence was laid out for the captured 64-byte reports
                    raise TransportError(
                        f"lcd payload {lcd.payload}: unexpected report size, refusing")
                total = sum(1 for _, _, o in sequence(slots) if o.get("data"))
            if "log" in opts:
                log(opts["log"])
            lcd.send(pkt, context=opts.get("context", ""),
                     flow_ms=opts.get("flow_ms", 50))
            if opts.get("data"):
                n += 1
                if progress_every and (n % progress_every == 0 or n == total):
                    log(f"  {n}/{total} ({n * 100 // total}%)")
            if "sleep_after" in opts:
                time.sleep(opts["sleep_after"])
        log("finalizing")
    finally:
        if lcd is not None:
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
