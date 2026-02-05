# Plan: Add Tailscale Subnet Routing to docker-bridged-xemu

## Prerequisites

- VPS firewall port 41641/udp must be open (already done)
- Tailscale account with Windows PC already joined to tailnet
- CLAUDE.md already removed from GitHub tracking (commit `d88740b` on `main`)

## Critical Lessons from Failed First Attempt

### 1. xemu.toml on GitHub is STALE

The committed `xemu.toml` has wrong values that were never updated in git:

```toml
# WRONG (what's in git):
backend = 'udp'
hdd_path = '/config/emulator/xbox_hdd.qcow2'

# CORRECT (what the running system actually uses):
backend = 'pcap'
hdd_path = '/config/emulator/iguana-dev.qcow2'
```

The `pcap` backend with `netif = 'eth0'` is what makes bridged networking work (Xbox at 172.20.0.50/51 on the Docker bridge). The `udp` backend is for XLink Kai tunnel mode only. xemu auto-saves toml changes through its UI, but those were never committed.

**Action required:** Fix xemu.toml as part of this branch. Add the pcap section:

```toml
[net]
enable = true
backend = 'pcap'

[net.pcap]
netif = 'eth0'

[net.udp]
bind_addr = '0.0.0.0:9968'
remote_addr = 'localhost:34523'
```

### 2. ethtool is NOT installed in the overlay image

The `10-xemu-setcap` init script runs `ethtool -K eth0 tx off 2>/dev/null || true`. The `|| true` suppresses the error, so it silently fails. **TX checksum offloading is NOT disabled**, which means all inbound TCP to the Xbox (FTP, XBDM) will time out while ping works.

The old full-build Dockerfile installed ethtool. The current overlay Dockerfile (`FROM lscr.io/linuxserver/xemu:latest`) only installs `wmctrl`.

**Action required:** Add `ethtool` to the Dockerfile's `apt-get install` line.

### 3. Work from ONE directory only

The first attempt used two directories:
- `/home/docker/bridged-xemu/` — running containers
- `/tmp/.../scratchpad/docker-bridged-xemu/` — git operations

This caused constant confusion about which had the right files and which branch was checked out where.

**Rule:** Stop the running containers first. Check out the feature branch directly in `/home/docker/bridged-xemu/`. Do all work there. No scratchpad clone.

### 4. Don't clone fresh unless necessary

Cloning fresh loses runtime state (xemu.toml auto-saved values, SSL certs generated at first boot, xlinkkai config). If you must clone fresh, you need to copy back:
- `config/emulator/*.qcow2` (disk images)
- `config/emulator/*.bin` (BIOS — these ARE in git though)
- `config/emulator/xemu.toml` (but verify it's correct, see lesson 1)
- `config/games/*.iso`
- `config/xlinkkai/` (XLink Kai state)
- `config/ssl/` (self-signed certs, regenerated on first boot if missing)

---

## Part A: Remove CLAUDE.md from GitHub — COMPLETED

Pushed as `d88740b` on `main`. CLAUDE.md removed from tracking, added to `.gitignore`.

---

## Part B: Tailscale in Docker (on `feature/tailscale`)

### What This Does

Run Tailscale as a 5th container on the `xemu_lan` bridge network. It advertises `172.20.0.0/24` as a subnet route so the user's Windows PC can directly reach all container and Xbox IPs. Entire stack stays in Docker — no host-level Tailscale install, no host firewall changes, fully reproducible from docker-compose.yml.

### Why Container Instead of Host

- Everything defined in docker-compose.yml — portable, reproducible
- No host packages to install or maintain
- No UFW/iptables edits on the host
- `docker compose up -d` brings up the full stack including VPN access
- Clean separation: host stays vanilla

### Architecture

```
Windows PC (Tailscale client)
  → WireGuard tunnel (encrypted, NAT-traversing)
  → Tailscale container (172.20.0.4) on xemu_lan bridge
  → Docker bridge (Layer 2)
  → 172.20.0.51:731 (Xbox XBDM), 172.20.0.50:21 (Xbox FTP), etc.
```

The Tailscale container sits on the same bridge as all other services. It can reach every IP on the bridge directly — including the pcap-injected Xbox IPs (.50, .51) — because it's on a different bridge port than xemu (no hairpin issue).

### Step 1: Prepare the branch

```bash
cd /home/docker/bridged-xemu
docker compose down
git checkout -b feature/tailscale
```

### Step 2: Fix Dockerfile (add ethtool)

Add `ethtool` to the `apt-get install` line in `Dockerfile`. Without this, TX checksum offloading fix silently fails and all TCP to the Xbox is broken.

### Step 3: Fix xemu.toml

Change `backend = 'udp'` to `backend = 'pcap'` and add `[net.pcap]` section with `netif = 'eth0'`. Change `hdd_path` from `xbox_hdd.qcow2` to `iguana-dev.qcow2`.

### Step 4: Modify docker-compose.yml

Add tailscale service, comment out xbdm-relay (don't delete — keep for fallback), add `tailscale-state` volume.

```yaml
  tailscale:
    image: tailscale/tailscale:latest
    container_name: xemu-tailscale
    hostname: xemu-vps
    cap_add:
      - NET_ADMIN
      - NET_RAW
    sysctls:
      - net.ipv4.ip_forward=1
    environment:
      - TS_EXTRA_ARGS=--advertise-routes=172.20.0.0/24 --accept-dns=false
      - TS_STATE_DIR=/var/lib/tailscale
    volumes:
      - tailscale-state:/var/lib/tailscale
    ports:
      - 41641:41641/udp
    networks:
      xemu_lan:
        ipv4_address: 172.20.0.4
    restart: unless-stopped
```

Top-level volumes:
```yaml
volumes:
  tailscale-state:
```

Key details:
- `NET_ADMIN` + `NET_RAW`: required for WireGuard tunnel and subnet routing
- `net.ipv4.ip_forward=1`: enables packet forwarding inside the container
- `TS_STATE_DIR` + named volume: persists auth across restarts (no re-login)
- Port 41641/udp: enables direct WireGuard connections (without this, Tailscale falls back to DERP relay — higher latency but still works)
- `--accept-dns=false`: prevents Tailscale from overwriting container DNS

### Step 5: Build and start

```bash
docker compose up -d --build
```

### Step 6: Authenticate Tailscale

```bash
docker logs xemu-tailscale
```

First run shows an auth URL. Visit it in a browser to add the node to the tailnet.

### Step 7: Approve subnet route in Tailscale admin console

- Go to https://login.tailscale.com/admin/machines
- Find `xemu-vps` node → Edit route settings → enable `172.20.0.0/24`
- User's Windows Tailscale client auto-accepts approved subnet routes

### Step 8: Verify from Windows PC

1. `tailscale ping xemu-vps` — confirm direct connection (not relayed)
2. `ping 172.20.0.51` — Xbox debug interface responds
3. `Test-NetConnection -ComputerName 172.20.0.51 -Port 731` — XBDM reachable
4. Assembly → set Xbox IP to `172.20.0.51` → take screenshot
5. FileZilla → connect directly to `172.20.0.50:21` (no SOCKS proxy) → browse files
6. Browser → `https://172.20.0.10:3001` — xemu web UI

### Step 9: If TCP to Xbox IPs fails but ping works

Same checksum offloading bug — but this time on the Tailscale container. The Tailscale container forwards packets from the Windows PC to the Docker bridge. If the kernel applies checksum offloading to those forwarded packets, the Xbox will drop them.

Test first. If broken, add ethtool to the Tailscale container entrypoint:
```yaml
    entrypoint: /bin/sh
    command: >
      -c "apk add --no-cache ethtool > /dev/null 2>&1;
          ethtool -K eth0 tx off 2>/dev/null || true;
          exec /usr/local/bin/containerboot"
```

Or check if the Tailscale image is Debian-based (use `apt-get` instead of `apk`).

### Step 10: Update docs and commit

**Files to modify:**

| File | Change |
|------|--------|
| `Dockerfile` | Add `ethtool` to apt-get install |
| `docker-compose.yml` | Add `tailscale` service, add `tailscale-state` volume, comment out `xbdm-relay` |
| `config/emulator/xemu.toml` | Fix backend to pcap, fix hdd_path to iguana-dev.qcow2 |
| `README.md` | Full rewrite — current version describes old docker-xemu repo |
| `FTP-Fix.md` | Add Tailscale as primary method, demote SSH-based to fallbacks |
| `CHANGELOG.md` | Full rewrite — current version references nonexistent files |

```bash
git add -A
git commit -m "Add Tailscale subnet routing, fix xemu.toml and Dockerfile"
git push -u origin feature/tailscale
```

---

## What Tailscale Does NOT Replace

- **XLink Kai** — still needed for Layer 2 system link gaming (Tailscale is Layer 3 only)
- **VS Code Remote-SSH** — still used for editing files on the VPS
- **pcap immediate mode shim** — still needed for xemu packet reception
- **TX checksum offloading fix** — still needed inside xemu container

## What Tailscale Eliminates

- xbdm-relay socat container (commented out, not deleted)
- SSH `LocalForward` for XBDM port 731
- `ssh -D 1080` SOCKS proxy for FTP
- FileZilla SOCKS5 proxy configuration
- Windows port conflicts (731 busy, auto-increment to 732)

---

## Execution Order

1. ~~Remove CLAUDE.md from GitHub tracking~~ — DONE (`d88740b`)
2. `docker compose down` in `/home/docker/bridged-xemu/`
3. `git checkout -b feature/tailscale`
4. Fix Dockerfile (add ethtool)
5. Fix xemu.toml (pcap backend, iguana-dev.qcow2)
6. Modify docker-compose.yml (add tailscale, comment out xbdm-relay)
7. `docker compose up -d --build`
8. Authenticate Tailscale (visit auth URL)
9. Approve subnet route in Tailscale admin console
10. Verify end-to-end from Windows PC
11. Fix checksum on Tailscale container if needed
12. Rewrite README.md, CHANGELOG.md, update FTP-Fix.md
13. Commit and push `feature/tailscale` branch

## Verification Checklist

From Windows PC after Tailscale is up:
- [ ] `ping 172.20.0.10` (xemu container)
- [ ] `ping 172.20.0.51` (Xbox debug interface)
- [ ] Assembly connects to `172.20.0.51:731` and takes screenshot
- [ ] FileZilla connects to `172.20.0.50:21` — list files, download works (passive mode)
- [ ] `https://172.20.0.10:3001` loads xemu web UI in browser
- [ ] `http://172.20.0.20:34522` loads XLink Kai web UI
- [ ] XLink Kai still works for system link gaming (unaffected)
