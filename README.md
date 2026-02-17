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

Add your Xbox files to `services/xemu/data/emulator/`:
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
- **Web UI:** `https://172.20.0.49:3001`
- **XLink Kai:** `http://172.20.0.25:34522`

---

## Network Architecture

```
Your Windows PC/Mac (Tailscale client)
  ↓ Encrypted WireGuard tunnel
  ↓
VPS: Docker Network 172.20.0.0/24
  ├── .10 Tailscale (subnet router)
  ├── .25 XLink Kai
  ├── .2  DHCP/DNS
  ├── .49 xemu container → pcap injects .50/.51
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
| [services/xemu/Dockerfile](services/xemu/Dockerfile) | Minimal overlay (wmctrl, ethtool) |
| [docker-compose.yml](docker-compose.yml) | 4-service stack (xemu, xlinkkai, tailscale, dhcp) |
| [services/xemu/data/emulator/xemu.toml](services/xemu/data/emulator/xemu.toml) | xemu config (backend=pcap) |
| [services/xemu/data/emulator/pcap_immediate.c](services/xemu/data/emulator/pcap_immediate.c) | Immediate mode fix |
| [services/xemu/init/10-xemu-setcap](services/xemu/init/10-xemu-setcap) | Runtime capability setup |
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
- **Host OS:** Linux (tested on Ubuntu 22.04+)
- **Memory:** 2GB+ RAM for xemu container
- **Network:** Static IPs in 172.20.0.0/24 range must be available

**Note:** This setup requires a Linux host. Windows/Mac Docker Desktop uses a Linux VM internally, but pcap bridging may not work correctly.

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
