# docker-xemu

Xbox emulator with XLink Kai multiplayer and automation. Fork of [linuxserver/docker-xemu](https://github.com/linuxserver/docker-xemu).

## Quick Start

**1. Download from [Google Drive](https://drive.google.com/drive/folders/10KqAo_bU0cdI_nOkcUG2paMmZ4phiBaY?usp=drive_link):**
- `xbox_hdd.qcow2` (3.6GB) → `config/emulator/xbox_hdd.qcow2`
- `halo2_r1e_xiso.iso` → `config/games/halo2_r1e_xiso.iso`

**2. Run:**
```bash
docker compose up -d
```

**3. Access:**
- Xemu: https://localhost:3000 (via ssh tunnel)
- XLink Kai: http://localhost:34522

## Configuration

**Ports:**
- `3000/3001` - Xemu (HTTP/HTTPS)
- `34522` - XLink Kai web interface
- `34523/UDP` - XLink Kai traffic

**Environment variables:**
```yaml
PUID=1000          # User ID
PGID=1000          # Group ID
TZ=Etc/UTC         # Timezone
```

See [docker-compose.yml](docker-compose.yml) for full config.

## What's Different?

This fork adds:
- XLink Kai for online multiplayer
- Passleader automation (`passleader_v3.sh`)
- Additional packages: `libusb-1.0`, `wmctrl`, `xdotool`

See [CHANGELOG.md](CHANGELOG.md) for complete modifications.

## Links

- [Issues](https://github.com/Roasted-Codes/docker-xemu/issues)
- [Upstream](https://github.com/linuxserver/docker-xemu)
- [xemu Docs](https://xemu.app/docs/)
