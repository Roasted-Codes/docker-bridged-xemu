"""
Read from KNOWN SAFE addresses during a live match.
Only uses user-space VAs that we've confirmed work with XBDM.
NO kernel VAs, NO speculative probing.

Usage: python read_live_safe.py [host]
"""
import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.20.0.51"
PORT = 731
TIMEOUT = 5.0
DELAY = 0.3  # 300ms between reads

def hexdump(data: bytes, prefix: str = "  ") -> str:
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{i:04x}: {hex_part:<48s} {ascii_part}")
    return "\n".join(lines)

def try_utf16(data: bytes) -> str:
    """Try to decode as UTF-16LE, return printable chars."""
    try:
        text = data.decode('utf-16-le', errors='replace')
        printable = "".join(c if 32 <= ord(c) < 127 else '' for c in text)
        return printable.rstrip('\x00') if printable else ""
    except:
        return ""

class SafeReader:
    def __init__(self, host, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(TIMEOUT)
        self.sock.connect((host, port))
        # Read banner
        self._recv_line()

    def _recv_line(self):
        buf = b""
        while not buf.endswith(b"\r\n"):
            buf += self.sock.recv(1)
        return buf.decode('ascii', errors='replace').strip()

    def read(self, addr: int, length: int) -> bytes:
        """Read memory. Returns bytes or empty bytes on failure."""
        time.sleep(DELAY)
        cmd = f"getmem2 addr=0x{addr:08X} length=0x{length:X}\r\n"
        self.sock.send(cmd.encode('ascii'))

        status = self._recv_line()
        if not status.startswith("203"):
            return b""

        data = b""
        self.sock.settimeout(3.0)
        try:
            while len(data) < length:
                chunk = self.sock.recv(min(length - len(data), 4096))
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        self.sock.settimeout(TIMEOUT)
        return data

    def close(self):
        try:
            self.sock.send(b"bye\r\n")
            self.sock.close()
        except:
            pass

def main():
    print(f"Reading SAFE addresses from {HOST}:{PORT} during live match\n")

    reader = SafeReader(HOST, PORT)

    # 1. Profile data - player name
    print("=== Profile Data (0x53D008) ===")
    data = reader.read(0x53D008, 64)
    if data:
        name = try_utf16(data)
        print(f"  Name: {name!r}" if name else "  (empty/zeros)")
        print(hexdump(data))

    # 2. Profile region P0 (0x53E0C0, stride 0x90)
    print("\n=== Profile Region P0 (0x53E0C0) ===")
    data = reader.read(0x53E0C0, 0x90)
    if data:
        name = try_utf16(data[:32])
        print(f"  Name: {name!r}" if name else "  (empty/zeros)")
        print(hexdump(data))

    # 3. Game state area (0x55C300) - changes during gameplay
    print("\n=== Game State Area (0x55C300, 256 bytes) ===")
    data = reader.read(0x55C300, 256)
    if data:
        nonzero = sum(1 for b in data if b != 0)
        print(f"  Non-zero bytes: {nonzero}/256")
        print(hexdump(data))

    # 4. PCR P0 (0x55CAF0) - usually empty during match
    print("\n=== PCR P0 (0x55CAF0, 64 bytes) ===")
    data = reader.read(0x55CAF0, 64)
    if data:
        name = try_utf16(data[:32])
        all_zero = all(b == 0 for b in data)
        print(f"  {'ALL ZEROS (as expected during match)' if all_zero else f'Name: {name!r}'}")
        if not all_zero:
            print(hexdump(data))

    # 5. Session players P0 (0x55D790, stride 0x1F8) - read 0x1F8 bytes
    print("\n=== Session Players P0 (0x55D790, 0xA4 bytes) ===")
    data = reader.read(0x55D790, 0xA4)
    if data:
        # Try finding name at various offsets
        for off in [0, 0x10, 0x20, 0x30, 0x40]:
            name = try_utf16(data[off:off+32])
            if name:
                print(f"  Name at +0x{off:02X}: {name!r}")
        nonzero = sum(1 for b in data if b != 0)
        print(f"  Non-zero bytes: {nonzero}/{len(data)}")
        print(hexdump(data))

    # 6. PGCR Display (0x56B900) - usually empty during match
    print("\n=== PGCR Display (0x56B900, 64 bytes) ===")
    data = reader.read(0x56B900, 64)
    if data:
        all_zero = all(b == 0 for b in data)
        print(f"  {'ALL ZEROS (as expected during match)' if all_zero else 'HAS DATA'}")
        if not all_zero:
            print(hexdump(data))

    # 7. Look around game state area more broadly
    # Read 0x55C000 - 0x55D000 in 256-byte chunks to find non-zero data
    print("\n=== Game State Scan (0x55C000 - 0x55D800, non-zero regions) ===")
    for addr in range(0x55C000, 0x55D800, 0x100):
        data = reader.read(addr, 0x100)
        if data:
            nonzero = sum(1 for b in data if b != 0)
            if nonzero > 10:  # Only show regions with significant data
                # Check for UTF-16 strings
                name = try_utf16(data[:32])
                tag = f" name={name!r}" if name else ""
                print(f"  0x{addr:06X}: {nonzero}/256 non-zero bytes{tag}")

    reader.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
