# cairo-station

Run xemu (original Xbox emulator) in Docker with a real IP address on your network — not NAT. Connect debuggers, FTP, and XLink Kai directly from any device via Tailscale, no SSH tunnels required.

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)

---

## What's Running

| Container | Address | What It Does |
|-----------|---------|--------------|
| xemu | 172.20.0.49 | The emulator — browser UI on `:3001`, QMP on `:4444` |
| Xbox | 172.20.0.50 / .51 | Emulated Xbox — FTP on `:21`, XBDM debug on `:731` |
| StatsBorg | 172.20.0.45 | Reads Halo 2 post-game stats — web viewer on `:8080` |
| XLink Kai | 172.20.0.25 | Online system link gaming — config UI on `:34522` |
| Tailscale | 172.20.0.10 | Lets you reach all of 172.20.0.0/24 from anywhere |
| Grafana | 172.20.0.41 | Network health dashboards on `:3000` |

---

## Setup

**You'll need:** A Linux host, Docker with Compose V2, and a free [Tailscale](https://tailscale.com) account.

```bash
git clone https://github.com/Roasted-Codes/cairo-station.git
cd cairo-station
```

Put your Xbox files in `services/xemu/data/emulator/`:

| File | What It Is |
|------|------------|
| `mcpx_1.0.bin` | Boot ROM |
| `CerbiosDebug.bin` | BIOS |
| `iguana-eeprom.bin` | EEPROM |
| `iguana-dev.qcow2` | Hard drive image (~3.6 GB — not in git, get this separately) |

```bash
docker compose build
docker compose up -d
```

**Connect Tailscale:** Watch logs until an auth URL appears, click it to log in, then go to the [Tailscale admin console](https://login.tailscale.com/admin/machines) and approve the `172.20.0.0/24` subnet route.

```bash
docker compose logs tailscale
```

Once that's done, every device on your Tailscale network can reach the Xbox directly.

---

## Access

| | Address |
|-|---------|
| xemu browser UI (gamepad works) | `https://172.20.0.49:3001` |
| FTP — username `xbox`, password `xbox` | `172.20.0.50:21` |
| XBDM debug (Assembly, Cxbx, etc.) | `172.20.0.51:731` |
| StatsBorg stats viewer | `http://172.20.0.45:8080` |
| XLink Kai | `http://172.20.0.25:34522` |
| Grafana | `http://172.20.0.41:3000` — login: admin / admin |

---

## Under the Hood

Getting xemu's pcap networking to work inside Docker required solving three bugs that cause silent failures:

1. **Packet receive never works** — xemu can send packets but the receive socket never fires. Fixed by injecting a small shim ([`pcap_immediate.c`](services/xemu/data/emulator/pcap_immediate.c)) that enables immediate mode on the capture device.

2. **TCP always times out even though ping works** — the Linux kernel leaves TCP checksums partially filled, expecting the NIC hardware to complete them. On a software bridge, nothing ever does, so the Xbox drops every TCP packet. Fixed by disabling TX checksum offloading on the container's network interface at startup.

3. **Containers can't talk to the Xbox's IPs** — Linux bridge networking blocks a container from reaching an IP that sits on the same bridge port as itself. Tailscale sidesteps this completely: remote traffic routes through the subnet router instead of across the bridge.

Full details in [CLAUDE.md](CLAUDE.md).

---

## Troubleshooting

| Symptom | What to Check |
|---------|---------------|
| xemu won't start | File paths in `services/xemu/data/emulator/xemu.toml` under `[sys.files]` |
| Sends but never receives packets | `docker exec xemu cat /etc/ld.so.preload` — must include `pcap_immediate.so` |
| Ping works but FTP/XBDM times out | `docker exec xemu ethtool -k eth0 \| grep tx-checksumming` — must show `off` |
| Can't reach anything remotely | Tailscale admin console — the `172.20.0.0/24` route must be approved |
| Gamepad stops working in-game | xemu auto-saves input config — run `git diff services/xemu/data/emulator/xemu.toml` and revert if port bindings changed |

---

[xemu.app](https://xemu.app) · [XLink Kai](https://www.teamxlink.co.uk) · [Tailscale](https://tailscale.com) · [Issues](https://github.com/Roasted-Codes/cairo-station/issues)

GPL-3.0 — built on [linuxserver/docker-xemu](https://github.com/linuxserver/docker-xemu)
