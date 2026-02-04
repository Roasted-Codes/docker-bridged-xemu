# Changelog

All notable changes to this fork of the LinuxServer.io xemu container are documented in this file.

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Additional System Packages** ([Dockerfile](Dockerfile#L23-L26), [Dockerfile.aarch64](Dockerfile.aarch64#L24-L26))
  - `libusb-1.0-0` - USB device support for Xbox controller passthrough
  - `wmctrl` - Window manager control for automation and window management
  - `xdotool` - X11 automation tool for programmatic input simulation
  - These packages enable better hardware support and automation capabilities
  - Added to both x86_64 and aarch64 (ARM64) builds for cross-platform consistency

- **Xemu Configuration Symlink Management** ([root/defaults/autostart](root/defaults/autostart))
  - Implemented automatic symlinking of xemu's default config location to `/config/emulator/xemu.toml`
  - This enables a single, clean, version-controlled configuration file location
  - Allows xemu auto-save functionality to work properly while maintaining config in a distributable location
  - See comments in `root/defaults/autostart` for detailed technical explanation

- **Setup Documentation** ([SETUP.md](SETUP.md))
  - Comprehensive setup guide for users
  - Documents required files and where to obtain them
  - Troubleshooting and configuration instructions

- **Gameplay Automation** ([config/emulator/passleader_v3.sh](config/emulator/passleader_v3.sh))
  - Automated input script for xemu gameplay
  - Launches in separate terminal window on container start
  - Waits for xemu, loads snapshot (F6), then automates B/A button presses
  - Can be stopped with Ctrl+C in the automation terminal
  - Optional - only runs if script is present in config/emulator/

- **XLink Kai Integration** ([docker-compose.yml](docker-compose.yml#L63-L83))
  - Added XLink Kai service for system link gaming over internet
  - Connects to xemu via UDP tunneling (ports 9968/34523)
  - Web interface accessible on port 34522
  - Enables LAN multiplayer games over the internet
  - Uses ich777/xlinkkaievolution Docker image

- **Bridged Networking with pcap Backend** ([docker-compose.yml](docker-compose.yml#L29-L61), [Dockerfile](Dockerfile#L38-L41), [Dockerfile.aarch64](Dockerfile.aarch64#L38-L41))
  - Enabled `privileged: true` on xemu container for raw packet capture
  - Added `NET_ADMIN` capability and `/dev/net/tun` device for TAP/bridged networking
  - xemu uses pcap backend on `eth0` — the emulated Xbox appears as a real device on the Docker bridge
  - Emulated Xbox debug kit uses static IPs (172.20.0.50 and 172.20.0.51 for title and debug interfaces)
  - All Xbox ports accessible directly at those IPs (UDP 3074 gaming, TCP 731 XDK, TCP 21 FTP)

- **Network Capabilities at Build Time** ([Dockerfile](Dockerfile#L38-L41), [Dockerfile.aarch64](Dockerfile.aarch64#L38-L41))
  - Registers AppImage libraries with system linker via `/etc/ld.so.conf.d/xemu.conf` + `ldconfig`
  - Sets `cap_net_raw,cap_net_admin+eip` on the xemu binary via `setcap`
  - Both steps are required: `setcap` strips `LD_LIBRARY_PATH` (same security rule as setuid), so libraries must be registered system-wide first

- **Runtime Capabilities Init Script** ([config/custom-cont-init.d/10-xemu-setcap](config/custom-cont-init.d/10-xemu-setcap))
  - Re-applies `ldconfig` + `setcap` at container startup as a safety net
  - Runs as root via s6-overlay `custom-cont-init.d` mechanism
  - Cannot run in autostart because it executes as user `abc` (uid 1000), which lacks `CAP_SETFCAP`
  - Mounted into container via `./config/custom-cont-init.d:/custom-cont-init.d` volume

- **Custom Bridge Network** ([docker-compose.yml](docker-compose.yml#L20-L27))
  - `xemu_lan` bridge network (172.20.0.0/24) with static IP assignments
  - Docker gateway at 172.20.0.1 provides internet access via iptables NAT/MASQUERADE
  - All containers share layer 2 connectivity for broadcast traffic

- **dnsmasq DHCP/DNS Service** ([docker-compose.yml](docker-compose.yml#L85-L95), [config/dnsmasq/dnsmasq.conf](config/dnsmasq/dnsmasq.conf))
  - Lightweight DHCP + DNS server running at 172.20.0.2
  - DHCP pool: 172.20.0.100-200 (available for future devices)
  - DNS forwarding to 8.8.8.8 and 1.1.1.1
  - Local hostname resolution: `xemu` → .10, `xlinkkai` → .20
  - Note: Emulated Xbox uses static IP instead of DHCP because Docker bridges don't reliably forward raw Layer 2 broadcast frames (DHCP discover) between containers

### Changed
- **Dockerfile** - Added additional runtime dependencies for USB and automation support
- **Dockerfile** - Added `ldconfig` + `setcap` for network capabilities after AppImage extraction
- **Startup Script** - Modified to manage xemu configuration via symlink instead of relying on default location
- **Startup Script** - Added automatic file ownership fix for xemu.toml to ensure write permissions
- **Startup Script** - Removed broken `setcap` call (cannot work as user `abc`), replaced with documentation pointing to the correct locations where capabilities are set

### Fixed
- **Configuration Saving** - Fixed circular symlink issue that prevented xemu from saving settings
- **File Permissions** - Automatically set correct ownership on xemu.toml at container startup
- **pcap Permission Error** - Fixed "failed to open interface 'eth0' for capture: Operation not permitted" by granting `cap_net_raw,cap_net_admin` via `setcap` at both build time and runtime
- **xemu Crash After setcap** - Fixed `libSDL2-2.0.so.0: cannot open shared object file` caused by `setcap` stripping `LD_LIBRARY_PATH`. Solved by registering AppImage libraries via `ldconfig` before applying capabilities

### Technical Details

#### Configuration Management
- **Managed Config Location**: `/config/emulator/xemu.toml` (version controlled, distributable)
- **Xemu Default Location**: `/config/.local/share/xemu/xemu/xemu.toml` (symlinked to managed location)
- **Benefit**: Single source of truth for configuration, no custom xemu binary required

#### Network Architecture
```
172.20.0.0/24 (xemu_lan) — functions like a home LAN
├── .1         Gateway (Docker bridge, NATs to internet via host)
├── .2         dnsmasq (DHCP + DNS server)
├── .10        xemu container (Selkies UI on ports 3000/3001)
├── .20        XLink Kai container (web UI on port 34522)
├── .50        Emulated Xbox - title interface (static IP, pcap)
├── .51        Emulated Xbox - debug interface (static IP, pcap)
└── .100-.200  DHCP pool (available for future devices)
```

#### Network Capabilities Chain
1. **Build time** ([Dockerfile](Dockerfile#L38-L41)): `ldconfig` + `setcap` baked into image
2. **Runtime** ([10-xemu-setcap](config/custom-cont-init.d/10-xemu-setcap)): Re-applied as root during s6-overlay init
3. **Why both?**: Build-time caps can be lost if the binary is updated. Runtime script ensures caps are always present.

#### Why setcap Requires ldconfig
- `setcap` on a binary causes Linux to strip `LD_LIBRARY_PATH` (same security mechanism as `setuid`)
- xemu's AppImage bundles libraries in `/opt/xemu/usr/lib/` and relies on `LD_LIBRARY_PATH` to find them
- Solution: Register the library path via `/etc/ld.so.conf.d/xemu.conf` + `ldconfig`, which is NOT stripped by `setcap`

---

## Current Status

**Working:**
- xemu launches and runs in CPU-only mode (no GPU required)
- Bridged networking via pcap backend on eth0 — no permission errors
- Emulated Xbox debug kit reachable at 172.20.0.50 (title) and 172.20.0.51 (debug) on the Docker bridge
- Both Xbox MACs (00:50:f2:97:c1:2a/2b) visible in host ARP table
- UDP 3074 (gaming) confirmed open on the emulated Xbox
- dnsmasq providing DNS resolution on the bridge network
- XLink Kai running and accessible on port 34522
- Selkies web UI accessible on ports 3000/3001
- Configuration symlink management working
- Gamepad passthrough enabled via Selkies

**Known Limitations:**
- DHCP does not work for the emulated Xbox (Docker bridges don't forward raw Layer 2 broadcasts from pcap); use static IP instead
- TCP ports 731 (XDK) and 21 (FTP) require their respective services to be running on the emulated Xbox
- .50 (title interface) does not respond to ICMP ping (normal Xbox behavior); .51 (debug interface) does

### Xbox Dashboard Network Configuration

The emulated Xbox uses static IPs configured inside the Xbox Dashboard (stored in the qcow2 disk image, not in git). If restoring from a fresh disk image, reconfigure these settings manually:

**Title Interface (primary):**
| Setting | Value |
|---------|-------|
| IP Address | `172.20.0.50` |
| Subnet Mask | `255.255.255.0` |
| Default Gateway | `172.20.0.1` |
| Primary DNS | `172.20.0.2` |

**Debug Interface (XDK):**
| Setting | Value |
|---------|-------|
| IP Address | `172.20.0.51` |
| Subnet Mask | `255.255.255.0` |
| Default Gateway | `172.20.0.1` |
| Primary DNS | `172.20.0.2` |

**How to set:** In xemu, open **Xbox Dashboard → Settings → Network Settings → Manual**, then enter the values above for each interface.

---

## About This Fork

This is a modified version of the [LinuxServer.io xemu container](https://github.com/linuxserver/docker-xemu).

### Upstream Repository
- **Original**: https://github.com/linuxserver/docker-xemu
- **Base Image**: `ghcr.io/linuxserver/baseimage-selkies:ubuntunoble`

### Key Differences from Upstream
1. **Additional Packages**: Added `libusb-1.0-0`, `wmctrl`, and `xdotool` for USB support and automation
2. **Custom Configuration Management**: Xemu config managed via symlinks for clean, distributable setup
3. **Organized Storage**: User-level modifications stored in `/config/emulator/` for easy distribution
4. **Bridged Networking**: pcap backend with `setcap` + `ldconfig` for raw socket access on Docker bridge
5. **Custom Bridge Network**: `xemu_lan` (172.20.0.0/24) with static IPs and dnsmasq for DNS
6. **XLink Kai**: System link gaming over the internet via dedicated container
7. **Enhanced Documentation**: Inline documentation, changelog, and setup guide

### Distribution Strategy

**Repository Contents:**
- Docker configuration and build files (Dockerfiles, docker-compose.yml)
- Startup scripts and xemu configuration management
- Network init scripts (custom-cont-init.d)
- dnsmasq configuration
- Small configuration files (`xemu.toml`)
- Documentation (CHANGELOG.md, SETUP.md)

**Separate Distribution (Not in Git):**
- Large disk images (~3.6GB):
  - Xbox disk image (`xbox_hdd.qcow2`)
  - Game ISOs (`*.iso`)
- BIOS files (`*.bin`) **ARE included** in the repository (total ~1MB)
- See [SETUP.md](SETUP.md) for download instructions

**Benefits:**
- **Small repo size**: ~10MB instead of ~3.6GB
- **Flexible hosting**: Large disk images can be hosted on Google Drive, MEGA, etc.
- **Easy updates**: Update disk image without git history bloat
- **Simple setup**: Most files included, only large disk image needs downloading

---

## Versioning Notes

This changelog tracks changes specific to this fork. For upstream LinuxServer.io xemu changes, see:
- https://github.com/linuxserver/docker-xemu/commits/master
