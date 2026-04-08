"""Scan XBDM-accessible memory for a player name to find user-space VAs."""
import sys, struct
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'c:\Users\james\code\StatsBorg')
from xbdm_client import XBDMClient

HOST = sys.argv[1] if len(sys.argv) > 1 else '172.20.0.51'
NAME = sys.argv[2] if len(sys.argv) > 2 else 'roasted'

client = XBDMClient(HOST, 731, timeout=5)
if not client.connect():
    print('XBDM connect failed'); sys.exit(1)

target = NAME.encode('utf-16-le')
print(f'Scanning for "{NAME}" in XBDM memory...')

regions = client.walk_memory()
print(f'{len(regions)} committed regions')
hits = []

for r in regions:
    base, size = r['base'], r['size']
    if base >= 0x7F000000 or size > 0x200000:
        continue
    CHUNK = 4096
    for off in range(0, size, CHUNK):
        addr = base + off
        read_size = min(CHUNK, size - off)
        data = client.read_memory(addr, read_size)
        if not data or target not in data:
            continue
        idx = 0
        while True:
            idx = data.find(target, idx)
            if idx < 0:
                break
            va = addr + idx
            hits.append(va)
            # Read PCR-sized context from name start
            ctx = client.read_memory(va, 0x120)
            if ctx and len(ctx) >= 0x74:
                try: n1 = ctx[0:32].decode('utf-16-le').rstrip('\x00')
                except: n1 = '?'
                try: n2 = ctx[0x20:0x40].decode('utf-16-le').rstrip('\x00')
                except: n2 = '?'
                k = struct.unpack('<i', ctx[0x60:0x64])[0]
                d = struct.unpack('<i', ctx[0x64:0x68])[0]
                a = struct.unpack('<i', ctx[0x68:0x6C])[0]
                s = struct.unpack('<i', ctx[0x6C:0x70])[0]
                tm = struct.unpack('<h', ctx[0x72:0x74])[0]
                print(f'  0x{va:08X}  name="{n1}" disp="{n2}" K:{k} D:{d} A:{a} S:{s} team:{tm}')
            else:
                print(f'  0x{va:08X}  (short read)')
            idx += len(target)

print(f'\nTotal: {len(hits)} hits')
client.disconnect()
