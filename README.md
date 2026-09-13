# HexStrike AI MCP Agents v6.0

MCP server untuk agentic cybersecurity - 150+ security tools terintegrasi, terhubung ke **Claude AI** via ngrok tunnel.

---

## Prasyarat

| Tool | Cek | Install (Kali/Debian) |
|------|-----|-----------------------|
| Python 3.10+ | `python3 --version` | sudah ada di Kali Linux |
| pip | `pip3 --version` | `apt install python3-pip` |
| git | `git --version` | `apt install git` |
| curl | `curl --version` | `apt install curl` |

> **ngrok tidak perlu install manual** - launcher otomatis download dan extract.

---

## Cara Pakai Step by Step

### Step 1 - Clone Repository

```bash
git clone https://github.com/burstbullet666-bit/fix222.git
cd fix222
```

---

### Step 2 - Buat Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

> Tanda berhasil: prompt terminal berubah jadi `(venv) root@mazzdaffa:~$`

Untuk nonaktifkan venv setelah selesai:

```bash
deactivate
```

---

### Step 3 - Install Dependencies

```bash
pip install -r requirements.txt
```

> Butuh 5-15 menit karena ada package besar seperti `angr`, `pwntools`, `mitmproxy`.

Kalau ada yang gagal, install bertahap:

```bash
# Core (wajib)
pip install flask requests aiohttp mcp psutil tqdm

# Web & browser automation
pip install beautifulsoup4 selenium webdriver-manager

# Security tools (opsional, skip jika error)
pip install mitmproxy pwntools angr bcrypt
```

---

### Step 4 - Isi ngrok Authtoken

1. Buka https://dashboard.ngrok.com/get-started/your-authtoken
2. Daftar gratis dan copy authtoken kamu
3. Edit file `ngrok_config.json`:

```json
{
  "authtoken": "ISI_TOKEN_NGROK_KAMU_DI_SINI",
  "region": "ap"
}
```

> Region `ap` = Asia Pacific (paling cepat untuk Indonesia).
> Opsi lain: `us`, `eu`, `au`, `jp`, `in`, `sa`

---

### Step 5 - Jalankan HexStrike

```bash
python3 launch_hexstrike_v5.py
```

**Pertama kali jalan**, launcher otomatis:
- Cek port tersedia (auto-rotate jika bentrok)
- Download ngrok jika belum ada (ada progress bar)
- Extract dan `chmod +x` ngrok otomatis
- Start HexStrike REST API server di port **9888**
- Start MCP server di port **9889**
- Aktifkan ngrok tunnel dan dapat URL publik

**Output jika berhasil:**

```
=========================================================
  HexStrike AI Launcher v5.0 - Smart Port Manager
=========================================================

[OK]    HexStrike Server running (PID: 12345) port 9888
[OK]    HexStrike MCP listening port 9889
[OK]    Ngrok active -> https://abcd-1234-5678.ngrok-free.app
[*]     Connector URL disimpan ke hexstrike-ai-mcp.json
```

---

### Step 6 - Hubungkan ke Claude AI

1. Buka file `hexstrike-ai-mcp.json` yang terbuat otomatis
2. Copy nilai `connector_url`:

```json
{
  "connector_url": "https://abcd-1234-5678.ngrok-free.app/mcp"
}
```

3. Buka **Claude.ai** klik foto profil klik **Settings**
4. Pilih tab **Connectors** klik **Add custom connector**
5. Paste URL connector klik **Connect**
6. **Selesai!** Claude sekarang bisa pakai 150+ HexStrike security tools

---

## Penggunaan Selanjutnya (Setelah Setup Awal)

Cukup jalankan ini setiap kali mau pakai:

```bash
cd fix222
source venv/bin/activate
python3 launch_hexstrike_v5.py
```

> **Penting:** URL ngrok berubah setiap restart.
> Update connector URL di Claude setiap ada URL baru dari `hexstrike-ai-mcp.json`.

---

## Troubleshooting

### Error: No module named mcp.server.fastmcp
mcp SDK v2.x sudah rename FastMCP ke MCPServer. File repo ini sudah di-fix.
```bash
pip install mcp>=2.0.0
```

### Port sudah dipakai
Launcher auto-rotate. Atau pilih custom:
```bash
python3 launch_hexstrike_v5.py
# Pilih menu 3 untuk custom port
```

### ngrok gagal connect atau timeout
Cek authtoken di `ngrok_config.json` sudah benar dan aktif.

### Permission denied ngrok
```bash
chmod +x ngrok
```

### pip install error di angr atau pwntools
```bash
sudo apt install -y python3-dev build-essential libffi-dev
pip install pwntools angr
```

### Venv tidak aktif setelah buka terminal baru
```bash
cd fix222
source venv/bin/activate
```

---

## Struktur File

```
fix222/
|-- hexstrike_server.py      # Flask REST API server (port 9888)
|-- hexstrike_mcp.py         # MCP server 150+ security tools (port 9889)
|-- launch_hexstrike_v5.py   # MAIN LAUNCHER - gunakan ini
|-- launch_hexstrike.py      # Launcher versi lama (backup)
|-- requirements.txt         # Python dependencies
|-- hexstrike-ai-mcp.json    # Connector URL Claude (auto-generate saat run)
|-- ngrok_config.json        # ISI AUTHTOKEN NGROK KAMU DI SINI
|-- hexstrike_ports.json     # Port aktif yang dipakai (auto-generate)
```

---

## Changelog v6.0

### Fix mcp SDK v2.x

| Sebelum (mcp 1.x) | Sesudah (mcp 2.x) |
|---|---|
| from mcp.server.fastmcp import FastMCP | from mcp.server.mcpserver import MCPServer as FastMCP |
| mcp.settings.host = args.mcp_host | mcp.run(host=args.mcp_host, ...) |
| mcp.settings.port = args.mcp_port | mcp.run(..., port=int(args.mcp_port)) |
| mcp.settings.transport_security = ... | mcp.run(..., transport_security=_ts) |

### Auto-download ngrok

- Download .zip dari Equinox CDN secara otomatis
- Fallback ke .tgz jika .zip gagal
- Deteksi .tgz lokal yang sudah ada (tidak download ulang)
- Progress bar via tqdm
- chmod +x dan tambah ke PATH otomatis

---

## Lisensi

MIT License
