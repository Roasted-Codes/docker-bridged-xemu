"""
XBDM Client - Cross-platform Xbox Debug Monitor protocol client

Connects to XBDM on port 731 to read/write Xbox memory.

Requirements:
- For Xemu: xbdm_gdb_bridge must be running (implements XBDM protocol)
- For Real Xbox: Connect directly (native XBDM support)

Usage:
    client = XBDMClient('127.0.0.1')
    client.connect()
    data = client.read_memory(0x55CAF0, 256)
    client.disconnect()

See ProjectState.md for full project context.
"""

import select
import socket
import struct
import time
from typing import List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class XBDMResponse:
    """Response from XBDM command"""
    status_code: int
    message: str
    data: Optional[bytes] = None


class XBDMClient:
    """
    XBDM protocol client for reading Xbox memory.

    Protocol basics:
    - Connect to port 731
    - Server sends "201- connected\\r\\n" banner
    - Send commands as text ending with \\r\\n
    - Responses start with status code (2xx = success, 4xx = error)
    - getmem2 returns binary data after status line

    IMPORTANT: Rate limiting is enabled by default to prevent Xemu crashes.
    Rapid memory reads can overwhelm xbdm_gdb_bridge and freeze the emulator.
    """

    DEFAULT_PORT = 731
    RECV_BUFFER = 4096

    # Rate limiting to prevent Xemu crashes
    DEFAULT_READ_DELAY = 0.05  # 50ms between reads (safe default)
    MIN_READ_DELAY = 0.01      # 10ms minimum (risky)

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 5.0,
                 read_delay: float = DEFAULT_READ_DELAY):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.read_delay = max(read_delay, self.MIN_READ_DELAY)
        self._socket: Optional[socket.socket] = None
        self._connected = False
        self._last_read_time: float = 0

    def connect(self) -> bool:
        """Connect to XBDM server and verify connection."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))

            # Read connection banner
            banner = self._recv_line()
            if banner and banner.startswith("201"):
                self._connected = True
                return True
            else:
                print(f"Unexpected banner: {banner}")
                self.disconnect()
                return False

        except socket.error as e:
            print(f"Connection failed: {e}")
            self._socket = None
            return False

    def disconnect(self):
        """Close connection to XBDM server."""
        if self._socket:
            try:
                self._socket.send(b"bye\r\n")
            except:
                pass
            try:
                self._socket.close()
            except:
                pass
            self._socket = None
        self._connected = False

    def _recv_line(self) -> Optional[str]:
        """Receive a single line response (up to \\r\\n)."""
        if not self._socket:
            return None

        data = b""
        while True:
            try:
                chunk = self._socket.recv(1)
                if not chunk:
                    break
                data += chunk
                if data.endswith(b"\r\n"):
                    break
            except socket.timeout:
                break

        return data.decode('ascii', errors='replace').strip() if data else None

    def _send_command(self, command: str) -> XBDMResponse:
        """Send a command and receive text response."""
        if not self._socket or not self._connected:
            return XBDMResponse(0, "Not connected")

        # Send command
        cmd = f"{command}\r\n"
        self._socket.send(cmd.encode('ascii'))

        # Read response line
        response = self._recv_line()
        if not response:
            return XBDMResponse(0, "No response")

        # Parse status code and message
        # Format: "NNN- message" or "NNN message"
        try:
            code = int(response[:3])
            message = response[4:] if len(response) > 4 else ""
            return XBDMResponse(code, message)
        except ValueError:
            return XBDMResponse(0, f"Invalid response: {response}")

    def read_memory(self, address: int, length: int) -> Optional[bytes]:
        """
        Read memory from Xbox using getmem2 command.

        Args:
            address: Xbox memory address to read
            length: Number of bytes to read

        Returns:
            Bytes read, or None on error

        Note:
            Rate limiting is applied to prevent Xemu crashes.
            Adjust read_delay in constructor if needed.
        """
        if not self._socket or not self._connected:
            return None

        # Rate limiting to prevent Xemu crashes
        elapsed = time.time() - self._last_read_time
        if elapsed < self.read_delay:
            time.sleep(self.read_delay - elapsed)
        self._last_read_time = time.time()

        # Send getmem2 command
        cmd = f"getmem2 addr=0x{address:08X} length=0x{length:X}\r\n"
        self._socket.send(cmd.encode('ascii'))

        # Read status line
        status_line = self._recv_line()
        if not status_line:
            return None

        # Check for success (203 = binary response follows)
        if not status_line.startswith("203"):
            # Try getmem (text format) as fallback
            return self._read_memory_text(address, length)

        # Read binary data
        # Note: If XBDM returns 203 but the address is inaccessible,
        # it may send 0 bytes of data. We handle this gracefully.
        data = b""
        remaining = length
        # Use a shorter timeout for the first byte to detect 0-byte responses
        self._socket.settimeout(2.0)
        while remaining > 0:
            try:
                chunk = self._socket.recv(min(remaining, self.RECV_BUFFER))
                if not chunk:
                    break
                data += chunk
                remaining -= len(chunk)
            except socket.timeout:
                break
        # Restore original timeout
        self._socket.settimeout(self.timeout)

        return data if len(data) == length else None

    def _read_memory_text(self, address: int, length: int) -> Optional[bytes]:
        """
        Fallback: read memory using text-format getmem command.

        Some XBDM implementations return hex text instead of binary.
        """
        cmd = f"getmem addr=0x{address:08X} length=0x{length:X}\r\n"
        self._socket.send(cmd.encode('ascii'))

        # Read response
        response = self._recv_line()
        if not response or not response.startswith("200"):
            return None

        # Read hex data lines until we get enough
        hex_data = ""
        while len(hex_data) < length * 2:
            line = self._recv_line()
            if not line or line.startswith("."):  # "." ends multiline
                break
            hex_data += line.replace(" ", "")

        try:
            return bytes.fromhex(hex_data[:length * 2])
        except ValueError:
            return None

    def write_memory(self, address: int, data: bytes) -> bool:
        """
        Write memory to Xbox using setmem command.

        Args:
            address: Xbox memory address to write
            data: Bytes to write

        Returns:
            True on success
        """
        hex_data = data.hex()
        response = self._send_command(f"setmem addr=0x{address:08X} data={hex_data}")
        return response.status_code == 200

    def get_modules(self) -> list:
        """Get list of loaded modules."""
        response = self._send_command("modules")
        if response.status_code != 202:  # Multiline response
            return []

        modules = []
        while True:
            line = self._recv_line()
            if not line or line == ".":
                break
            modules.append(line)

        return modules

    def _recv_multiline(self) -> list:
        """Read multiline response lines until '.' terminator."""
        lines = []
        while True:
            line = self._recv_line()
            if not line or line == ".":
                break
            lines.append(line)
        return lines

    def _parse_kv_line(self, line: str) -> dict:
        """Parse an XBDM key=value response line into a dict.

        Handles formats like:
            name="default.xbe" base=0x00010000 size=0x00371D2C check=0x1234
        """
        result = {}
        i = 0
        while i < len(line):
            # Skip whitespace
            while i < len(line) and line[i] in ' \t':
                i += 1
            if i >= len(line):
                break

            # Read key
            key_start = i
            while i < len(line) and line[i] not in '= \t':
                i += 1
            key = line[key_start:i]

            if i < len(line) and line[i] == '=':
                i += 1  # skip '='
                if i < len(line) and line[i] == '"':
                    # Quoted value
                    i += 1
                    val_start = i
                    while i < len(line) and line[i] != '"':
                        i += 1
                    result[key] = line[val_start:i]
                    if i < len(line):
                        i += 1  # skip closing '"'
                else:
                    # Unquoted value
                    val_start = i
                    while i < len(line) and line[i] not in ' \t':
                        i += 1
                    val = line[val_start:i]
                    # Auto-convert hex integers
                    if val.startswith("0x") or val.startswith("0X"):
                        try:
                            val = int(val, 16)
                        except ValueError:
                            pass
                    else:
                        try:
                            val = int(val)
                        except ValueError:
                            pass
                    result[key] = val
            else:
                # Bare key with no value (flag)
                result[key] = True
            i += 1
        return result

    def walk_memory(self) -> list:
        """Enumerate all committed virtual memory regions.

        Returns list of dicts with keys: base, size, protect.
        Uses the XBDM 'walkmem' command (DmWalkCommittedMemory).
        """
        if not self._socket or not self._connected:
            return []

        # Rate limit
        elapsed = time.time() - self._last_read_time
        if elapsed < self.read_delay:
            time.sleep(self.read_delay - elapsed)
        self._last_read_time = time.time()

        response = self._send_command("walkmem")
        if response.status_code != 202:
            return []

        regions = []
        for line in self._recv_multiline():
            parsed = self._parse_kv_line(line)
            if parsed:
                regions.append(parsed)
        return regions

    def get_module_sections(self, module_name: str) -> list:
        """Get sections (.text, .data, etc.) for a loaded module.

        Args:
            module_name: Module name (e.g., "default.xbe")

        Returns list of dicts with keys like: name, base, size, index, flags.
        """
        if not self._socket or not self._connected:
            return []

        elapsed = time.time() - self._last_read_time
        if elapsed < self.read_delay:
            time.sleep(self.read_delay - elapsed)
        self._last_read_time = time.time()

        response = self._send_command(f'modsections name="{module_name}"')
        if response.status_code != 202:
            return []

        sections = []
        for line in self._recv_multiline():
            parsed = self._parse_kv_line(line)
            if parsed:
                sections.append(parsed)
        return sections

    def set_breakpoint(self, address: int) -> bool:
        """
        Set a breakpoint at the given address.

        Args:
            address: Xbox memory address for the breakpoint

        Returns:
            True if the breakpoint was set successfully
        """
        if not self._socket or not self._connected:
            return False

        # Rate limit
        elapsed = time.time() - self._last_read_time
        if elapsed < self.read_delay:
            time.sleep(self.read_delay - elapsed)
        self._last_read_time = time.time()

        response = self._send_command(f"break addr=0x{address:08X}")
        return response.status_code == 200

    def clear_breakpoint(self, address: int) -> bool:
        """
        Clear a breakpoint at the given address.

        Args:
            address: Xbox memory address of the breakpoint to clear

        Returns:
            True if the breakpoint was cleared successfully
        """
        if not self._socket or not self._connected:
            return False

        # Rate limit
        elapsed = time.time() - self._last_read_time
        if elapsed < self.read_delay:
            time.sleep(self.read_delay - elapsed)
        self._last_read_time = time.time()

        response = self._send_command(f"break addr=0x{address:08X} clear")
        return response.status_code == 200

    def clear_all_breakpoints(self) -> bool:
        """
        Clear all breakpoints.

        Returns:
            True if all breakpoints were cleared successfully
        """
        if not self._socket or not self._connected:
            return False

        # Rate limit
        elapsed = time.time() - self._last_read_time
        if elapsed < self.read_delay:
            time.sleep(self.read_delay - elapsed)
        self._last_read_time = time.time()

        response = self._send_command("break clearall")
        return response.status_code == 200

    def continue_execution(self) -> bool:
        """
        Resume execution after a breakpoint hit.

        XBDM uses the 'go' command (not 'continue') to resume.

        Returns:
            True if execution was resumed successfully
        """
        if not self._socket or not self._connected:
            return False

        # Rate limit
        elapsed = time.time() - self._last_read_time
        if elapsed < self.read_delay:
            time.sleep(self.read_delay - elapsed)
        self._last_read_time = time.time()

        response = self._send_command("go")
        return response.status_code == 200

    def continue_thread(self, thread_id: int) -> bool:
        """
        Resume a specific thread stopped by a breakpoint.

        Per Xbox SDK (DmContinueThread), threads stopped by breakpoints
        will not resume after 'go' unless 'continue thread=N' is called first.

        Args:
            thread_id: Thread ID from breakpoint notification

        Returns:
            True if the command succeeded
        """
        if not self._socket or not self._connected:
            return False

        elapsed = time.time() - self._last_read_time
        if elapsed < self.read_delay:
            time.sleep(self.read_delay - elapsed)
        self._last_read_time = time.time()

        response = self._send_command(f"continue thread={thread_id}")
        return response.status_code == 200

    def debug_info(self) -> dict:
        """Get debug information from Xbox."""
        response = self._send_command("dmversion")
        return {
            "status": response.status_code,
            "version": response.message
        }

    @property
    def is_connected(self) -> bool:
        return self._connected

    def scan_memory(self, start_addr: int, end_addr: int, chunk_size: int = 256,
                    delay_per_chunk: float = 0.1) -> bytes:
        """
        Scan a memory range safely with rate limiting.

        Args:
            start_addr: Starting address
            end_addr: Ending address
            chunk_size: Bytes per read (smaller = slower but safer)
            delay_per_chunk: Seconds to wait between chunks

        Returns:
            All bytes read (may be incomplete on error)

        Note:
            This method is designed for safe scanning without crashing Xemu.
            For faster scanning, reduce delay_per_chunk (at risk of crashes).
        """
        result = b""
        addr = start_addr
        total = end_addr - start_addr
        read_count = 0

        while addr < end_addr:
            length = min(chunk_size, end_addr - addr)
            data = self.read_memory(addr, length)

            if data:
                result += data
                read_count += 1

                # Progress indicator every 10 reads
                if read_count % 10 == 0:
                    progress = (addr - start_addr) / total * 100
                    print(f"  Scan progress: {progress:.1f}% (0x{addr:08X})")
            else:
                # Fill with zeros on read failure
                result += b'\x00' * length

            addr += length

            # Extra delay for scanning (in addition to per-read delay)
            if delay_per_chunk > self.read_delay:
                time.sleep(delay_per_chunk - self.read_delay)

        return result


class XBDMNotificationListener:
    """
    Listens for XBDM async notifications (breakpoints, etc.)

    Uses a separate TCP connection. When a breakpoint fires,
    XBDM sends a notification message to all registered listeners.

    Usage:
        listener = XBDMNotificationListener('172.20.0.51')
        if listener.connect():
            # ... set breakpoints on main XBDMClient ...
            event = listener.wait_for_notification(timeout=300)
            if event and 'break' in event.lower():
                # breakpoint fired, read stats
                pass
            listener.close()
    """

    def __init__(self, host: str, port: int = 731, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._connected = False

    def _recv_line(self) -> Optional[str]:
        """Receive a single line response (up to \\r\\n)."""
        if not self._socket:
            return None

        data = b""
        while True:
            try:
                chunk = self._socket.recv(1)
                if not chunk:
                    break
                data += chunk
                if data.endswith(b"\r\n"):
                    break
            except socket.timeout:
                break

        return data.decode('ascii', errors='replace').strip() if data else None

    def _send_command(self, command: str) -> XBDMResponse:
        """Send a command and receive text response."""
        if not self._socket or not self._connected:
            return XBDMResponse(0, "Not connected")

        cmd = f"{command}\r\n"
        self._socket.send(cmd.encode('ascii'))

        response = self._recv_line()
        if not response:
            return XBDMResponse(0, "No response")

        try:
            code = int(response[:3])
            message = response[4:] if len(response) > 4 else ""
            return XBDMResponse(code, message)
        except ValueError:
            return XBDMResponse(0, f"Invalid response: {response}")

    def connect(self) -> bool:
        """
        Connect to XBDM and register for async notifications.

        Opens a separate TCP connection, reads the 201 banner,
        then sends the 'notifyat' command to register this socket
        as a notification channel.

        Returns:
            True if connected and registered successfully
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))

            # Read 201 connection banner
            banner = self._recv_line()
            if not banner or not banner.startswith("201"):
                print(f"Unexpected banner: {banner}")
                self.close()
                return False

            self._connected = True

            # Register for notifications
            # notifyat tells XBDM to send async events to this connection
            # CerbiosDebug returns 205 ("now a notification channel") on success
            response = self._send_command(f"notifyat port={self.port}")
            if response.status_code not in (200, 205):
                # Some XBDM implementations use "notify" instead
                response = self._send_command("notify")
                if response.status_code not in (200, 205):
                    print(f"Failed to register for notifications: "
                          f"{response.status_code} {response.message}")
                    self.close()
                    return False

            return True

        except socket.error as e:
            print(f"Notification listener connection failed: {e}")
            self._socket = None
            self._connected = False
            return False

    def wait_for_notification(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Block until a notification arrives or timeout expires.

        Uses select() for reliable blocking instead of relying on socket
        timeout alone, which can spin-loop when the connection degrades
        (_recv_line returns None instantly instead of blocking).

        Args:
            timeout: Seconds to wait, or None for the default timeout.
                     Use a large value (e.g. 300) for long waits.

        Returns:
            The notification text string, or None on timeout/error
        """
        if not self._socket or not self._connected:
            return None

        wait_timeout = timeout if timeout is not None else self.timeout

        # Use select() for reliable blocking — prevents spin-loop when
        # connection degrades (recv returns empty bytes instantly)
        try:
            readable, _, _ = select.select([self._socket], [], [], wait_timeout)
        except (OSError, ValueError):
            self._connected = False
            return None

        if not readable:
            return None  # Clean timeout, no data

        # Data available — read with a short timeout as safety net
        self._socket.settimeout(2.0)
        try:
            line = self._recv_line()
            if line is None:
                self._connected = False  # Connection dead
            return line
        except socket.timeout:
            return None
        finally:
            self._socket.settimeout(self.timeout)

    def wait_for_notifications(self, timeout: Optional[float] = None,
                                max_events: int = 0) -> List[str]:
        """
        Collect multiple notifications until timeout or max_events reached.

        Useful when a single breakpoint hit may produce multiple notification
        lines, or when waiting for several events.

        Args:
            timeout: Total seconds to collect events (None = default timeout)
            max_events: Stop after this many events (0 = no limit, collect until timeout)

        Returns:
            List of notification text strings received
        """
        if not self._socket or not self._connected:
            return []

        wait_timeout = timeout if timeout is not None else self.timeout
        deadline = time.time() + wait_timeout
        events = []

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break

            self._socket.settimeout(remaining)
            try:
                line = self._recv_line()
                if line:
                    events.append(line)
                    if max_events > 0 and len(events) >= max_events:
                        break
                else:
                    # Connection closed or empty read
                    break
            except socket.timeout:
                break

        # Restore default timeout
        self._socket.settimeout(self.timeout)
        return events

    def close(self):
        """Unregister from notifications and close the connection."""
        if self._socket:
            if self._connected:
                try:
                    self._socket.send(b"bye\r\n")
                except socket.error:
                    pass
            try:
                self._socket.close()
            except socket.error:
                pass
            self._socket = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


def test_connection(host: str, port: int = 731) -> bool:
    """Quick test to verify XBDM connectivity."""
    client = XBDMClient(host, port, timeout=3.0)
    if client.connect():
        info = client.debug_info()
        print(f"Connected to XBDM: {info}")
        client.disconnect()
        return True
    return False


if __name__ == "__main__":
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    print(f"Testing XBDM connection to {host}:731...")

    if test_connection(host):
        print("Success!")
    else:
        print("Failed to connect")
