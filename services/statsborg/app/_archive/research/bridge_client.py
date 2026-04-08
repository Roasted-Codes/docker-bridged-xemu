"""
xbdm_gdb_bridge Client - Interface to xbdm_gdb_bridge shell

Instead of connecting directly to XBDM (which may conflict with the bridge or
cause freezes), this module spawns xbdm_gdb_bridge as a subprocess and sends
commands through its shell interface.

This is the recommended approach for reading Xbox memory when using Xemu.
"""

import subprocess
import re
import time
from typing import Optional, List, Tuple
from dataclasses import dataclass
import os


@dataclass
class MemoryReadResult:
    """Result of a memory read operation"""
    success: bool
    data: Optional[bytes] = None
    error: Optional[str] = None
    raw_output: str = ""


class BridgeClient:
    """
    Client that interfaces with xbdm_gdb_bridge via subprocess.

    Usage:
        client = BridgeClient("/path/to/xbdm_gdb_bridge", "192.168.1.100")
        client.start()
        data = client.read_memory(0x55CAF0, 64)
        client.stop()
    """

    def __init__(self, bridge_path: str, xbox_ip: str, xbox_port: int = 731):
        self.bridge_path = bridge_path
        self.xbox_ip = xbox_ip
        self.xbox_port = xbox_port
        self._process: Optional[subprocess.Popen] = None
        self._connected = False

    def start(self, timeout: float = 10.0) -> bool:
        """Start xbdm_gdb_bridge and wait for connection."""
        if self._process:
            return True

        try:
            xbox_addr = f"{self.xbox_ip}:{self.xbox_port}"
            self._process = subprocess.Popen(
                [self.bridge_path, xbox_addr, "-s"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )

            # Wait for the shell prompt
            # The bridge shows a prompt when ready
            start = time.time()
            while time.time() - start < timeout:
                if self._process.poll() is not None:
                    # Process exited
                    stderr = self._process.stderr.read() if self._process.stderr else ""
                    print(f"Bridge exited unexpectedly: {stderr}")
                    return False

                # Check if there's output (shell prompt)
                # This is tricky without select() on Windows
                time.sleep(0.5)
                self._connected = True
                return True

        except FileNotFoundError:
            print(f"Bridge executable not found: {self.bridge_path}")
            return False
        except Exception as e:
            print(f"Failed to start bridge: {e}")
            return False

        return False

    def stop(self):
        """Stop xbdm_gdb_bridge."""
        if self._process:
            try:
                self._process.stdin.write("quit\n")
                self._process.stdin.flush()
                self._process.wait(timeout=5.0)
            except:
                self._process.kill()
            self._process = None
        self._connected = False

    def _send_command(self, command: str, timeout: float = 5.0) -> str:
        """Send a command and read the response."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return ""

        try:
            self._process.stdin.write(command + "\n")
            self._process.stdin.flush()

            # Read response until we get a prompt or timeout
            # This is simplified - a real implementation would need
            # proper async I/O or threading
            output = []
            start = time.time()

            while time.time() - start < timeout:
                line = self._process.stdout.readline()
                if not line:
                    break
                output.append(line)
                # Look for end of output (command prompt or empty line)
                if line.strip() == "" or ">" in line:
                    break

            return "".join(output)

        except Exception as e:
            return f"Error: {e}"

    def read_memory(self, address: int, length: int) -> MemoryReadResult:
        """
        Read memory using the bridge's getmem command.

        Args:
            address: Memory address to read
            length: Number of bytes to read

        Returns:
            MemoryReadResult with parsed data
        """
        command = f"getmem 0x{address:08X} {length}"
        output = self._send_command(command)

        if not output or "Error" in output or "error" in output:
            return MemoryReadResult(
                success=False,
                error=output or "No response",
                raw_output=output
            )

        # Parse hex output
        # Format: "XX XX XX XX ..." (space-separated hex bytes)
        try:
            hex_values = re.findall(r'[0-9a-fA-F]{2}', output)
            if hex_values:
                data = bytes(int(h, 16) for h in hex_values[:length])
                return MemoryReadResult(
                    success=True,
                    data=data,
                    raw_output=output
                )
        except Exception as e:
            return MemoryReadResult(
                success=False,
                error=str(e),
                raw_output=output
            )

        return MemoryReadResult(
            success=False,
            error="Failed to parse output",
            raw_output=output
        )

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process is not None


def run_single_command(bridge_path: str, xbox_ip: str, command: str) -> str:
    """
    Run a single command via xbdm_gdb_bridge and return output.

    This spawns the bridge, runs the command, and exits.
    Useful for one-off memory reads.
    """
    xbox_addr = f"{xbox_ip}:731"

    try:
        result = subprocess.run(
            [bridge_path, xbox_addr, command],
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except FileNotFoundError:
        return f"Error: Bridge not found at {bridge_path}"
    except Exception as e:
        return f"Error: {e}"


def read_memory_once(bridge_path: str, xbox_ip: str, address: int, length: int) -> Optional[bytes]:
    """
    Convenience function to read memory with a single command invocation.

    Args:
        bridge_path: Path to xbdm_gdb_bridge executable
        xbox_ip: IP address of Xbox/Xemu
        address: Memory address to read
        length: Number of bytes

    Returns:
        Bytes read, or None on error
    """
    command = f"getmem 0x{address:08X} {length}"
    output = run_single_command(bridge_path, xbox_ip, command)

    if output.startswith("Error"):
        print(output)
        return None

    # Parse hex output
    try:
        hex_values = re.findall(r'[0-9a-fA-F]{2}', output)
        if hex_values:
            return bytes(int(h, 16) for h in hex_values[:length])
    except Exception as e:
        print(f"Parse error: {e}")

    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("Usage: bridge_client.py <bridge_path> <xbox_ip> <address> [length]")
        print("Example: bridge_client.py ./xbdm_gdb_bridge 192.168.1.100 0x55CAF0 64")
        sys.exit(1)

    bridge = sys.argv[1]
    ip = sys.argv[2]
    addr = int(sys.argv[3], 0)  # Auto-detect hex or decimal
    length = int(sys.argv[4]) if len(sys.argv) > 4 else 64

    print(f"Reading {length} bytes from 0x{addr:08X}...")
    data = read_memory_once(bridge, ip, addr, length)

    if data:
        # Print as hex dump
        for i in range(0, len(data), 16):
            hex_part = " ".join(f"{b:02X}" for b in data[i:i+16])
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i:i+16])
            print(f"{addr+i:08X}  {hex_part:<48}  {ascii_part}")
    else:
        print("Failed to read memory")
