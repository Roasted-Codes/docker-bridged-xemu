# docker-bridged-xemu: Quick Reference

**Xbox emulator with real bridged networking via pcap + Tailscale subnet routing**

[GitHub: Roasted-Codes/docker-bridged-xemu](https://github.com/Roasted-Codes/docker-bridged-xemu) | License: GPL-3.0

---

## What This Is

5-container Docker stack that runs xemu (Xbox emulator) with true bridged networking. The emulated Xbox gets real IPs (172.20.0.50/51) via pcap packet injection, plus Tailscale for direct remote access. Enables:
- FTP access to Xbox HDD (direct via Tailscale, no SOCKS proxy)
- XBDM debugging on port 731 (direct via Tailscale, no SSH tunnel)
- XLink Kai online gaming
- Real LAN presence for system link games
- Direct access to entire Docker network from remote clients

**Base:** LinuxServer.io's xemu image + minimal overlay (wmctrl, ethtool, custom scripts)

---

## Quick Start

```bash
# Clone and enter directory
git clone https://github.com/Roasted-Codes/docker-bridged-xemu.git
cd docker-bridged-xemu

# Add your Xbox files to config/emulator/
# - mcpx_1.0.bin (boot ROM)
# - CerbiosDebug_old.bin (BIOS)
# - iguana-eeprom.bin (EEPROM)
# - iguana-dev.qcow2 (HDD image)

# Build and start
docker compose build
docker compose up -d

# Authenticate Tailscale (first run only)
docker logs xemu-tailscale  # Visit auth URL
# Then approve 172.20.0.0/24 route in Tailscale admin console

# Access from Windows PC (via Tailscale)
# Assembly: connect to 172.20.0.51:731
# FileZilla: connect to 172.20.0.50:21
# Browser: https://172.20.0.10:3001
```

**Network IPs:**
- `172.20.0.10` - xemu container (web UI on 3001)
- `172.20.0.50` - Xbox title interface (FTP, games)
- `172.20.0.51` - Xbox debug interface (XBDM)
- `172.20.0.20` - XLink Kai
- `172.20.0.4` - Tailscale (subnet router)
- `172.20.0.2` - DHCP/DNS

---

## The 3 Critical Bugs (and Fixes)

### 1. libpcap Immediate Mode
**Problem:** xemu can send but never receives packets (pcap fd never becomes readable)
**Fix:** [pcap_immediate.c](config/emulator/pcap_immediate.c) - LD_PRELOAD shim intercepts `pcap_open_live()` and adds `pcap_set_immediate_mode(1)`
**Applied by:** [10-xemu-setcap](config/custom-cont-init.d/10-xemu-setcap) writes to `/etc/ld.so.preload`

### 2. TX Checksum Offloading
**Problem:** Ping works, TCP times out (bad checksums on software bridge)
**Fix:** `ethtool -K eth0 tx off` forces software checksum computation
**Applied by:** [10-xemu-setcap](config/custom-cont-init.d/10-xemu-setcap) in xemu container, and Tailscale container entrypoint

### 3. Bridge Hairpin Mode
**Problem:** socat in xemu container can't reach Xbox IPs (same bridge port)
**Original fix:** Separate xbdm-relay container on different bridge port (172.20.0.3)
**Current solution:** Tailscale bypasses the hairpin issue entirely - remote clients access Xbox IPs directly via subnet routing
**Fallback:** xbdm-relay kept commented out in docker-compose.yml for users not using Tailscale

---

## Key Files

| File | Purpose |
|------|---------|
| [Dockerfile](Dockerfile) | Adds wmctrl, ethtool, copies autostart |
| [docker-compose.yml](docker-compose.yml) | 5 services: xemu, xlinkkai, tailscale, dhcp, (xbdm-relay commented) |
| [config/emulator/xemu.toml](config/emulator/xemu.toml) | xemu config (MUST have `backend = 'pcap'`) |
| [config/emulator/pcap_immediate.c](config/emulator/pcap_immediate.c) | LD_PRELOAD shim source (73 lines) |
| [config/custom-cont-init.d/01-install-autostart](config/custom-cont-init.d/01-install-autostart) | Syncs autostart, creates xemu.toml symlink |
| [config/custom-cont-init.d/10-xemu-setcap](config/custom-cont-init.d/10-xemu-setcap) | Applies all 3 bug fixes at runtime |
| [root/defaults/autostart](root/defaults/autostart) | Launches xemu (and optional automation) |
| [config/dnsmasq/dnsmasq.conf](config/dnsmasq/dnsmasq.conf) | DHCP pool, DNS forwarders |

---

## Common Tasks

### Build and Run
```bash
docker compose build --no-cache  # Clean build
docker compose up -d             # Start all services
docker compose logs -f xemu      # Watch logs
docker compose down              # Stop everything
```

### Access Xbox via Tailscale (from Windows PC)
```bash
# XBDM debugging with Assembly
# Set Xbox IP to: 172.20.0.51

# FTP with FileZilla (no SOCKS proxy needed)
# Host: 172.20.0.50
# Port: 21
# User: xbox
# Pass: xbox

# xemu web UI
# Browser: https://172.20.0.10:3001
```

### Access Xbox FTP (from VPS terminal)
```bash
# From xemu container terminal
docker exec -it xemu-halo2-server bash
lftp 172.20.0.50
```

### Debug Network Issues
```bash
# Check capabilities
docker exec xemu-halo2-server getcap /opt/xemu/usr/bin/xemu
# Should show: cap_net_admin,cap_net_raw+eip

# Check promiscuous mode
docker exec xemu-halo2-server ip link show eth0
# Should show: PROMISC

# Check LD_PRELOAD
docker exec xemu-halo2-server cat /etc/ld.so.preload
# Should list pcap_immediate.so

# Check TX offload in xemu container
docker exec xemu-halo2-server ethtool -k eth0 | grep tx-checksumming
# Should show: tx-checksumming: off

# Check TX offload in Tailscale container
docker exec xemu-tailscale ethtool -k eth0 | grep tx-checksumming
# Should show: tx-checksumming: off

# Verify Tailscale subnet route
docker exec xemu-tailscale tailscale status
# Should show 172.20.0.0/24 advertised

# Capture Xbox traffic
docker exec xemu-halo2-server tcpdump -i eth0 host 172.20.0.50
```

### Rebuild pcap_immediate.so
```bash
docker exec xemu-halo2-server bash -c \
    'gcc -shared -fPIC -o /config/emulator/pcap_immediate.so /config/emulator/pcap_immediate.c -ldl'
docker compose restart xemu
```

### Tailscale Re-authentication
```bash
# If Tailscale loses auth (rare, usually persists via volume)
docker exec xemu-tailscale tailscale logout
docker compose restart tailscale
docker logs xemu-tailscale  # Visit new auth URL
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| xemu won't start | Missing BIOS/HDD files | Check `config/emulator/` for required files |
| Can send but not receive packets | Immediate mode not enabled | Rebuild pcap_immediate.so, check /etc/ld.so.preload |
| Ping works, TCP times out (xemu) | Bad checksums | `ethtool -K eth0 tx off` in xemu container (check if ethtool installed) |
| Ping works, TCP times out (Tailscale) | Bad checksums | Verify Tailscale entrypoint has ethtool command |
| XBDM not reachable via Tailscale | Subnet route not approved | Check Tailscale admin console, approve 172.20.0.0/24 |
| Tailscale auth URL keeps changing | Restart loop | Remove `restart: unless-stopped`, authenticate, then re-add |
| `error loading shared libraries` | setcap stripped LD_LIBRARY_PATH | Check ldconfig ran, /etc/ld.so.conf.d/xemu.conf exists |
| No browser gamepad | Selkies not in /etc/ld.so.preload | Check 10-xemu-setcap wrote all 3 .so files |
| Dashboard boots to wrong HDD | xemu.toml stale path | Edit xemu.toml, set correct hdd_path |

---

## Docker Services

| Service | IP | Ports | Purpose |
|---------|-----|-------|---------|
| xemu | 172.20.0.10 | 3000 (HTTP), 3001 (HTTPS) | Emulator with Selkies web UI |
| xlinkkai | 172.20.0.20 | 34522 | Online system link gaming |
| tailscale | 172.20.0.4 | 41641/udp (WireGuard) | Subnet router for remote access |
| dhcp | 172.20.0.2 | 53 (DNS), 67 (DHCP) | DNS forwarding + DHCP pool |
| xbdm-relay* | 172.20.0.3 | 127.0.0.1:731 | *Commented out - fallback if not using Tailscale |
| Xbox (pcap) | 172.20.0.50/51 | 21 (FTP), 731 (XBDM) | Virtual Xbox IPs |

---

## Startup Sequence

1. **s6-overlay runs 01-install-autostart** (root) - Syncs autostart, creates xemu.toml symlink
2. **s6-overlay runs 10-xemu-setcap** (root) - Applies all 3 bug fixes, sets capabilities
3. **Desktop starts, runs autostart** (user abc) - Launches xemu via xterm
4. **xemu boots** - LD_PRELOAD loads pcap fix → Xbox BIOS → Dashboard → Network ready
5. **Tailscale authenticates** (first run) - Visit auth URL, approve subnet route

**Total time:** 35-70 seconds from `docker compose up` to playable Xbox

---

## Critical Constraints

- **Never apply setcap at build time** - Base image updates, runtime only
- **Always pair setcap with ldconfig** - AppImage libs need system registration
- **Always pair setcap with /etc/ld.so.preload** - AT_SECURE strips LD_PRELOAD env var
- **Must use backend = 'pcap'** in xemu.toml - Other backends don't provide real network
- **Must disable TX offload** - Both xemu AND Tailscale containers need `ethtool -K eth0 tx off`
- **Tailscale needs subnet route approval** - Admin console must enable 172.20.0.0/24

---

## Architecture Pattern

```
LinuxServer xemu base (maintained upstream)
    ↓
+ Dockerfile: wmctrl, ethtool, autostart
    ↓
+ Volume mounts: init scripts, config, pcap shim
    ↓
+ Tailscale: subnet routing for remote access
    ↓
docker-bridged-xemu (minimal overlay, auto-updates)
```

**Benefit:** Upstream security patches and xemu updates without maintenance burden

---

## Network Architecture

```
Windows PC (Tailscale client)
  ↓ WireGuard tunnel (encrypted, NAT-traversing)
  ↓
VPS: Docker Network 172.20.0.0/24
  ├── .4  Tailscale (subnet router)
  ├── .10 xemu container → pcap injects .50/.51
  ├── .20 XLink Kai
  ├── .2  DHCP/DNS
  └── .50/.51 Xbox (pcap-injected IPs)

Direct Access from Windows:
  - 172.20.0.51:731 → XBDM (Assembly)
  - 172.20.0.50:21  → FTP (FileZilla)
  - 172.20.0.10:3001 → Web UI
```

---

## Directory Structure

```
bridged-xemu/
├── Dockerfile                       # Minimal overlay
├── docker-compose.yml               # 5-service stack
├── root/defaults/autostart          # Launches xemu
├── config/
│   ├── custom-cont-init.d/          # Runtime init scripts
│   │   ├── 01-install-autostart     # Sync autostart, symlink xemu.toml
│   │   └── 10-xemu-setcap           # Apply 3 bug fixes, set capabilities
│   ├── emulator/                    # xemu files
│   │   ├── xemu.toml                # Config (backend=pcap required)
│   │   ├── pcap_immediate.c         # LD_PRELOAD shim source
│   │   ├── *.bin                    # BIOS files
│   │   └── *.qcow2                  # HDD image (not in git)
│   └── dnsmasq/
│       └── dnsmasq.conf             # DHCP/DNS config
└── .gitignore                       # Excludes *.qcow2, *.iso, *.so
```

---

## What Tailscale Provides

✅ **Direct access** to Xbox IPs (172.20.0.50/51) from Windows PC
✅ **No SSH tunnels** needed for XBDM or web UI
✅ **No SOCKS proxy** needed for FTP
✅ **Encrypted WireGuard tunnel** with NAT traversal
✅ **Zero host firewall changes** - all in Docker
✅ **Fully reproducible** from docker-compose.yml

## What Tailscale Does NOT Replace

- **XLink Kai** - still needed for Layer 2 system link gaming (Tailscale is Layer 3 only)
- **VS Code Remote-SSH** - still used for editing files on the VPS
- **pcap immediate mode shim** - still needed for xemu packet reception
- **TX checksum offloading fix** - still needed in both xemu AND Tailscale containers

---

## Related Documentation

- **[CLAUDE.md](CLAUDE.md)** - Comprehensive technical guide (990+ lines, all details)
- **[FTP-Fix.md](FTP-Fix.md)** - Detailed FTP access guide with diagrams
- **[README.md](README.md)** - Original quick start (STALE, needs update)
- **[CHANGELOG.md](CHANGELOG.md)** - Version history (STALE, needs update)

---

## Getting Help

- **Issues:** https://github.com/Roasted-Codes/docker-bridged-xemu/issues
- **xemu upstream:** https://xemu.app
- **XLink Kai:** https://www.teamxlink.co.uk
- **LinuxServer base:** https://github.com/linuxserver/docker-xemu
- **Tailscale:** https://tailscale.com/kb
