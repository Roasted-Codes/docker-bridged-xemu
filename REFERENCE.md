# docker-bridged-xemu: Quick Reference

**Xbox emulator with real bridged networking via pcap**

[GitHub: Roasted-Codes/docker-bridged-xemu](https://github.com/Roasted-Codes/docker-bridged-xemu) | License: GPL-3.0

---

## What This Is

4-container Docker stack that runs xemu (Xbox emulator) with true bridged networking. The emulated Xbox gets real IPs (172.20.0.50/51) via pcap packet injection, enabling:
- FTP access to Xbox HDD
- XBDM debugging (port 731)
- XLink Kai online gaming
- Real LAN presence for system link games

**Base:** LinuxServer.io's xemu image + minimal overlay (wmctrl, custom scripts)

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

# Access web UI
open https://localhost:3000
```

**Network IPs:**
- `172.20.0.10` - xemu container
- `172.20.0.50` - Xbox title interface (FTP, games)
- `172.20.0.51` - Xbox debug interface (XBDM)

---

## The 3 Critical Bugs (and Fixes)

### 1. libpcap Immediate Mode
**Problem:** xemu can send but never receives packets (pcap fd never becomes readable)
**Fix:** [pcap_immediate.c](config/emulator/pcap_immediate.c) - LD_PRELOAD shim intercepts `pcap_open_live()` and adds `pcap_set_immediate_mode(1)`
**Applied by:** [10-xemu-setcap](config/custom-cont-init.d/10-xemu-setcap) writes to `/etc/ld.so.preload`

### 2. TX Checksum Offloading
**Problem:** Ping works, TCP times out (bad checksums on software bridge)
**Fix:** `ethtool -K eth0 tx off` forces software checksum computation
**Applied by:** [10-xemu-setcap](config/custom-cont-init.d/10-xemu-setcap) and xbdm-relay container

### 3. Bridge Hairpin Mode
**Problem:** socat in xemu container can't reach Xbox IPs (same bridge port)
**Fix:** Separate [xbdm-relay container](docker-compose.yml) on different bridge port (172.20.0.3)
**Why:** Docker bridge hairpin disabled by default, can't be enabled from container

---

## Key Files

| File | Purpose |
|------|---------|
| [Dockerfile](Dockerfile) | Adds wmctrl, copies autostart (21 lines) |
| [docker-compose.yml](docker-compose.yml) | 4 services: xemu, xlinkkai, xbdm-relay, dhcp |
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

### Access Xbox FTP
```bash
# From xemu container terminal
lftp 172.20.0.50

# From host (requires SSH SOCKS proxy)
ssh -D 1080 user@remote-host
# Configure FileZilla: SOCKS5 proxy localhost:1080
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

# Check TX offload (should be off)
docker exec xemu-halo2-server ethtool -k eth0 | grep tx-checksumming
# Should show: tx-checksumming: off

# Capture Xbox traffic
docker exec xemu-halo2-server tcpdump -i eth0 host 172.20.0.50
```

### Rebuild pcap_immediate.so
```bash
docker exec xemu-halo2-server bash -c \
    'gcc -shared -fPIC -o /config/emulator/pcap_immediate.so /config/emulator/pcap_immediate.c -ldl'
docker compose restart xemu
```

### Git Push
```bash
cd /home/docker/bridged-xemu
git add .
git commit -m "Your message

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
git push origin main
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| xemu won't start | Missing BIOS/HDD files | Check `config/emulator/` for required files |
| Can send but not receive packets | Immediate mode not enabled | Rebuild pcap_immediate.so, check /etc/ld.so.preload |
| Ping works, TCP times out | Bad checksums | `ethtool -K eth0 tx off` (check if ethtool installed) |
| XBDM relay fails | Hairpin mode | Use separate xbdm-relay container (already in compose) |
| `error loading shared libraries` | setcap stripped LD_LIBRARY_PATH | Check ldconfig ran, /etc/ld.so.conf.d/xemu.conf exists |
| No browser gamepad | Selkies not in /etc/ld.so.preload | Check 10-xemu-setcap wrote all 3 .so files |
| Dashboard boots to wrong HDD | xemu.toml stale path | Edit xemu.toml, set correct hdd_path |

---

## Docker Services

| Service | IP | Ports | Purpose |
|---------|-----|-------|---------|
| xemu | 172.20.0.10 | 3000 (HTTPS), 3001 (VNC) | Emulator with Selkies web UI |
| xlinkkai | 172.20.0.20 | 34522 | Online system link gaming |
| xbdm-relay | 172.20.0.3 | 127.0.0.1:731 | XBDM TCP relay (hairpin fix) |
| dhcp | 172.20.0.2 | 53, 67 (internal) | DHCP/DNS services |
| Xbox (pcap) | 172.20.0.50/51 | 21 (FTP), 731 (XBDM) | Virtual Xbox IPs |

---

## Startup Sequence

1. **s6-overlay runs 01-install-autostart** (root) - Syncs autostart, creates xemu.toml symlink
2. **s6-overlay runs 10-xemu-setcap** (root) - Applies all 3 bug fixes, sets capabilities
3. **Desktop starts, runs autostart** (user abc) - Launches xemu via xterm
4. **xemu boots** - LD_PRELOAD loads pcap fix → Xbox BIOS → Dashboard → Network ready

**Total time:** 35-70 seconds from `docker compose up` to playable Xbox

---

## Critical Constraints

- **Never apply setcap at build time** - Base image updates, runtime only
- **Always pair setcap with ldconfig** - AppImage libs need system registration
- **Always pair setcap with /etc/ld.so.preload** - AT_SECURE strips LD_PRELOAD env var
- **Must use backend = 'pcap'** in xemu.toml - Other backends don't provide real network
- **Must disable TX offload** - ethtool -K eth0 tx off (add ethtool to Dockerfile)
- **xbdm-relay must be separate container** - Hairpin workaround

---

## Architecture Pattern

```
LinuxServer xemu base (maintained upstream)
    ↓
+ Dockerfile: wmctrl package, autostart
    ↓
+ Volume mounts: init scripts, config, pcap shim
    ↓
docker-bridged-xemu (minimal overlay, auto-updates)
```

**Benefit:** Upstream security patches and xemu updates without maintenance burden

---

## Directory Structure

```
bridged-xemu/
├── Dockerfile                       # Minimal overlay
├── docker-compose.yml               # 4-service stack
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

## Related Documentation

- **[CLAUDE.md](CLAUDE.md)** - Comprehensive technical guide (991 lines, all details)
- **[FTP-Fix.md](FTP-Fix.md)** - Detailed FTP access guide with diagrams
- **[README.md](README.md)** - Original quick start (STALE, needs update)
- **[CHANGELOG.md](CHANGELOG.md)** - Version history (STALE, needs update)

---

## Getting Help

- **Issues:** https://github.com/Roasted-Codes/docker-bridged-xemu/issues
- **xemu upstream:** https://xemu.app
- **XLink Kai:** https://www.teamxlink.co.uk
- **LinuxServer base:** https://github.com/linuxserver/docker-xemu
