# docker-bridged-xemu

**This file provides guidance to Claude Code (claude.ai/code) when working with this repository.**

**Repository:** [`Roasted-Codes/docker-bridged-xemu`](https://github.com/Roasted-Codes/docker-bridged-xemu)
**Maintainer:** Roasted-Codes
**License:** GPL-3.0

---

## Project Overview

`docker-bridged-xemu` is a **Docker overlay** on top of [`linuxserver/docker-xemu`](https://github.com/linuxserver/docker-xemu) that enables **pcap-based bridged networking** for the emulated Xbox. This allows the emulated Xbox to appear as a real device on a Docker bridge network with its own static IP addresses.

### What This Provides

- **xemu** (Xbox emulator) with pcap backend networking on Docker bridge
- **XLink Kai** for system link gaming over the internet
- **dnsmasq** for DHCP and DNS services on the bridge network
- **xbdm-relay** for accessing Xbox Debug Monitor (XBDM) over TCP port 731
- **Emulated Xbox IPs:** `172.20.0.50` (title interface) and `172.20.0.51` (debug interface)

### Why Overlay Pattern?

This project uses a **minimal overlay** approach instead of forking the entire base image:

- **Base Image:** `lscr.io/linuxserver/xemu:latest` (maintained by LinuxServer.io)
- **Overlay:** Adds `wmctrl`, custom autostart script, and runtime init scripts
- **Benefits:**
  - Automatic upstream updates (xemu version, security patches)
  - Minimal maintenance burden
  - Clear separation between base functionality and custom modifications
  - Small image delta (~10MB of modifications vs. ~3.6GB base image)

### Critical Network Fixes

This project solves **three critical bugs** that prevent xemu from working with pcap networking:

1. **libpcap immediate mode** (CRITICAL): xemu cannot receive packets without `pcap_set_immediate_mode()`. Fixed with LD_PRELOAD shim ([`pcap_immediate.c`](config/emulator/pcap_immediate.c)).

2. **TCP checksum offloading**: Host kernel writes placeholder checksums expecting hardware completion, but pcap-injected IPs go through software bridge. Fixed with `ethtool -K eth0 tx off` in init script.

3. **Bridge hairpin mode**: Containers on the same bridge port cannot reach each other. Fixed with dedicated `xbdm-relay` container on separate bridge port.

---

## Important Constraints ⚠️

**Critical rules for AI agents working with this codebase:**

- **🚨 NEVER push to GitHub without explicit user confirmation first.** Git push is a hard-to-reverse action that affects shared state. Always ask the user before running `git push`. This is non-negotiable - even after committing changes, ALWAYS confirm before pushing.
- **Never apply `setcap` at build time** in the Dockerfile. The xemu binary comes from the base image and changes when upstream updates. `setcap` must be applied at runtime via `10-xemu-setcap` to always target the current binary.
- **Always pair `setcap` with `/etc/ld.so.preload`**. If you apply `setcap` to xemu, you must also write the Selkies interposer to `/etc/ld.so.preload` or browser input will silently break.
- **Always pair `setcap` with `ldconfig`**. The AppImage libraries must be registered system-wide or xemu will fail to start (missing shared libraries).
- **The `custom-cont-init.d` mount must go to `/custom-cont-init.d`** (root), not `/config/custom-cont-init.d`. LinuxServer's s6-overlay only scans the root path.
- **`01-install-autostart` must force-copy autostart every start**. The base image only copies `/defaults/autostart` on first run. Without force-sync, existing containers would use a stale autostart after image updates.
- **`pcap_immediate.so` must be in `/etc/ld.so.preload`**. Without this shim, xemu's pcap backend cannot receive any packets on libpcap >= 1.9 (TPACKET_V3). The shim intercepts `pcap_open_live()` and injects `pcap_set_immediate_mode(1)`. It must intercept `pcap_open_live` (not `pcap_activate`) because xemu's bundled libpcap makes internal calls that bypass the PLT.
- **TX checksum offloading must be disabled on eth0**. Without `ethtool -K eth0 tx off`, all inbound TCP connections to the Xbox (FTP, XBDM) silently fail because the host kernel writes placeholder checksums that never get completed by hardware on the software bridge. ICMP ping still works (kernel computes ICMP checksums in software).

---

## Directory Structure

```
bridged-xemu/
├── Dockerfile                          # Minimal overlay: adds wmctrl, copies autostart
├── docker-compose.yml                  # 4 services: xemu, xlinkkai, xbdm-relay, dhcp
├── LICENSE                             # GPL-3.0
├── README.md                           # Quick start guide
├── CHANGELOG.md                        # Historical change log (STALE - see 2026-02-05-project-review.md)
├── FTP-Fix.md                          # Guide for accessing Xbox FTP via SOCKS proxy or lftp
├── 2026-02-05-project-review.md        # Current project review (identifies stale docs)
├── tailscale-plan.md                   # Future work: Tailscale subnet routing
├── .gitignore                          # Excludes *.qcow2, *.iso, *.so, config runtime dirs
│
├── root/
│   └── defaults/
│       └── autostart                   # Custom startup script (launches xemu in xterm)
│
└── config/                             # Volume-mounted into container at /config
    ├── custom-cont-init.d/             # Root-level init scripts (run before user session)
    │   ├── 01-install-autostart        # Syncs autostart, creates xemu.toml symlink
    │   └── 10-xemu-setcap              # Grants network caps, disables TX checksum, sets ld.so.preload
    │
    ├── emulator/                       # xemu configuration and BIOS files
    │   ├── xemu.toml                   # xemu config (pcap backend, paths, input bindings)
    │   ├── pcap_immediate.c            # LD_PRELOAD shim source code
    │   ├── pcap_immediate.so           # Compiled shim (built inside container, not in git)
    │   ├── mcpx_1.0.bin                # Xbox boot ROM (1MB)
    │   ├── CerbiosDebug_old.bin        # Cerbios BIOS (512KB)
    │   ├── iguana-eeprom.bin           # EEPROM image (256 bytes)
    │   ├── iguana-dev.qcow2            # Xbox HDD image (~3.6GB, NOT in git)
    │   └── passleader_v3.sh.disabled   # Optional automation script (rename to .sh to enable)
    │
    ├── dnsmasq/
    │   └── dnsmasq.conf                # DHCP (172.20.0.100-200) + DNS (8.8.8.8, 1.1.1.1)
    │
    ├── xlinkkai/                       # XLink Kai runtime state (created at first start)
    │   ├── kaiengine.conf              # XLink Kai configuration
    │   └── README                      # XLink Kai usage notes
    │
    └── games/                          # Game ISOs (NOT in git)
        └── *.iso
```

### Files NOT in Git

Excluded via [`.gitignore`](.gitignore):

- `*.qcow2` (Xbox disk images, ~3.6GB)
- `*.iso` (Game ISOs)
- `*.so` (Compiled shared libraries, built at runtime)
- `config/.cache/`, `config/.local/`, etc. (Runtime-generated LinuxServer base image state)

**Distribution:** Large files hosted externally (e.g., Google Drive) and downloaded separately.

---

## Build & Run Commands

### Prerequisites

1. **Download large files** (not in git):
   - `iguana-dev.qcow2` (~3.6GB) → `config/emulator/iguana-dev.qcow2`
   - Game ISOs → `config/games/*.iso`

2. **Ensure host kernel modules** are loaded:
   ```bash
   sudo modprobe tun
   ```

### Build

```bash
cd /home/docker/bridged-xemu
docker compose build
```

**Built image:** `xemu-bridged:latest`

### Run

```bash
docker compose up -d
```

**Services started:**
- `xemu-halo2-server` (172.20.0.10) — xemu emulator with Selkies web UI
- `xlinkkai` (172.20.0.20) — XLink Kai for online multiplayer
- `xbdm-relay` (172.20.0.3) — socat relay for XBDM (TCP 731)
- `xemu-dhcp` (172.20.0.2) — dnsmasq DHCP/DNS server

**Emulated Xbox IPs:**
- `172.20.0.50` — Title interface (gaming, FTP port 21)
- `172.20.0.51` — Debug interface (XBDM port 731, responds to ping)

### Access

| Service | URL/Port | Notes |
|---------|----------|-------|
| xemu (HTTP) | `http://localhost:3000` | Selkies web UI (requires SSH tunnel) |
| xemu (HTTPS) | `https://localhost:3001` | Self-signed cert |
| XLink Kai | `http://localhost:34522` | Web interface |
| XBDM (debug) | `localhost:731` | Via xbdm-relay, requires SSH tunnel |
| Xbox FTP | `172.20.0.50:21` | Requires SOCKS proxy or `lftp` from server terminal |

**SSH Tunnel Example:**
```bash
ssh -L 3000:localhost:3000 -L 731:localhost:731 user@your-server-ip
```

### Stop

```bash
docker compose down
```

### Rebuild After Changes

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

### View Logs

```bash
docker compose logs -f xemu          # xemu logs
docker compose logs -f xbdm-relay    # relay logs
docker logs xemu-halo2-server        # Full container logs
```

### Exec Into Container

```bash
docker exec -it xemu-halo2-server bash
```

---

## Architecture Decisions

### 1. Overlay Pattern vs. Fork

**Decision:** Use `FROM lscr.io/linuxserver/xemu:latest` and layer minimal changes on top.

**Why:**
- LinuxServer.io maintains the base image (xemu updates, Selkies UI, s6-overlay init system)
- We only modify networking behavior and add custom init scripts
- Automatic upstream updates without manual merging
- Clear separation of concerns

**Modifications:**
- Add `wmctrl` package for window management
- Replace `/defaults/autostart` with custom launcher script
- Add `custom-cont-init.d` init scripts for network capabilities and config symlinks

### 2. Bridged Networking with pcap Backend

**Decision:** Use xemu's pcap backend on Docker bridge interface `eth0` instead of user-mode NAT or TAP device.

**Why:**
- Emulated Xbox appears as real device on network with static IP
- No port forwarding required — all Xbox ports accessible at 172.20.0.50/51
- Compatible with XLink Kai for system link gaming over internet
- Enables Xbox Dashboard network settings to work correctly

**Requirements:**
- `privileged: true` on xemu container (for raw packet capture)
- `cap_add: NET_ADMIN` (for TAP device)
- `/dev/net/tun` device passthrough
- `setcap cap_net_raw,cap_net_admin+eip` on xemu binary

### 3. setcap + ldconfig + LD_PRELOAD Chain

**Decision:** Grant network capabilities at runtime (not build time), register AppImage libraries with `ldconfig`, and preserve LD_PRELOAD via `/etc/ld.so.preload`.

**Why:**
- `setcap` causes Linux to strip `LD_LIBRARY_PATH` and `LD_PRELOAD` (secure execution mode / AT_SECURE)
- xemu's AppImage bundles libraries in `/opt/xemu/usr/lib/` and relies on `LD_LIBRARY_PATH` to find them
- Selkies web UI relies on `LD_PRELOAD` for joystick interposer (`/usr/lib/selkies_joystick_interposer.so`)
- pcap receive fix relies on `LD_PRELOAD` for immediate mode shim (`/config/emulator/pcap_immediate.so`)

**Solution:**
1. Register AppImage libraries via `/etc/ld.so.conf.d/xemu.conf` + `ldconfig` (not stripped by setcap)
2. Write preload libraries to `/etc/ld.so.preload` instead of env var (always honored)
3. Apply `setcap` at runtime in `10-xemu-setcap` init script (runs as root during s6-overlay init)

**Important Constraint:**
- **NEVER apply setcap at build time.** Docker layers are immutable — runtime changes don't persist. Always apply in `custom-cont-init.d` script at container startup.

### 4. Separate xbdm-relay Container

**Decision:** Run socat relay in a dedicated Alpine container on a separate bridge port instead of inside xemu container.

**Why:**
- **Bridge hairpin mode issue:** Containers on the same bridge port cannot reach each other when the destination IP is on the same port (packets exiting a port cannot re-enter the same port)
- The Xbox's pcap-injected IP (172.20.0.51) is on the same bridge port as the xemu container (172.20.0.10)
- socat running inside xemu container cannot reach 172.20.0.51
- Separate container (`xbdm-relay` at 172.20.0.3) avoids hairpin entirely

**Additional Benefit:**
- Relay container also needs `ethtool -K eth0 tx off` to disable TX checksum offloading (same bug affects relay)
- Installing `ethtool` at runtime in Alpine is simple: `apk add --no-cache ethtool`

### 5. Static IPs for Xbox (No DHCP)

**Decision:** Configure Xbox with static IPs (172.20.0.50/51) in Xbox Dashboard, not via DHCP.

**Why:**
- Docker bridges do not reliably forward raw Layer 2 broadcast frames (DHCP discover) between containers
- pcap-injected packets use the container's bridge port, but DHCP broadcasts don't reach other containers
- dnsmasq DHCP server at 172.20.0.2 can serve IPs to *future* devices, but Xbox must use static IP

**How to Set:**
1. Boot xemu, open Xbox Dashboard → Settings → Network Settings
2. Select "Manual" configuration
3. Enter static IPs (see CHANGELOG.md for exact values)

### 6. Custom Bridge Network (172.20.0.0/24)

**Decision:** Create custom Docker bridge network instead of using default Docker network.

**Why:**
- Predictable static IP assignments
- Isolated from other Docker projects
- Gateway at 172.20.0.1 provides internet access via host iptables NAT/MASQUERADE
- All containers share Layer 2 connectivity for broadcast traffic (XLink Kai, future DHCP clients)

---

## Container Startup Flow

**Step-by-step initialization sequence:**

1. **s6-overlay runs `custom-cont-init.d/01-install-autostart`** (as root):
   - Copies `/defaults/autostart` to `/config/.config/openbox/autostart` (the base image only does this on first run; this script force-syncs it every start so our custom version is always active)
   - Creates `/config/.local/share/xemu/xemu/` directory tree
   - Symlinks `xemu.toml` from xemu's default location to `/config/emulator/xemu.toml`
   - Fixes file permissions (`chown abc:abc`)

2. **s6-overlay runs `custom-cont-init.d/10-xemu-setcap`** (as root):
   - Enables promiscuous mode on eth0 for receiving Xbox-addressed unicast frames
   - Disables TX checksum offloading on eth0 (see "TCP Checksum Offloading Fix" below)
   - Registers AppImage libraries with system linker (`ldconfig`) so they can be found without `LD_LIBRARY_PATH`
   - Applies `setcap cap_net_raw,cap_net_admin+eip` to the xemu binary for pcap networking
   - Writes to `/etc/ld.so.preload`: Selkies interposer + fake udev + pcap immediate mode shim

3. **Desktop session starts, runs `autostart`** (as user `abc`):
   - Launches passleader automation in a separate xterm window (only if `/config/emulator/passleader_v3.sh` exists -- rename from `.sh.disabled` to activate)
   - Starts xemu via `xterm -e /opt/xemu/AppRun`

---

## Known Gotchas

### 1. setcap Strips LD_PRELOAD and LD_LIBRARY_PATH

**Symptom:** After `setcap cap_net_raw+eip /opt/xemu/usr/bin/xemu`, xemu fails with:
```
error while loading shared libraries: libSDL2-2.0.so.0: cannot open shared object file
```

**Root Cause:**
- `setcap` triggers secure execution mode (same as setuid binaries)
- Linux strips `LD_LIBRARY_PATH` and `LD_PRELOAD` env vars in secure execution mode
- xemu's AppImage bundles libraries and relies on `LD_LIBRARY_PATH` to find them

**Solution:**
1. Register AppImage libraries system-wide via `ldconfig`:
   ```bash
   echo "/opt/xemu/usr/lib" > /etc/ld.so.conf.d/xemu.conf
   ldconfig
   ```
2. Write preload libraries to `/etc/ld.so.preload` (always honored):
   ```bash
   printf "%s\n%s\n%s\n" \
     "/usr/lib/selkies_joystick_interposer.so" \
     "/opt/lib/libudev.so.1.0.0-fake" \
     "/config/emulator/pcap_immediate.so" \
     > /etc/ld.so.preload
   ```
3. Then apply `setcap`:
   ```bash
   setcap cap_net_raw,cap_net_admin+eip /opt/xemu/usr/bin/xemu
   ```

**Implemented in:** [`config/custom-cont-init.d/10-xemu-setcap`](config/custom-cont-init.d/10-xemu-setcap)

### 2. NEVER Apply setcap at Build Time

**Symptom:** Capabilities applied during `docker build` are lost at runtime.

**Root Cause:**
- Docker layers are read-only and immutable
- File capabilities are stored in extended attributes (`user.capability` xattr)
- When container starts, the overlay filesystem doesn't preserve extended attributes correctly
- `getcap /opt/xemu/usr/bin/xemu` returns empty at runtime even if set during build

**Solution:**
- Always apply `setcap` at **runtime** in `custom-cont-init.d` init script
- The init script runs as root during s6-overlay initialization (before user session starts)
- Capabilities are applied fresh on every container start

**Never do this:**
```dockerfile
# ❌ WRONG - capabilities lost at runtime
RUN setcap cap_net_raw+eip /opt/xemu/usr/bin/xemu
```

**Always do this:**
```bash
# ✅ CORRECT - in custom-cont-init.d/10-xemu-setcap
setcap cap_net_raw,cap_net_admin+eip /opt/xemu/usr/bin/xemu
```

### 3. TCP Checksum Offloading Breaks Xbox TCP Connections

**Symptom:**
- `ping 172.20.0.51` works ✅
- `nc 172.20.0.50 21` (FTP) times out ❌
- `nc 172.20.0.51 731` (XBDM) times out ❌
- `tcpdump` shows packets with `cksum incorrect`

**Root Cause:**
- Host kernel uses TX checksum offloading (writes placeholder checksums expecting NIC hardware to complete them)
- Packets to pcap-injected Xbox IPs (172.20.0.50/51) traverse Docker bridge (software) — no hardware ever fills in the checksum
- Xbox TCP stack silently drops bad-checksum packets
- ICMP ping still works because kernel computes ICMP checksums in software

**Solution:**
```bash
ethtool -K eth0 tx off
```

**Verify:**
```bash
ethtool -k eth0 | grep tx-checksum
# Output should show: tx-checksum-ip-generic: off
```

**Implemented in:** [`config/custom-cont-init.d/10-xemu-setcap`](config/custom-cont-init.d/10-xemu-setcap:36)

### 4. libpcap Immediate Mode Required for Packet Receive

**Symptom:** xemu can SEND packets but never RECEIVES. `tcpdump` on bridge shows packets arriving, but xemu's event loop never processes them.

**Root Cause:**
- xemu calls `pcap_open_live()` which does NOT set immediate mode
- On Linux with libpcap >= 1.9 and TPACKET_V3, `pcap_get_selectable_fd()` returns an fd that NEVER becomes readable without immediate mode
- xemu's event loop waits on this fd, never wakes up, never calls `pcap_dispatch()`

**Solution:**
- LD_PRELOAD shim intercepts `pcap_open_live()` and replaces it with `pcap_create()` + `pcap_set_immediate_mode()` + `pcap_activate()` sequence
- Must use `/etc/ld.so.preload` (not `LD_PRELOAD` env var) because setcap strips env vars

**Implemented in:**
- Source: [`config/emulator/pcap_immediate.c`](config/emulator/pcap_immediate.c)
- Compiled: `config/emulator/pcap_immediate.so` (built inside container, not in git)
- Loaded: [`config/custom-cont-init.d/10-xemu-setcap:58-66`](config/custom-cont-init.d/10-xemu-setcap#L58-L66)

### 5. Bridge Hairpin Mode (Cannot Reach Same-Port IPs)

**Symptom:** socat relay inside xemu container cannot reach Xbox IPs (172.20.0.50/51) even though other containers can.

**Root Cause:**
- Linux bridge hairpin mode is disabled by default
- Packets exiting a bridge port cannot re-enter the same port
- xemu container (172.20.0.10) and Xbox pcap-injected IPs (172.20.0.50/51) share the same bridge port
- socat running inside xemu container tries to reach 172.20.0.51 but packets are dropped by bridge

**Cannot Fix from Inside Container:**
- `/sys/class/net/eth0/brport/hairpin_mode` doesn't exist from container's perspective
- Setting hairpin requires host-level access: `echo 1 > /sys/class/net/<bridge>/brif/<port>/hairpin_mode`

**Solution:**
- Use **separate container** (`xbdm-relay`) on its own bridge port (172.20.0.3)
- Avoids hairpin entirely — relay container's packets exit one port and enter Xbox's port
- Bonus: separate container also needs `ethtool -K eth0 tx off`, which is cleaner to manage in Alpine container

**Implemented in:** [`docker-compose.yml:85-102`](docker-compose.yml#L85-L102) (`xbdm-relay` service)

### 6. VS Code Remote-SSH LocalForward Limitations

**Symptom:**
- VS Code SSH config has `LocalForward 731 172.20.0.51:731`
- Port 731 opens on Windows, but connecting to `localhost:731` connects then hangs (no data flows)

**Root Cause:**
- VS Code's SSH implementation only supports forwarding to `localhost:PORT` on remote
- Forwarding to non-localhost IPs (e.g., `172.20.0.51:731`) silently fails — TCP handshake succeeds but no data flows

**Solution:**
- Always forward to `localhost:PORT` on remote and use relay (socat/Docker port mapping) to bridge to actual target:
  ```
  # VS Code SSH config
  LocalForward 731 localhost:731

  # docker-compose.yml
  ports:
    - 127.0.0.1:731:731  # xbdm-relay maps localhost:731 → 172.20.0.51:731
  ```

**Port Conflict Detection:**
- If VS Code auto-increments port (731→732), something is holding port 731
- Windows: `netstat -ano | findstr ":731 "` to find PID, then kill it in Task Manager

### 7. FTP Passive Mode Requires SOCKS Proxy

**Symptom:** Simple SSH port forward to Xbox FTP (port 21) connects but file transfers fail.

**Root Cause:**
- FTP uses port 21 for commands but opens random ports for every file transfer (passive mode)
- Simple port forward only handles port 21 — data connections fail

**Solution:**
- Use SSH SOCKS proxy (`ssh -D 1080`) to route ALL FTP traffic through SSH
- Configure FileZilla/WinSCP to use SOCKS5 proxy at `localhost:1080`
- Simpler alternative: `lftp -u xbox,xbox 172.20.0.50` from VS Code terminal on server

**Details:** See [`FTP-Fix.md`](FTP-Fix.md)

---

## Common Tasks

### Add New Package to Container

**Edit:** [`Dockerfile`](Dockerfile)

```dockerfile
RUN \
  apt-get update && \
  apt-get install -y --no-install-recommends \
    wmctrl \
    your-new-package && \
  apt-get autoclean && \
  rm -rf \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /tmp/*
```

**Rebuild:**
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Modify xemu Configuration

**Edit:** [`config/emulator/xemu.toml`](config/emulator/xemu.toml)

Changes take effect on next xemu restart:
```bash
docker compose restart xemu
```

**Note:** xemu auto-saves config changes through its UI. If you modify `xemu.toml` in git, those changes will be overwritten by xemu's auto-save. To make permanent config changes:
1. Edit `xemu.toml` in git
2. Restart container to load new config
3. Commit the updated `xemu.toml` back to git after verifying it works

### Change Xbox IP Addresses

**Edit:** [`docker-compose.yml`](docker-compose.yml) and [`config/dnsmasq/dnsmasq.conf`](config/dnsmasq/dnsmasq.conf)

1. Update DHCP pool in `dnsmasq.conf` to avoid new static IPs
2. Rebuild containers:
   ```bash
   docker compose down
   docker compose up -d
   ```
3. Boot xemu, open Xbox Dashboard → Settings → Network Settings → Manual
4. Enter new static IPs for title and debug interfaces

### Update Base Image (Sync with Upstream)

**Pull latest LinuxServer.io xemu image:**
```bash
docker pull lscr.io/linuxserver/xemu:latest
docker compose build --no-cache
docker compose up -d
```

**Verify no breaking changes:**
1. Check xemu launches correctly
2. Verify pcap networking works (ping 172.20.0.51)
3. Test TCP connections (FTP, XBDM)
4. Check logs for errors: `docker compose logs xemu`

### Recompile pcap_immediate.so Shim

**Inside container:**
```bash
docker exec -it xemu-halo2-server bash
cd /config/emulator
gcc -shared -fPIC -o pcap_immediate.so pcap_immediate.c -ldl
exit
```

**Restart container:**
```bash
docker compose restart xemu
```

### Enable Passleader Automation Script

**Rename script:**
```bash
cd /home/docker/bridged-xemu/config/emulator
mv passleader_v3.sh.disabled passleader_v3.sh
```

**Restart container:**
```bash
docker compose restart xemu
```

Script launches in separate xterm window. Press Ctrl+C in automation terminal to stop.

### Push to GitHub

**🚨 CRITICAL: Always ask for user confirmation before pushing to GitHub!**

**Working directory:** `/home/docker/bridged-xemu/`

```bash
cd /home/docker/bridged-xemu
git add .
git commit -m "Your commit message

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
# STOP HERE - ask user before proceeding
git push origin main  # Only run after explicit user confirmation
```

**Note:** Verify git remote with `git remote -v` before pushing. The origin should point to `Roasted-Codes/docker-bridged-xemu`.

**AI Agent Rule:** Never execute `git push` without first asking the user "Ready to push to GitHub?" and receiving explicit confirmation. This applies to ALL branches, not just main.

### Test After Changes

**Full test sequence:**
```bash
# 1. Rebuild and start
docker compose down
docker compose build --no-cache
docker compose up -d

# 2. Verify xemu starts
docker compose logs -f xemu

# 3. Test network connectivity
docker exec xemu-halo2-server ping -c 3 172.20.0.51  # Should work
docker exec xemu-halo2-server nc -zv 172.20.0.51 731  # Should connect (if XBDM running)

# 4. Check capabilities
docker exec xemu-halo2-server getcap /opt/xemu/usr/bin/xemu
# Expected: /opt/xemu/usr/bin/xemu = cap_net_admin,cap_net_raw+eip

# 5. Check TX checksum offloading
docker exec xemu-halo2-server ethtool -k eth0 | grep tx-checksum
# Expected: tx-checksum-ip-generic: off

# 6. Check LD_PRELOAD
docker exec xemu-halo2-server cat /etc/ld.so.preload
# Expected: Three lines with selkies_joystick_interposer.so, libudev-fake, pcap_immediate.so

# 7. Access xemu web UI
# Open browser: https://localhost:3001 (via SSH tunnel)
```

---

## File Conventions

### Comment Markers for Local Overrides

When replacing or modifying upstream files, use clear comment markers:

```bash
# =============================================================================
# LOCAL OVERRIDE: Custom autostart script for docker-bridged-xemu
# =============================================================================
# This file replaces the upstream LinuxServer.io autostart.
# Modifications:
#   - Launches xemu in xterm (upstream uses bare command)
#   - Optional passleader automation script launcher
# =============================================================================
```

### Naming Conventions

**Init Scripts:**
- Prefix with number for execution order: `01-install-autostart`, `10-xemu-setcap`
- Use descriptive names: `install-autostart` (not `init1.sh`)
- Make executable: `chmod +x`

**Config Files:**
- Use official tool names: `xemu.toml` (not `xemu-config.toml`)
- Backups: `xemu.toml.backup-YYYYMMDD` or `xemu.toml.backup-description`

**Disabled Features:**
- Append `.disabled` to disable: `passleader_v3.sh.disabled`
- Remove `.disabled` to enable: `passleader_v3.sh`

**Docker Services:**
- Use descriptive container names: `xemu-halo2-server`, `xbdm-relay`, `xemu-dhcp`
- Prefix related services: `xemu-*` for project components

### Code Style

**Bash Scripts:**
- Use `set -euo pipefail` for error handling
- Section headers with `# =============================================================================` dividers
- Prefix log messages with script name: `echo "[10-xemu-setcap] message"`
- Window detection via `wmctrl -l` and input via `xdotool`

**Docker Configuration:**
- `security_opt: seccomp:unconfined` for GUI applications
- `PUID`/`PGID` environment variables (default 1000:1000)
- Mount `/config` volume for persistent data
- `shm_size: "1gb"` for xemu's shared memory needs
- CPU-only mode: set `DISABLE_ZINK=true` and `DISABLE_DRI3=true`
- `SELKIES_GAMEPAD_ENABLED=true` enables browser gamepad passthrough

**Configuration Files:**
- TOML format for xemu settings
- Use absolute paths in configuration files (e.g., `/config/emulator/mcpx_1.0.bin`)

**Documentation Style:**
- Use `#` for shell scripts, `//` for C code, `#` for TOML files
- Always explain **WHY**, not just **WHAT**
- Section structure: What → Why → How → Gotchas

**Example:**
```bash
# Good:
# setcap strips LD_LIBRARY_PATH, so register libs via ldconfig
ldconfig

# Bad:
# Run ldconfig
ldconfig
```

---

## Docker Conventions

**Project-specific best practices:**

- When modifying capabilities (e.g., `setcap`), verify that `LD_PRELOAD` and other environment-based library injection mechanisms still work. `setcap` triggers secure execution mode (`AT_SECURE`) which silently strips both `LD_PRELOAD` and `LD_LIBRARY_PATH`.
- Always test controller/input device passthrough after changing permissions or capabilities in containers. The Selkies joystick interposer depends on being loaded into the xemu process.
- Never apply `setcap` without also updating `/etc/ld.so.preload` (for Selkies input) and running `ldconfig` (for AppImage libraries). These three operations are a unit.
- The xbdm-relay container must be a separate container (not socat inside xemu) due to bridge hairpin mode being disabled by default.

---

## Network Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Host (Vultr VPS or Local Machine)                                       │
│                                                                          │
│  Docker Network: xemu_lan (172.20.0.0/24)                               │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                                                                      │ │
│  │  .1  Docker Gateway (NATs to internet via host iptables)            │ │
│  │  .2  xemu-dhcp (dnsmasq: DHCP 172.20.0.100-200, DNS 8.8.8.8)        │ │
│  │  .3  xbdm-relay (socat: localhost:731 → 172.20.0.51:731)            │ │
│  │  .10 xemu-halo2-server (Selkies web UI: 3000/3001)                  │ │
│  │      │                                                               │ │
│  │      └─→ pcap on eth0 injects packets for:                          │ │
│  │          .50 Emulated Xbox - title interface (FTP 21, gaming)       │ │
│  │          .51 Emulated Xbox - debug interface (XBDM 731, ping)       │ │
│  │  .20 xlinkkai (XLink Kai web UI: 34522)                             │ │
│  │                                                                      │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  Host Ports (mapped to Docker containers):                              │
│    3000/3001 → xemu HTTP/HTTPS (localhost only, SSH tunnel)             │
│    34522     → XLink Kai web UI                                         │
│    731       → xbdm-relay → 172.20.0.51:731 (localhost, SSH tunnel)    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
         ▲
         │ SSH Tunnel
         │
    ┌────────────┐
    │ Home PC    │
    │            │
    │ Browser:   │
    │ localhost: │
    │ 3001, 731  │
    └────────────┘
```

### IP Assignments

| IP | Service | Purpose |
|----|---------|---------|
| 172.20.0.1 | Docker Gateway | NAT to internet |
| 172.20.0.2 | dnsmasq | DHCP + DNS |
| 172.20.0.3 | xbdm-relay | XBDM TCP relay (avoids hairpin) |
| 172.20.0.10 | xemu container | Selkies web UI |
| 172.20.0.20 | xlinkkai | XLink Kai |
| 172.20.0.50 | Xbox (title) | Gaming, FTP (pcap-injected) |
| 172.20.0.51 | Xbox (debug) | XBDM, ping (pcap-injected) |
| 172.20.0.100-200 | DHCP pool | Available for future devices |

---

## Upstream vs. Overlay

### Upstream (LinuxServer.io)

**Base Image:** `lscr.io/linuxserver/xemu:latest`

**Provides:**
- xemu emulator (extracted from AppImage to `/opt/xemu/`)
- Selkies web streaming (KasmVNC + gstreamer)
- Openbox window manager
- s6-overlay init system
- User `abc` (uid 1000, gid 1000) for unprivileged execution
- `/defaults/autostart` → `/config/.config/openbox/autostart` on first start
- Volume persistence at `/config`

**Upstream Repository:** https://github.com/linuxserver/docker-xemu

### Overlay (This Project)

**Image:** `xemu-bridged:latest` (built from [`Dockerfile`](Dockerfile))

**Adds:**
- `wmctrl` package for window management
- Custom `/defaults/autostart` script (replaces upstream)
- `custom-cont-init.d` init scripts for network capabilities
- pcap immediate mode shim (`pcap_immediate.c` + `.so`)
- XLink Kai container
- dnsmasq DHCP/DNS container
- xbdm-relay container

**Does NOT modify:**
- Base LinuxServer.io functionality
- xemu binary or version
- Selkies web UI
- s6-overlay init system

---

## Security Considerations

### Privileged Containers

**xemu:** `privileged: true` required for raw packet capture (pcap)
**xlinkkai:** `privileged: true` required for network bridging
**xbdm-relay:** `cap_add: NET_ADMIN` for ethtool only
**dhcp:** `cap_add: NET_ADMIN` for DHCP server only

**Mitigation:**
- All containers run on isolated custom bridge network (not host network)
- xbdm-relay port 731 bound to localhost only (`127.0.0.1:731:731`)
- xemu ports 3000/3001 NOT exposed on public interface (use SSH tunnel)

### Port Exposure

**Public (0.0.0.0):**
- None by default (XLink Kai port 34522 can be exposed if needed)

**Localhost only (127.0.0.1):**
- 3000 (xemu HTTP) — use SSH tunnel
- 3001 (xemu HTTPS) — use SSH tunnel
- 731 (XBDM relay) — use SSH tunnel

**Recommendation:** Always use SSH tunnels for accessing xemu and XBDM. Never expose ports directly on public IP.

### Secrets Management

**No secrets required.** All configuration is in version control.

**Xbox BIOS files:**
- `mcpx_1.0.bin`, `CerbiosDebug_old.bin` included in git (publicly available)
- EEPROM (`iguana-eeprom.bin`) included in git (not tied to real hardware)

---

## Troubleshooting

### xemu Won't Start

**Check logs:**
```bash
docker compose logs xemu
```

**Common issues:**
- Missing disk image: `config/emulator/iguana-dev.qcow2` not downloaded
- Permission error: `chown -R 1000:1000 config/` to fix ownership
- Init script failed: Check `/var/log/s6-uncaught-logs` inside container

### No Network Connectivity

**Test basic networking:**
```bash
docker exec xemu-halo2-server ping -c 3 172.20.0.1   # Docker gateway
docker exec xemu-halo2-server ping -c 3 172.20.0.51  # Xbox debug interface
```

**Check capabilities:**
```bash
docker exec xemu-halo2-server getcap /opt/xemu/usr/bin/xemu
# Expected: cap_net_admin,cap_net_raw+eip
```

**Check LD_PRELOAD:**
```bash
docker exec xemu-halo2-server cat /etc/ld.so.preload
# Expected: Three lines (selkies, udev-fake, pcap_immediate)
```

**Check promiscuous mode:**
```bash
docker exec xemu-halo2-server ip link show eth0
# Expected: PROMISC flag
```

### TCP Connections Timeout (But Ping Works)

**Symptom:** `ping 172.20.0.51` works, but `nc 172.20.0.51 731` times out.

**Check TX checksum offloading:**
```bash
docker exec xemu-halo2-server ethtool -k eth0 | grep tx-checksum
# Expected: tx-checksum-ip-generic: off
```

**If it shows `on`, fix manually:**
```bash
docker exec xemu-halo2-server ethtool -K eth0 tx off
```

**Permanent fix:** Verify `10-xemu-setcap` init script runs successfully:
```bash
docker compose logs xemu | grep xemu-setcap
```

### xemu Crashes with Library Error

**Symptom:** `error while loading shared libraries: libSDL2-2.0.so.0`

**Root cause:** `setcap` strips `LD_LIBRARY_PATH`, AppImage libraries not registered.

**Fix:**
```bash
docker exec xemu-halo2-server bash -c \
  'echo "/opt/xemu/usr/lib" > /etc/ld.so.conf.d/xemu.conf && ldconfig'
docker compose restart xemu
```

**Permanent fix:** Verify `10-xemu-setcap` init script runs successfully.

### FTP Connection Fails

**See:** [`FTP-Fix.md`](FTP-Fix.md)

**Quick check:**
1. Is Xbox booted to dashboard?
2. Is FTP server enabled in XBMC settings?
3. Is TX checksum offloading disabled? (`ethtool -k eth0`)
4. Is pcap immediate mode shim loaded? (`cat /etc/ld.so.preload`)

### XBDM Connection Fails

**Check relay container:**
```bash
docker compose logs xbdm-relay
```

**Test relay from host:**
```bash
nc -zv localhost 731
```

**Test Xbox debug port directly from inside xemu container:**
```bash
docker exec xemu-halo2-server nc -zv 172.20.0.51 731
```

If relay fails but direct connection works, check `xbdm-relay` container has TX checksum offloading disabled.

### XLink Kai Not Detecting Xbox

**Check XLink Kai logs:**
```bash
docker compose logs xlinkkai
```

**Verify containers on same bridge:**
```bash
docker network inspect bridged-xemu_xemu_lan
```

**Check XLink Kai interface setting:**
- XLink Kai web UI → Settings → Interface: must be `eth0`

---

## Future Work

See [`tailscale-plan.md`](tailscale-plan.md) for Tailscale subnet routing implementation plan.

**Goals:**
- Add Tailscale container to expose entire `172.20.0.0/24` subnet to remote clients
- Direct access to Xbox IPs (172.20.0.50/51) from Windows PC without SSH tunnels
- Fully reproducible VPN access via docker-compose.yml

---

## References

- [xemu Documentation](https://xemu.app/docs/)
- [LinuxServer.io xemu Image](https://github.com/linuxserver/docker-xemu)
- [XLink Kai](https://www.teamxlink.co.uk/)
- [dnsmasq Documentation](https://thekelleys.org.uk/dnsmasq/doc.html)
- [libpcap Immediate Mode Issue](https://github.com/the-tcpdump-group/libpcap/issues/1099)

---

## License

This project inherits the GPL-3.0 license from the upstream LinuxServer.io xemu image.

See [`LICENSE`](LICENSE) for full text.
