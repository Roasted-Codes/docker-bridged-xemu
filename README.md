# docker-bridged-xemu

**Web-based Xbox debug kit with true bridged networking and remote access.**

Run xemu (original Xbox emulator) with real pcap-based networking that gives the emulated Xbox actual IP addresses on your Docker network. Access FTP, XBDM debugging, and the web UI remotely via Tailscale—no SSH tunnels or SOCKS proxies needed.

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)

---

## What This Does

- **Real bridged networking** via pcap packet injection (Xbox gets 172.20.0.50/51 IPs)
- **FTP access** to Xbox hard drive at 172.20.0.50:21
- **XBDM debugging** on port 731 for Assembly, Cxbx-Reloaded, etc.
- **Tailscale subnet routing** for direct remote access from any device
- **Web-based interface** via Selkies (gamepad passthrough works!)
- **XLink Kai** for online system link gaming
- **CPU-only rendering** (no GPU required)

Minimal overlay on [linuxserver/docker-xemu](https://github.com/linuxserver/docker-xemu) — automatically stays up to date with upstream xemu releases.

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Xbox BIOS files (mcpx_1.0.bin, BIOS, EEPROM)
- Xbox HDD image (qcow2 format)
- Tailscale account (free for personal use)

### 1. Clone and Configure

```bash
git clone https://github.com/Roasted-Codes/docker-bridged-xemu.git
cd docker-bridged-xemu
```

Add your Xbox files to `config/emulator/`:
- `mcpx_1.0.bin` - Boot ROM
- `CerbiosDebug_old.bin` - BIOS (or your preferred BIOS)
- `iguana-eeprom.bin` - EEPROM
- `iguana-dev.qcow2` - HDD image

### 2. Build and Start

```bash
docker compose build
docker compose up -d
```

### 3. Authenticate Tailscale

```bash
# Watch logs for auth URL
docker logs xemu-tailscale

# Visit the URL and log in
# Then approve the 172.20.0.0/24 subnet route in Tailscale admin console
```

### 4. Access Your Xbox

**From any device on your Tailscale network:**

- **XBDM (Assembly):** Connect to `172.20.0.51:731`
- **FTP (FileZilla):** `172.20.0.50:21` (user: xbox, pass: xbox)
- **Web UI:** `https://172.20.0.10:3001`
- **XLink Kai:** `http://172.20.0.20:34522`

---

## First-Time Setup Details

### Which Files Are Included?

This repository includes the Xbox BIOS files and startup configuration:

| File | Included? | Notes |
|------|-----------|-------|
| `mcpx_1.0.bin` | ✅ Yes | Xbox bootloader |
| `Complex_4627.bin` | ✅ Yes | Xbox kernel |
| `iguana-eeprom.bin` | ✅ Yes | Xbox EEPROM (factory default) |
| `iguana-dev.qcow2` | ❌ No | **You must provide an HDD image** |
| `*.iso` game files | ❌ No | **You must provide your own games** |

**Good news:** The hard disk image can be auto-created by xemu if missing. See below.

### Getting a Hard Disk Image

**Option 1: Use an existing HDD image (Recommended)**

If you have a pre-built Xbox HDD image (from another xemu install or extracted from hardware):

```bash
cp /path/to/your/xbox-hdd.qcow2 config/emulator/iguana-dev.qcow2
```

**Option 2: Create a blank HDD on first run**

If the `iguana-dev.qcow2` file is missing, xemu will create a blank HDD when it starts. You'll need to:

1. Start the containers: `docker compose up -d`
2. Access xemu via VNC or Selkies web UI
3. Complete the Xbox dashboard setup
4. Reboot when finished

The HDD image persists in `config/emulator/iguana-dev.qcow2` for future runs.

### Adding Games

Place Xbox game ISO files in the `config/games/` directory:

```bash
mkdir -p config/games
cp /path/to/game.iso config/games/
```

**To load a game:**

1. **Via xemu UI:** Machine → Load Disc → browse to `/config/games/` and select your game
2. **Via config file:** Edit `config/emulator/xemu.toml` and set:
   ```toml
   dvd_path = '/config/games/your-game.iso'
   ```

### What Gets Built Automatically?

On the first run, the container init scripts will:

✅ Compile `pcap_immediate.so` (fixes Xbox packet reception)
✅ Set up network capabilities for xemu
✅ Disable TX checksum offloading (fixes TCP connections)
✅ Create runtime directories for xemu config
✅ Register the pcap shim with the system loader

**You don't need to manually compile anything!** All required libraries and fixes are applied automatically.

### Verifying Everything Works

After running `docker compose up -d`, verify:

```bash
# Check that xemu started without errors
docker compose logs xemu | head -20

# Check that pcap immediate mode is loaded
docker exec xemu-halo2-server cat /etc/ld.so.preload

# Verify TX checksum offloading is disabled (critical for TCP)
docker exec xemu-halo2-server ethtool -k eth0 | grep tx-checksumming
# Should show: tx-checksumming: off
```

If the logs are clean and the checksum offload is disabled, your setup is working correctly!

### Troubleshooting First-Time Setup

**xemu crashes on startup:**
- Check that `config/emulator/` has BIOS files (they're included in the repo)
- Check container logs: `docker compose logs xemu`

**Can access xemu but XBDM won't connect (172.20.0.51:731):**
- This likely indicates checksum offloading wasn't disabled
- Verify: `docker exec xemu-halo2-server ethtool -k eth0 | grep tx-checksumming`
- Should show `tx-checksumming: off`
- If not, the init script may have failed - check full logs with `docker compose logs xemu`

**pcap_immediate.so compilation failed:**
- Check if gcc is installed in the container
- Check container logs: `docker compose logs xemu | grep -i "gcc\|compile"`

**Still having issues?**
- Check [CLAUDE.md](CLAUDE.md) for the full technical troubleshooting guide

---

## Network Architecture

```
Your Windows PC/Mac (Tailscale client)
  ↓ Encrypted WireGuard tunnel
  ↓
VPS: Docker Network 172.20.0.0/24
  ├── .4  Tailscale (subnet router)
  ├── .10 xemu container → pcap injects .50/.51
  ├── .20 XLink Kai
  ├── .2  DHCP/DNS
  └── .50/.51 Xbox (pcap-injected IPs)
```

**No SSH tunnels. No SOCKS proxies. Direct access.**

---

## The 3 Critical Bugs (Solved)

This project solves three non-obvious bugs that break pcap-based Xbox emulation in Docker:

### 1. libpcap Immediate Mode
**Problem:** xemu can send packets but never receives (pcap fd never becomes readable)
**Fix:** [pcap_immediate.c](config/emulator/pcap_immediate.c) - LD_PRELOAD shim that intercepts `pcap_open_live()` and adds immediate mode

### 2. TX Checksum Offloading
**Problem:** Ping works, TCP times out (kernel writes placeholder checksums)
**Fix:** `ethtool -K eth0 tx off` in both xemu and Tailscale containers

### 3. Bridge Hairpin Mode
**Problem:** Containers can't reach pcap-injected IPs on the same bridge port
**Solution:** Tailscale bypasses this entirely; fallback xbdm-relay container available if needed

See [CLAUDE.md](CLAUDE.md) for full technical details.

---

## Key Files

| File | Purpose |
|------|---------|
| [Dockerfile](Dockerfile) | Minimal overlay (wmctrl, ethtool) |
| [docker-compose.yml](docker-compose.yml) | 4-service stack (xemu, xlinkkai, tailscale, dhcp) |
| [config/emulator/xemu.toml](config/emulator/xemu.toml) | xemu config (backend=pcap) |
| [config/emulator/pcap_immediate.c](config/emulator/pcap_immediate.c) | Immediate mode fix |
| [config/custom-cont-init.d/10-xemu-setcap](config/custom-cont-init.d/10-xemu-setcap) | Runtime capability setup |
| [CLAUDE.md](CLAUDE.md) | Comprehensive technical guide |

---

## Common Tasks

### Rebuild After Changes
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

### View Logs
```bash
docker compose logs -f xemu       # Watch xemu logs
docker logs xemu-tailscale        # Check Tailscale auth
```

### Debug Networking
```bash
# Check pcap immediate mode shim
docker exec xemu-halo2-server cat /etc/ld.so.preload

# Check TX offload disabled
docker exec xemu-halo2-server ethtool -k eth0 | grep tx-checksumming

# Capture Xbox traffic
docker exec xemu-halo2-server tcpdump -i eth0 host 172.20.0.50
```

### Access FTP from Server Terminal
```bash
docker exec -it xemu-halo2-server bash
lftp 172.20.0.50
```

---

## What's Different from Upstream?

This fork adds:
- **Bridged pcap networking** with immediate mode fix
- **Tailscale integration** for remote access
- **TX checksum offload fixes** for both xemu and Tailscale
- **Custom init scripts** for setcap and library registration
- **XLink Kai integration** for online gaming
- **Window automation tools** (wmctrl)

We maintain a **minimal overlay** on linuxserver/docker-xemu. The base image is pulled from upstream, so you get automatic xemu updates without maintenance burden.

---

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Comprehensive technical guide (architecture, constraints, troubleshooting)

---

## System Requirements

- **Docker:** 20.10+ with Compose V2
- **Memory:** 2GB+ RAM for xemu container
- **Disk:** 8GB+ for Xbox HDD image and games

### Supported Platforms

| Platform | Support | Notes |
|----------|---------|-------|
| **Linux** | ✅ Full | Ubuntu 22.04+, Debian 11+, Fedora 35+ |
| **Windows (WSL2)** | ✅ Full | Native Docker in WSL2 (not Docker Desktop) |
| **macOS** | ❌ No | Docker Desktop on Mac cannot access pcap |
| **Windows (Docker Desktop)** | ❌ No | Cannot access pcap; use WSL2 instead |

### Why WSL2 Works, Docker Desktop Doesn't

- **WSL2 with native Docker**: Direct access to Linux network interfaces → pcap works
- **Docker Desktop (Windows/Mac)**: Runs in isolated VM → pcap cannot access real networks

For macOS, you'd need a remote Linux server or Ubuntu VM.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| xemu won't start | Missing BIOS/HDD files | Check `config/emulator/` for required files |
| Can send but not receive | Immediate mode not enabled | Check `/etc/ld.so.preload` has pcap_immediate.so |
| Ping works, TCP fails | Bad checksums | Verify `ethtool -K eth0 tx off` in both containers |
| XBDM not reachable | Tailscale route not approved | Check Tailscale admin console |
| Gamepad not working | Selkies not loaded | Check `/etc/ld.so.preload` has all 3 .so files |

See [CLAUDE.md](CLAUDE.md) for complete troubleshooting guide.

---

## Contributing

This is a specialized setup for running Xbox debug environments remotely. If you find bugs or have improvements:

1. Check [CLAUDE.md](CLAUDE.md) to understand the architecture
2. Test thoroughly (the 3 bugs are subtle!)
3. Open an issue or PR

---

## License

GPL-3.0 - See [LICENSE](LICENSE)

Based on [linuxserver/docker-xemu](https://github.com/linuxserver/docker-xemu) (GPL-3.0)

---

## Links

- **Issues:** [github.com/Roasted-Codes/docker-bridged-xemu/issues](https://github.com/Roasted-Codes/docker-bridged-xemu/issues)
- **xemu:** [xemu.app](https://xemu.app)
- **XLink Kai:** [teamxlink.co.uk](https://www.teamxlink.co.uk)
- **Tailscale:** [tailscale.com](https://tailscale.com)
- **LinuxServer.io:** [linuxserver.io](https://linuxserver.io)

---

## Acknowledgments

- **LinuxServer.io** - Base xemu Docker image
- **xemu project** - Original Xbox emulation
- **Tailscale** - Zero-config VPN that makes remote access possible
- Everyone who contributed to solving the pcap networking bugs
