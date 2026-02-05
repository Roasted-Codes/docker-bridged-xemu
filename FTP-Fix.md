# FTP Access to the Emulated Xbox

## Background

The emulated Xbox runs an FTP server (XBMC FileZilla) on `172.20.0.50:21` inside a Docker bridge network. This IP is private — it only exists on the Vultr server inside Docker. Default credentials: `xbox` / `xbox`.

Two bugs had to be fixed before FTP could work at all:

1. **pcap immediate mode** — xemu couldn't receive ANY packets (including FTP connections) due to libpcap 1.9+ TPACKET_V3 requiring `pcap_set_immediate_mode()`. Fixed with the `pcap_immediate.so` shim in `/etc/ld.so.preload`.

2. **TCP checksum offloading** — The host kernel writes placeholder TCP checksums expecting hardware to complete them. Packets to pcap-injected Xbox IPs go through a software bridge where no hardware fills in the checksum. The Xbox silently drops packets with bad checksums. Symptom: `ping` works but `nc` to any TCP port times out. Fixed with `ethtool -K eth0 tx off` in the init script.

Both fixes are applied automatically by `config/custom-cont-init.d/10-xemu-setcap` at container startup.

## Option 1: lftp from VS Code Terminal (Simplest)

You're already connected to the server via VS Code Remote SSH. Open a terminal and connect directly:

```bash
lftp -u xbox,xbox 172.20.0.50
```

Basic commands:
```
ls                    # list Xbox drives (C, D, E, F, etc.)
cd E:/                # enter the E: drive
ls                    # list files
get somefile.xbe      # download a file to the server
put myfile.txt        # upload a file from the server to Xbox
mirror E:/games/ /home/docker/xbox-backup/   # download entire folder
quit
```

Files land on the Vultr server's filesystem. Use VS Code's file explorer to move them to/from your PC (drag & drop, or right-click > Download).

**Flow: Home PC ↔ (VS Code drag & drop) ↔ Vultr server ↔ (lftp) ↔ Xbox**

Install lftp if needed: `sudo apt-get install -y lftp`

## Option 2: FileZilla / WinSCP with SOCKS Proxy (GUI)

FTP uses port 21 for commands but opens random ports for every file transfer (passive mode). A simple port forward only handles port 21 — file transfers fail. A SOCKS proxy routes ALL traffic through SSH, solving this automatically.

### Step 1: Create a SOCKS proxy

**PuTTY (Windows):**
1. Open PuTTY, load your Vultr connection
2. Go to Connection > SSH > Tunnels
3. Source port: `1080`, select **Dynamic**, click **Add**
4. Connect to the server
5. Leave PuTTY open

**Windows Terminal / PowerShell / macOS Terminal:**
```
ssh -D 1080 user@your-vultr-ip
```
Leave the window open.

### Step 2: Configure FileZilla

1. Edit > Settings > Connection > Generic Proxy
2. Select **SOCKS5**
3. Proxy host: `127.0.0.1`
4. Proxy port: `1080`
5. Leave username/password blank
6. Click OK

### Step 3: Connect

1. In FileZilla's quickconnect bar:
   - Host: `172.20.0.50`
   - Username: `xbox`
   - Password: `xbox`
   - Port: `21`
2. Click Quickconnect
3. Xbox drives appear in the right panel
4. Drag and drop files between your PC and the Xbox

### WinSCP alternative

1. New Site > Advanced > Connection > Proxy
2. Proxy type: **SOCKS5**
3. Proxy hostname: `127.0.0.1`, port: `1080`
4. Back in main dialog: Host: `172.20.0.50`, Port: `21`, User: `xbox`, Password: `xbox`
5. Protocol: **FTP**

## How the network path works

```
Your PC (FileZilla)
  ↓ SOCKS5 proxy (localhost:1080)
  ↓ SSH tunnel (encrypted)
Vultr Server
  ↓ Docker bridge (172.20.0.0/24)
  ↓ server is gateway at 172.20.0.1
xemu Container (172.20.0.10)
  ↓ pcap on eth0
Emulated Xbox (172.20.0.50)
  ↓ XBMC FileZilla FTP server on port 21
```

No firewall ports need to be opened. No changes to docker-compose. All FTP traffic is encrypted inside the SSH tunnel.

## Why opening port 21 on Vultr doesn't work

The Xbox FTP server listens on `172.20.0.50:21` — a private Docker bridge IP. Docker's port mapping (`ports: "21:21"` in docker-compose) maps ports on the *container's* IP (172.20.0.10), not the Xbox's pcap-injected IP. Even with port 21 open on Vultr's firewall, nothing connects to the Xbox. You'd need a socat relay inside the container PLUS handle FTP passive mode data ports — it's not worth the complexity.

## Troubleshooting

**"Connection timed out" on port 21:**
- Is the Xbox running and booted to XBMC dashboard?
- Is the FTP server enabled in XBMC settings?
- Check that the checksum offloading fix is applied: `docker exec xemu-halo2-server ethtool -k eth0 | grep tx-checksum`
  - `tx-checksum-ip-generic: off` = good
  - `tx-checksum-ip-generic: on` = bad, run `docker exec xemu-halo2-server ethtool -K eth0 tx off`

**"Connection refused" on port 21:**
- FTP server is not running. Enable it in XBMC Settings > Network > Services.

**SOCKS proxy not working:**
- Make sure the SSH session with `-D 1080` is still open
- Check FileZilla proxy settings (must be SOCKS5, not SOCKS4 or HTTP)
