"""Render the Fable panel and push it to the RT82 screen, if it is worth doing.

Called from a Claude Code Stop hook after every turn, so almost every
invocation should decide to do nothing and exit quickly. Each real push erases
and rewrites keyboard flash, so both gates matter.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / "state.json"
LOCK = HERE / "push.lock"
LOG = HERE / "push.log"
QGIF_OUT = HERE / "current.qgif"

MIN_INTERVAL = 3600      # at most one flash write per hour
LOCK_STALE = 300         # a lock older than this is from a crashed run
LOG_LINES = 200

sys.path.insert(0, str(HERE))


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    try:
        old = LOG.read_text(encoding="utf-8").splitlines() if LOG.exists() else []
        LOG.write_text("\n".join((old + [line])[-LOG_LINES:]) + "\n",
                       encoding="utf-8")
    except OSError:
        pass


def acquire_lock() -> int | None:
    if LOCK.exists():
        try:
            if time.time() - LOCK.stat().st_mtime > LOCK_STALE:
                LOCK.unlink()
            else:
                return None
        except OSError:
            return None
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except OSError:
        return None


def release_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        LOCK.unlink()
    except OSError:
        pass


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def write_state(d: dict) -> None:
    try:
        STATE.write_text(json.dumps(d, indent=2))
    except OSError:
        pass


def main() -> int:
    force = "--force" in sys.argv
    verbose = force or "--verbose" in sys.argv

    import hid  # noqa: E402
    import render  # noqa: E402
    import qgif  # noqa: E402
    import upload as up  # noqa: E402

    state = read_state()

    if not force:
        since = time.time() - state.get("last_push", 0)
        if since < MIN_INTERVAL:
            if verbose:
                log(f"skip: {since / 60:.0f}m since last push "
                    f"(gate {MIN_INTERVAL // 60}m)")
            return 0

    # Cheapest check that rules out the common case: not in wired mode.
    if not hid.enumerate(up.KBD_VID, up.KBD_PID):
        if verbose:
            log("skip: keyboard not in wired mode")
        return 0

    lock = acquire_lock()
    if lock is None:
        if verbose:
            log("skip: another push holds the lock")
        return 0

    try:
        frames, sig = render.build()
        digest = hashlib.sha256(sig.encode()).hexdigest()
        if not force and digest == state.get("image_hash"):
            log("skip: nothing worth redrawing")
            return 0

        frames[0].save(HERE / "preview.png")
        data = qgif.encode(frames, QGIF_OUT, fps=render.mascot.FPS)

        try:
            up.preflight()
        except up.TransportError as e:
            log(f"skip: {e}")
            return 1

        elapsed = up.upload(data, screen_index=0, log=lambda *_: None,
                            progress_every=0)
        pct, _ = render.read_usage(refresh=False)
        log(f"pushed Fable {pct}% - {len(frames)} frames, {len(data)} bytes "
            f"in {elapsed:.1f}s")
        write_state({"last_push": time.time(), "image_hash": digest,
                     "pct": pct,
                     "at": datetime.now().isoformat(timespec="seconds")})
        return 0
    except Exception as e:
        log(f"failed: {type(e).__name__}: {e}")
        return 1
    finally:
        release_lock(lock)


if __name__ == "__main__":
    sys.exit(main())
