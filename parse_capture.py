"""Parse the WebHID capture from the official tool into ground truth.

Report length tells us the interface: 32-byte payloads go to the keyboard
(0xFF60, OutputReportByteLength 33), 64-byte payloads go to the LCD (0x00FF,
OutputReportByteLength 65).
"""
import sys
from pathlib import Path

DEFAULT = Path(__file__).parent / "captures" / "webhid-official-tool.txt"
src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT

records = []
for line in src.read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    rid, _, rest = line.partition(":")
    payload = bytes(int(b, 16) for b in rest.split())
    records.append((int(rid, 16), payload))

print(f"{len(records)} reports")
lens = {}
for _, p in records:
    lens[len(p)] = lens.get(len(p), 0) + 1
print("payload lengths:", lens)


def iface(p):
    return "KBD" if len(p) == 32 else "LCD"


print("\n=== control sequence (everything that is not 0xAA 0x19) ===")
idx_first_data = None
for i, (rid, p) in enumerate(records):
    if p[0] == 0xAA and p[1] == 0x19:
        idx_first_data = i
        break

for i, (rid, p) in enumerate(records[:idx_first_data]):
    print(f"  {i:3d} {iface(p):3s} aa {p[1]:02x}  {p[2:24].hex(' ')}")

print(f"\n=== data phase: reports {idx_first_data} .. ===")
data_records = [(i, p) for i, (rid, p) in enumerate(records) if p[0] == 0xAA and p[1] == 0x19]
print(f"  {len(data_records)} data packets")
first = data_records[0][1]
print(f"  first: offset={int.from_bytes(first[2:5],'little')} len={first[5]}")
last = data_records[-1][1]
print(f"  last : offset={int.from_bytes(last[2:5],'little')} len={last[5]}")

# reassemble
blob = bytearray()
for _, p in data_records:
    off = int.from_bytes(p[2:5], "little")
    ln = p[5]
    chunk = p[8:8 + ln]
    if len(blob) < off + ln:
        blob.extend(bytes(off + ln - len(blob)))
    blob[off:off + ln] = chunk

out = Path(__file__).parent / "captured.qgif"
out.write_bytes(bytes(blob))
print(f"  reassembled {len(blob)} bytes -> {out.name}")
print(f"  magic={bytes(blob[:4])!r}  header={bytes(blob[:16]).hex(' ')}")

# what the setup packet declared
for i, (rid, p) in enumerate(records[:idx_first_data]):
    if p[1] == 0x15 and p[2] == 0 and p[3] == 0:
        declared = int.from_bytes(p[13:16], "little")
        print(f"  setup declared size={declared} erase_count={p[10]} "
              f"screen_index={p[8]} screen_count={p[9]}")
        break

print("\n=== trailer (after last data packet) ===")
last_idx = data_records[-1][0]
for i, (rid, p) in enumerate(records[last_idx + 1:], start=last_idx + 1):
    print(f"  {i:4d} {iface(p):3s} aa {p[1]:02x}  {p[2:24].hex(' ')}")
