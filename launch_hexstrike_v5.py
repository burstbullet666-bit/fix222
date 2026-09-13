#!/usr/bin/env python3
"""
HexStrike AI Launcher v5.0 — Smart Port Manager
- Menu: 1) Jalankan, 2) Cek port, 3) Custom port
- Auto-detect port bentrok
- Auto-rotate port (minimal 5 kandidat)
- Notifikasi jelas saat port berubah
"""
import subprocess
import json
import time
import sys
import os
import signal
import shutil
import socket
import getpass
import threading
import urllib.request
import zipfile
import tarfile
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
from pathlib import Path

HEXSTRIKE_DIR = Path(__file__).parent

# ─── PORT CONFIG (bisa dioverride lewat menu) ───────────────────────────────
DEFAULT_SERVER_PORT = 9888
DEFAULT_MCP_PORT    = 9889

# Kandidat port untuk rotate (minimal 5 per slot)
SERVER_PORT_CANDIDATES = [9888, 9988, 19888, 19988, 29888, 29988]
MCP_PORT_CANDIDATES    = [9889, 9989, 19889, 19989, 29889, 29989]

# ─── FILE PATHS ─────────────────────────────────────────────────────────────
CONFIG_FILE  = HEXSTRIKE_DIR / "hexstrike-ai-mcp.json"
NGROK_CONFIG = HEXSTRIKE_DIR / "ngrok_config.json"
ERROR_LOG    = HEXSTRIKE_DIR / "hexstrike_error.log"
PORT_CONFIG  = HEXSTRIKE_DIR / "hexstrike_ports.json"  # simpan port aktif

DOWNLOAD_TIMEOUT = 15

CORE_FILES = {
    "hexstrike_server.py": "https://raw.githubusercontent.com/0x4m4/hexstrike-ai/master/hexstrike_server.py",
    "hexstrike_mcp.py":    "https://raw.githubusercontent.com/0x4m4/hexstrike-ai/master/hexstrike_mcp.py",
}

processes      = []
server_log_fh  = None
log_lock       = threading.Lock()

# ─── COLORS ─────────────────────────────────────────────────────────────────
class C:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

def ok(msg):   print(f"{C.GREEN}[OK]{C.RESET}    {msg}")
def fail(msg): print(f"{C.RED}[FAIL]{C.RESET}  {msg}")
def warn(msg): print(f"{C.YELLOW}[!]{C.RESET}     {msg}")
def info(msg): print(f"{C.CYAN}[*]{C.RESET}     {msg}")

def banner():
    print(f"""
{C.BOLD}{C.CYAN}
╔══════════════════════════════════════════════════════════════╗
║         HexStrike AI Launcher v5.0 — Smart Port Manager      ║
╚══════════════════════════════════════════════════════════════╝{C.RESET}
""")

# ─── PORT UTILITIES ─────────────────────────────────────────────────────────
def is_port_in_use(port: int) -> bool:
    """Cek apakah port sedang dipakai (TCP)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False

def scan_used_ports(port_list: list) -> dict:
    """Scan daftar port, return dict {port: status}."""
    result = {}
    for p in port_list:
        result[p] = is_port_in_use(p)
    return result

def find_free_port(candidates: list) -> int | None:
    """Cari port bebas dari daftar kandidat."""
    for p in candidates:
        if not is_port_in_use(p):
            return p
    return None

def auto_rotate_ports(server_candidates: list, mcp_candidates: list):
    """
    Auto-cari pasangan port bebas dari kandidat.
    Minimal 5 kandidat tersedia per slot.
    Return (server_port, mcp_port) atau exit kalau semua bentrok.
    """
    print()
    info(f"Auto-rotate port dari {len(server_candidates)} kandidat...")

    server_port = find_free_port(server_candidates)
    mcp_port    = find_free_port(mcp_candidates)

    if server_port is None:
        fail(f"Semua {len(server_candidates)} kandidat SERVER PORT bentrok!")
        fail("Kandidat: " + ", ".join(str(p) for p in server_candidates))
        sys.exit(1)

    if mcp_port is None:
        fail(f"Semua {len(mcp_candidates)} kandidat MCP PORT bentrok!")
        fail("Kandidat: " + ", ".join(str(p) for p in mcp_candidates))
        sys.exit(1)

    return server_port, mcp_port

def save_port_config(server_port: int, mcp_port: int):
    """Simpan port aktif ke file JSON."""
    data = {
        "server_port": server_port,
        "mcp_port":    mcp_port,
        "saved_at":    time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(PORT_CONFIG, "w") as f:
        json.dump(data, f, indent=2)

def load_port_config() -> tuple[int, int] | None:
    """Load port dari file config kalau ada."""
    if PORT_CONFIG.exists():
        try:
            with open(PORT_CONFIG) as f:
                data = json.load(f)
            return data["server_port"], data["mcp_port"]
        except Exception:
            pass
    return None

def notify_port_change(old_server, old_mcp, new_server, new_mcp):
    """Tampilkan notifikasi perubahan port."""
    print()
    print(f"{C.YELLOW}{'━'*62}{C.RESET}")
    print(f"{C.YELLOW}{C.BOLD}  ⚠  NOTIFIKASI: PORT BERUBAH{C.RESET}")
    print(f"{C.YELLOW}{'━'*62}{C.RESET}")
    print(f"  Server Port : {C.RED}{old_server}{C.RESET}  →  {C.GREEN}{new_server}{C.RESET}")
    print(f"  MCP Port    : {C.RED}{old_mcp}{C.RESET}  →  {C.GREEN}{new_mcp}{C.RESET}")
    print(f"{C.YELLOW}{'━'*62}{C.RESET}")
    print(f"  {C.CYAN}File config diupdate otomatis: hexstrike_ports.json{C.RESET}")
    print(f"{C.YELLOW}{'━'*62}{C.RESET}")
    print()

# ─── MENU ───────────────────────────────────────────────────────────────────
def menu_cek_port():
    """Menu 2: Tampilkan status semua kandidat port."""
    all_ports = sorted(set(SERVER_PORT_CANDIDATES + MCP_PORT_CANDIDATES))
    # tambah port umum yang mungkin bentrok
    extra = [8080, 8888, 8889, 9888, 9889, 4040, 4041]
    all_ports = sorted(set(all_ports + extra))

    print(f"\n{C.BOLD}{'PORT':>8}   {'STATUS':^12}   KETERANGAN{C.RESET}")
    print("─" * 50)
    for p in all_ports:
        used = is_port_in_use(p)
        status = f"{C.RED}TERPAKAI{C.RESET}" if used else f"{C.GREEN}BEBAS   {C.RESET}"
        role = ""
        if p == 8080:  role = "← Burp Proxy"
        if p == 4040:  role = "← ngrok dashboard"
        if p in SERVER_PORT_CANDIDATES: role += " [server kandidat]"
        if p in MCP_PORT_CANDIDATES:    role += " [mcp kandidat]"
        print(f"  {p:>6}   {status}   {role}")
    print()

def menu_custom_port() -> tuple[int, int]:
    """Menu 3: Input manual port."""
    print(f"\n{C.CYAN}Custom Port Mode{C.RESET}")
    print("Masukkan port yang ingin digunakan (kosongkan = pakai default)\n")

    # Server port
    while True:
        try:
            val = input(f"  Server Port [{DEFAULT_SERVER_PORT}]: ").strip()
            server_port = int(val) if val else DEFAULT_SERVER_PORT
            if not (1024 <= server_port <= 65535):
                warn("Port harus antara 1024-65535, coba lagi.")
                continue
            if is_port_in_use(server_port):
                warn(f"Port {server_port} sedang terpakai!")
                force = input("  Tetap pakai? (y/N): ").strip().lower()
                if force != "y":
                    continue
            break
        except ValueError:
            warn("Masukkan angka yang valid.")

    # MCP port
    while True:
        try:
            val = input(f"  MCP Port    [{DEFAULT_MCP_PORT}]: ").strip()
            mcp_port = int(val) if val else DEFAULT_MCP_PORT
            if not (1024 <= mcp_port <= 65535):
                warn("Port harus antara 1024-65535, coba lagi.")
                continue
            if mcp_port == server_port:
                warn("MCP port tidak boleh sama dengan server port!")
                continue
            if is_port_in_use(mcp_port):
                warn(f"Port {mcp_port} sedang terpakai!")
                force = input("  Tetap pakai? (y/N): ").strip().lower()
                if force != "y":
                    continue
            break
        except ValueError:
            warn("Masukkan angka yang valid.")

    return server_port, mcp_port

def show_main_menu() -> int:
    """Tampilkan menu utama, return pilihan."""
    print(f"{C.BOLD}  Pilih Opsi:{C.RESET}")
    print(f"  {C.GREEN}[1]{C.RESET} Jalankan HexStrike (auto-detect & rotate port kalau bentrok)")
    print(f"  {C.CYAN}[2]{C.RESET} Cek status port (semua kandidat)")
    print(f"  {C.YELLOW}[3]{C.RESET} Custom port manual")
    print(f"  {C.RED}[0]{C.RESET} Keluar")
    print()
    while True:
        try:
            choice = input("  Pilihan [0-3]: ").strip()
            if choice in ("0", "1", "2", "3"):
                return int(choice)
            warn("Pilih 0, 1, 2, atau 3.")
        except (ValueError, KeyboardInterrupt):
            print()
            sys.exit(0)

# ─── CORE LOGIC (sama seperti v4.5, diadaptasi) ─────────────────────────────
def cleanup(signum=None, frame=None):
    print("\n[*] Shutting down...")
    for p in processes:
        try:
            p.terminate()
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try: p.kill()
            except Exception: pass
        except Exception: pass
    if server_log_fh and not server_log_fh.closed:
        server_log_fh.close()
    sys.exit(0)

signal.signal(signal.SIGINT,  cleanup)
signal.signal(signal.SIGTERM, cleanup)

def ensure_core_files():
    for fname, url in CORE_FILES.items():
        fpath = HEXSTRIKE_DIR / fname
        if fpath.exists():
            ok(f"{fname} found")
            continue
        info(f"Downloading {fname}...")
        try:
            with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as r:
                fpath.write_bytes(r.read())
            ok(f"{fname} downloaded")
        except Exception as e:
            fail(f"Gagal download {fname}: {e}")
            sys.exit(1)

def get_ngrok_token() -> str:
    if NGROK_CONFIG.exists():
        try:
            with open(NGROK_CONFIG) as f:
                data = json.load(f)
            token = data.get("authtoken", "").strip()
            if token:
                ok("Ngrok token loaded from config")
                return token
        except Exception:
            pass
    token = getpass.getpass("  Masukkan ngrok authtoken: ").strip()
    if not token:
        fail("Token kosong. Exit.")
        sys.exit(1)
    with open(NGROK_CONFIG, "w") as f:
        json.dump({"authtoken": token, "region": "ap"}, f, indent=2)
    os.chmod(NGROK_CONFIG, 0o600)
    ok(f"Token disimpan ke {NGROK_CONFIG}")
    return token


NGROK_DOWNLOAD_URL  = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.zip"
NGROK_TGZ_FALLBACK  = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz"

def _download_with_progress(url: str, dest) -> None:
    """Download file dari URL ke dest dengan progress bar."""
    info(f"Downloading {url} ...")
    with urllib.request.urlopen(url) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        chunk_size = 8192
        downloaded = 0
        try:
            from tqdm import tqdm as _tqdm
            bar = _tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) if total else None
        except ImportError:
            bar = None
        with open(dest, "wb") as f:
            while True:
                data = resp.read(chunk_size)
                if not data:
                    break
                f.write(data)
                downloaded += len(data)
                if bar:
                    bar.update(len(data))
                elif total:
                    print(f"\r  {int(downloaded*100/total)}% ({downloaded//1024} KB)", end="", flush=True)
        if bar:
            bar.close()
        else:
            print()
    ok(f"{dest.name} downloaded ({downloaded//1024} KB)")

def _finalize_ngrok(local_ngrok) -> None:
    """Set chmod +x dan tambahkan direktori ke PATH."""
    if not local_ngrok.exists():
        fail("ngrok binary tidak ditemukan setelah ekstrak!")
        sys.exit(1)
    os.chmod(local_ngrok, 0o755)
    os.environ["PATH"] = str(local_ngrok.parent) + ":" + os.environ.get("PATH", "")
    ok(f"ngrok siap: {local_ngrok}")

def ensure_ngrok():
    """Pastikan ngrok tersedia. Auto-download + unzip jika belum ada."""
    local_ngrok = HEXSTRIKE_DIR / "ngrok"
    # 1. Cek di PATH
    if shutil.which("ngrok"):
        ok("ngrok binary found in PATH")
        return
    # 2. Cek file lokal
    if local_ngrok.exists() and os.access(local_ngrok, os.X_OK):
        ok(f"ngrok binary found: {local_ngrok}")
        os.environ["PATH"] = str(HEXSTRIKE_DIR) + ":" + os.environ.get("PATH", "")
        return
    warn("ngrok tidak ditemukan. Memulai auto-download...")
    tgz_local = HEXSTRIKE_DIR / "ngrok-v3-stable-linux-amd64.tgz"
    zip_local = HEXSTRIKE_DIR / "ngrok-download.zip"
    # 3. Ekstrak dari .tgz lokal jika ada
    if tgz_local.exists():
        info(f"File .tgz lokal ditemukan: {tgz_local}")
        try:
            with tarfile.open(tgz_local, "r:gz") as tar:
                tar.extractall(HEXSTRIKE_DIR)
            _finalize_ngrok(local_ngrok)
            return
        except Exception as e:
            warn(f"Gagal ekstrak .tgz lokal: {e}. Coba download ulang...")
    # 4. Download .zip dari Equinox CDN
    try:
        _download_with_progress(NGROK_DOWNLOAD_URL, zip_local)
        info("Mengekstrak ngrok dari ZIP...")
        with zipfile.ZipFile(zip_local, "r") as z:
            z.extractall(HEXSTRIKE_DIR)
        zip_local.unlink(missing_ok=True)
        _finalize_ngrok(local_ngrok)
        return
    except Exception as e:
        warn(f"Gagal download ZIP: {e}")
        if zip_local.exists():
            zip_local.unlink(missing_ok=True)
    # 5. Fallback: download .tgz
    try:
        _download_with_progress(NGROK_TGZ_FALLBACK, tgz_local)
        info("Mengekstrak ngrok dari TGZ...")
        with tarfile.open(tgz_local, "r:gz") as tar:
            tar.extractall(HEXSTRIKE_DIR)
        _finalize_ngrok(local_ngrok)
        return
    except Exception as e:
        fail(f"Semua metode auto-download ngrok gagal: {e}")
        fail("Install manual dari: https://ngrok.com/download")
        sys.exit(1)

def start_ngrok(token: str, port: int) -> str:
    info(f"Starting ngrok on port {port}...")
    env = os.environ.copy()
    env["NGROK_AUTHTOKEN"] = token
    ngrok_log = HEXSTRIKE_DIR / "ngrok.log"
    proc = subprocess.Popen(
        ["ngrok", "http", str(port), f"--log={ngrok_log}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env, start_new_session=True,
    )
    processes.append(proc)

    public_url = None
    for _ in range(25):
        time.sleep(1.2)
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3) as r:
                data = json.loads(r.read().decode())
                for t in data.get("tunnels", []):
                    url  = t.get("public_url", "")
                    addr = str(t.get("config", {}).get("addr", ""))
                    if url.startswith("https://") and addr.endswith(str(port)):
                        public_url = url
                        break
            if public_url:
                break
        except Exception:
            continue

    if not public_url:
        fail(f"Gagal mendapatkan ngrok URL untuk port {port}")
        cleanup()
    ok(f"Ngrok active → {public_url}")
    return public_url

def wait_for_port(port: int, timeout: int = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False

def start_server(server_port: int):
    global server_log_fh
    info("Starting HexStrike Server...")
    server_script = HEXSTRIKE_DIR / "hexstrike_server.py"
    if not server_script.exists():
        fail(f"File tidak ditemukan: {server_script}")
        sys.exit(1)

    env = os.environ.copy()
    env["HEXSTRIKE_PORT"] = str(server_port)  # server baca dari env

    server_log_fh = open(ERROR_LOG, "w")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(server_script)],
        cwd=HEXSTRIKE_DIR,
        env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, start_new_session=True,
    )
    processes.append(proc)

    def reader():
        for line in proc.stdout:
            print(line, end="")
            with log_lock:
                if server_log_fh and not server_log_fh.closed:
                    server_log_fh.write(line)
                    server_log_fh.flush()

    threading.Thread(target=reader, daemon=True).start()
    time.sleep(1.5)

    if proc.poll() is not None:
        fail(f"Server gagal start (exit code {proc.returncode})")
        fail(f"Lihat log: {ERROR_LOG}")
        sys.exit(1)

    if not wait_for_port(server_port, timeout=15):
        fail(f"Server tidak listening di port {server_port} dalam 15 detik")
        sys.exit(1)

    ok(f"HexStrike Server running (PID: {proc.pid}) → port {server_port}")
    return proc

def start_mcp_http(server_port: int, mcp_port: int):
    info("Starting HexStrike MCP (streamable-http)...")
    mcp_script = HEXSTRIKE_DIR / "hexstrike_mcp.py"
    proc = subprocess.Popen(
        [sys.executable, "-u", str(mcp_script),
         "--server",    f"http://127.0.0.1:{server_port}",
         "--transport", "streamable-http",
         "--mcp-host",  "127.0.0.1",
         "--mcp-port",  str(mcp_port)],
        cwd=HEXSTRIKE_DIR, start_new_session=True,
    )
    processes.append(proc)

    if not wait_for_port(mcp_port, timeout=15):
        fail(f"hexstrike_mcp.py tidak listening di port {mcp_port}")
        sys.exit(1)

    ok(f"HexStrike MCP running (PID: {proc.pid}) → port {mcp_port}")
    return proc

def update_mcp_config(public_url: str):
    mcp_endpoint = public_url.rstrip("/") + "/mcp"
    config = {
        "note":          "Paste 'connector_url' ke Claude Web → Settings → Connectors → Add custom connector",
        "connector_url": mcp_endpoint,
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    ok(f"MCP endpoint → {mcp_endpoint}")

def run_hexstrike(server_port: int, mcp_port: int):
    """Jalankan semua service dengan port yang sudah ditentukan."""
    ensure_core_files()
    ensure_ngrok()
    token = get_ngrok_token()

    print()
    start_server(server_port)
    start_mcp_http(server_port, mcp_port)
    public_url = start_ngrok(token, mcp_port)
    update_mcp_config(public_url)
    save_port_config(server_port, mcp_port)

    print("\n" + f"{C.GREEN}{'═'*62}{C.RESET}")
    print(f"{C.BOLD}{C.GREEN}  ✓  HEXSTRIKE READY!{C.RESET}")
    print(f"{C.GREEN}{'═'*62}{C.RESET}")
    print(f"  {C.BOLD}Connector URL (Claude Web):{C.RESET} {public_url}/mcp")
    print(f"  Local MCP     : http://127.0.0.1:{mcp_port}/mcp")
    print(f"  Local Backend : http://127.0.0.1:{server_port}")
    print(f"  Config file   : {CONFIG_FILE}")
    print(f"  Port config   : {PORT_CONFIG}")
    print(f"{C.GREEN}{'═'*62}{C.RESET}")
    print(f"\n  {C.YELLOW}Tekan Ctrl+C untuk stop{C.RESET}\n")

    already_warned = False
    try:
        while True:
            time.sleep(1)
            for p in processes:
                if (p.poll() is not None
                        and any("hexstrike_server" in str(a) for a in p.args)
                        and not already_warned):
                    warn(f"HexStrike Server berhenti (exit {p.returncode}) — script tetap jalan")
                    warn(f"Cek log: {ERROR_LOG}")
                    already_warned = True
    except KeyboardInterrupt:
        cleanup()

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    banner()

    while True:
        choice = show_main_menu()

        if choice == 0:
            print("  Bye!")
            sys.exit(0)

        elif choice == 2:
            menu_cek_port()
            # kembali ke menu setelah cek port

        elif choice == 3:
            server_port, mcp_port = menu_custom_port()

            # Notifikasi kalau beda dari default/saved
            saved = load_port_config()
            old_s = saved[0] if saved else DEFAULT_SERVER_PORT
            old_m = saved[1] if saved else DEFAULT_MCP_PORT
            if server_port != old_s or mcp_port != old_m:
                notify_port_change(old_s, old_m, server_port, mcp_port)

            run_hexstrike(server_port, mcp_port)

        elif choice == 1:
            info("Mengecek port yang tersedia...")

            # Load port terakhir sebagai referensi
            saved = load_port_config()
            old_s = saved[0] if saved else DEFAULT_SERVER_PORT
            old_m = saved[1] if saved else DEFAULT_MCP_PORT

            # Cek apakah port default/saved masih bebas
            s_used = is_port_in_use(old_s)
            m_used = is_port_in_use(old_m)

            if not s_used and not m_used:
                ok(f"Port server {old_s} & MCP {old_m} bebas → pakai langsung")
                server_port, mcp_port = old_s, old_m
            else:
                if s_used: warn(f"Server port {old_s} sedang TERPAKAI!")
                if m_used: warn(f"MCP port    {old_m} sedang TERPAKAI!")
                warn("Auto-rotate mencari port pengganti...")
                server_port, mcp_port = auto_rotate_ports(
                    SERVER_PORT_CANDIDATES, MCP_PORT_CANDIDATES
                )
                notify_port_change(old_s, old_m, server_port, mcp_port)

            run_hexstrike(server_port, mcp_port)

if __name__ == "__main__":
    main()
