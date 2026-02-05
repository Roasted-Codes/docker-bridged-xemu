# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Docker-based Xbox emulator (xemu) deployment with XLink Kai multiplayer networking. This project is an **overlay image** built on top of the published [linuxserver/docker-xemu](https://github.com/linuxserver/docker-xemu) image (`lscr.io/linuxserver/xemu:latest`). All customizations are additive -- no upstream files are modified. Upstream updates flow automatically when the image is rebuilt.

The GitHub repo is [`Roasted-Codes/docker-bridged-xemu`](https://github.com/Roasted-Codes/docker-bridged-xemu). Upstream changes come through the base image tag, not git merges.

**Main project location:** `docker-bridged-xemu/`

## Common Commands

```bash
# Build overlay image and start all services
cd bridged-xemu
docker compose up -d

# Rebuild after Dockerfile or autostart changes
docker compose up -d --build

# Force rebuild from latest upstream (pulls new base image)
docker compose build --no-cache --pull

# Restart just xemu (e.g., after changing init scripts or xemu.toml)
docker compose restart xemu

# View logs
docker logs xemu-halo2-server
docker logs xlinkkai
```

## Architecture

### Overlay Image Pattern

The Dockerfile uses `FROM lscr.io/linuxserver/xemu:latest` -- the fully-built upstream image with xemu already installed. Our overlay only adds:

- **Build time** (`Dockerfile`): Installs `wmctrl` (the only package not already in upstream). Copies our custom `autostart` to `/defaults/autostart`.
- **Runtime** (`custom-cont-init.d/` scripts): Applies network capabilities, manages config symlinks, and fixes input compatibility. These run as root during s6-overlay init before the desktop session starts.

There is no `Dockerfile.aarch64`. Multi-arch support is handled automatically by the upstream base image.

### Services

Three containers on a shared Docker bridge network (`172.20.0.0/24`):

| Service | Container Name | IP | Ports | Purpose |
|---------|---------------|-----|-------|---------|
| xemu | xemu-halo2-server | 172.20.0.10 | 3000 (HTTP), 3001 (HTTPS) | Xbox emulator with Selkies web interface |
| xlinkkai | xlinkkai | 172.20.0.20 | 34522 (web UI), 30000/udp, 34523/udp | XLink Kai for LAN gaming over internet |
| dhcp | xemu-dhcp | 172.20.0.2 | -- | dnsmasq DHCP/DNS for the bridge network |

### Bridge Network

Services use a custom Docker bridge network (`xemu_lan`) instead of host networking. This provides:
- Layer 2 broadcast traffic between xemu and XLink Kai (required for Xbox system link)
- Static IP assignment for predictable service discovery
- DHCP via dnsmasq for the emulated Xbox's network stack
- Isolation from the host network

The xemu container runs with `privileged: true`, `cap_add: NET_ADMIN`, and `/dev/net/tun` mapped for pcap/bridged networking. The xemu binary uses pcap backend on `eth0` to capture/inject packets on the bridge.

### Volume Mounts

The xemu service has two volume mounts:
- `./config:/config` -- persistent data (xemu config, BIOS files, saves, runtime state)
- `./config/custom-cont-init.d:/custom-cont-init.d` -- init scripts that run as root

The second mount is required because LinuxServer's s6-overlay looks for init scripts at `/custom-cont-init.d` (root of filesystem), NOT at `/config/custom-cont-init.d`. Without this explicit mount, the scripts would only exist under `/config/` and never execute.

### Configuration Symlink Pattern

Xemu hardcodes its config to `~/.local/share/xemu/xemu/xemu.toml`. The `01-install-autostart` init script symlinks this to `/config/emulator/xemu.toml` so there is a single, distributable config location. The symlink is recreated on every container start.

## Container Startup Flow

1. **s6-overlay runs `custom-cont-init.d/01-install-autostart`** (as root):
   - Copies `/defaults/autostart` to `/config/.config/openbox/autostart` (the base image only does this on first run; this script force-syncs it every start so our custom version is always active)
   - Creates `/config/.local/share/xemu/xemu/` directory tree
   - Symlinks `xemu.toml` from xemu's default location to `/config/emulator/xemu.toml`
   - Fixes file permissions (`chown abc:abc`)

2. **s6-overlay runs `custom-cont-init.d/10-xemu-setcap`** (as root):
   - Enables promiscuous mode on eth0 for receiving Xbox-addressed unicast frames
   - Registers AppImage libraries with system linker (`ldconfig`) so they can be found without `LD_LIBRARY_PATH`
   - Applies `setcap cap_net_raw,cap_net_admin+eip` to the xemu binary for pcap networking
   - Writes to `/etc/ld.so.preload`: Selkies interposer + fake udev + pcap immediate mode shim (see "Setcap and Input Compatibility" and "Pcap Immediate Mode Fix" below)

3. **Desktop session starts, runs `autostart`** (as user `abc`):
   - Launches passleader automation in a separate xterm window (only if `/config/emulator/passleader_v3.sh` exists -- rename from `.sh.disabled` to activate)
   - Starts xemu via `xterm -e /opt/xemu/AppRun`

## Setcap and Input Compatibility

This is a critical interaction between pcap networking and Selkies browser input. Both features are required and they conflict at the Linux kernel level.

**The problem:**
- pcap/bridged networking requires `setcap cap_net_raw,cap_net_admin+eip` on the xemu binary
- Selkies browser input works by injecting `selkies_joystick_interposer.so` into applications via `LD_PRELOAD` (set by s6-overlay's `init-selkies-config` service)
- When a binary has file capabilities (`setcap`), Linux activates **secure execution mode** (`AT_SECURE`), which **silently strips `LD_PRELOAD`**
- Result: the Selkies interposer never loads into xemu, and all browser-based input (keyboard, gamepad) stops working

**The fix:**
- `10-xemu-setcap` writes the interposer paths to `/etc/ld.so.preload` (a system file always honored by the dynamic linker, regardless of `AT_SECURE`)
- The two libraries written are `/usr/lib/selkies_joystick_interposer.so` and `/opt/lib/libudev.so.1.0.0-fake`
- This ensures both pcap networking AND browser input work simultaneously

**`setcap` also strips `LD_LIBRARY_PATH`**, which would prevent xemu from finding its bundled AppImage libraries. This is handled separately by `10-xemu-setcap` registering the AppImage lib directory (`/opt/xemu/usr/lib`) with `ldconfig`.

## Pcap Immediate Mode Fix

xemu's pcap backend is completely broken for *receiving* packets on modern Linux. Sending works fine, but the emulated Xbox can never receive any network traffic. This section documents the root cause and fix.

**Root cause:**
- xemu calls `pcap_open_live()` to open the network interface, which does NOT call `pcap_set_immediate_mode()`
- On libpcap >= 1.9 with Linux's TPACKET_V3 (the default since kernel 3.2), the file descriptor returned by `pcap_get_selectable_fd()` never becomes readable unless immediate mode is enabled
- xemu's QEMU event loop polls this fd waiting for `POLLIN`, which never fires
- Result: xemu can inject packets via `pcap_sendpacket()` (bypasses the fd) but never reads incoming packets

**Why a simple shim doesn't work:**
- First attempt: intercept `pcap_activate()` via LD_PRELOAD to add `pcap_set_immediate_mode()` before activation
- This fails because xemu bundles its own libpcap at `/opt/xemu/usr/lib/libpcap.so.0.8`
- Internal calls from `pcap_open_live()` → `pcap_activate()` within the same shared library bypass the PLT (Procedure Linkage Table)
- LD_PRELOAD can only intercept cross-library calls that go through the PLT

**The fix (`pcap_immediate.c`):**
- Intercept `pcap_open_live()` instead — this IS a cross-library call (xemu binary → bundled libpcap) so it goes through the PLT
- The shim replaces `pcap_open_live()` with the equivalent `pcap_create` / `pcap_set_immediate_mode(1)` / `pcap_activate` sequence
- Uses `dlsym(RTLD_NEXT, ...)` to call the real functions from whatever libpcap is loaded
- Compiled as a shared library: `gcc -shared -fPIC -o pcap_immediate.so pcap_immediate.c -ldl`
- Loaded via `/etc/ld.so.preload` (not `LD_PRELOAD` env var, because `setcap` triggers `AT_SECURE` which strips `LD_PRELOAD`)

**Files:**
- `config/emulator/pcap_immediate.c` — shim source code
- `config/emulator/pcap_immediate.so` — compiled shim (built inside container, not in git)

**Promiscuous mode:**
- `10-xemu-setcap` also runs `ip link set eth0 promisc on` at the interface level
- This is needed so the container's NIC accepts unicast frames addressed to the Xbox's emulated MAC (which differs from the container's own MAC)
- xemu's libpcap also sets per-socket promiscuous via `PACKET_MR_PROMISC`, but interface-level promisc provides defense in depth

## Key Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Overlay image: `FROM lscr.io/linuxserver/xemu:latest`, installs `wmctrl`, copies custom autostart |
| `docker-compose.yml` | 3-service stack with bridge network (xemu, xlinkkai, dhcp) |
| `root/defaults/autostart` | Desktop session entrypoint: optional passleader launcher + xemu launch |
| `config/custom-cont-init.d/01-install-autostart` | Root init: autostart sync + xemu.toml symlink + permissions |
| `config/custom-cont-init.d/10-xemu-setcap` | Root init: ldconfig + setcap + `/etc/ld.so.preload` for input compat |
| `config/emulator/xemu.toml` | Main xemu configuration (TOML format, auto-saved by xemu via symlink) |
| `config/emulator/*.bin` | BIOS/EEPROM files (mcpx, flashrom, eeprom) |
| `config/emulator/pcap_immediate.c` | LD_PRELOAD shim source: fixes pcap receive on libpcap >= 1.9 (see "Pcap Immediate Mode Fix") |
| `config/emulator/passleader_v3.sh.disabled` | Gameplay automation script (rename to `.sh` to activate) |
| `config/dnsmasq/dnsmasq.conf` | DHCP/DNS config for bridge network |

## Code Style

### Bash Scripts
- Use `set -euo pipefail` for error handling
- Section headers with `# =============================================================================` dividers
- Prefix log messages with script name: `echo "[10-xemu-setcap] message"`
- Window detection via `wmctrl -l` and input via `xdotool`

### Docker Configuration
- `security_opt: seccomp:unconfined` for GUI applications
- `PUID`/`PGID` environment variables (default 1000:1000)
- Mount `/config` volume for persistent data
- `shm_size: "1gb"` for xemu's shared memory needs
- CPU-only mode: set `DISABLE_ZINK=true` and `DISABLE_DRI3=true`
- `SELKIES_GAMEPAD_ENABLED=true` enables browser gamepad passthrough

### Configuration
- TOML format for xemu settings
- Use absolute paths in configuration files (e.g., `/config/emulator/mcpx_1.0.bin`)

## Important Constraints

- **Never apply `setcap` at build time** in the Dockerfile. The xemu binary comes from the base image and changes when upstream updates. `setcap` must be applied at runtime via `10-xemu-setcap` to always target the current binary.
- **Always pair `setcap` with `/etc/ld.so.preload`**. If you apply `setcap` to xemu, you must also write the Selkies interposer to `/etc/ld.so.preload` or browser input will silently break.
- **Always pair `setcap` with `ldconfig`**. The AppImage libraries must be registered system-wide or xemu will fail to start (missing shared libraries).
- **The `custom-cont-init.d` mount must go to `/custom-cont-init.d`** (root), not `/config/custom-cont-init.d`. LinuxServer's s6-overlay only scans the root path.
- **`01-install-autostart` must force-copy autostart every start**. The base image only copies `/defaults/autostart` on first run. Without force-sync, existing containers would use a stale autostart after image updates.
- **`pcap_immediate.so` must be in `/etc/ld.so.preload`**. Without this shim, xemu's pcap backend cannot receive any packets on libpcap >= 1.9 (TPACKET_V3). The shim intercepts `pcap_open_live()` and injects `pcap_set_immediate_mode(1)`. It must intercept `pcap_open_live` (not `pcap_activate`) because xemu's bundled libpcap makes internal calls that bypass the PLT.

## Required Downloads (Not in Git)

Large files distributed separately via Google Drive:
- `xbox_hdd.qcow2` (3.6GB) -> `config/emulator/`
- Game ISOs -> `config/games/`

BIOS files (`*.bin`) ARE included in the repository.
