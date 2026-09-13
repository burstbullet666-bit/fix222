#!/usr/bin/env python3
"""
HexStrike AI Launcher v4.5 — Ngrok + Live Logs, no auto-shutdown on crash
Fixed: secret input, own-process-only cleanup, correct tunnel matching,
download timeout, safe log writes, real readiness check.
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
from pathlib import Path

HEXSTRIKE_DIR = Path(__file__).parent
SERVER_PORT = 9888
MCP_PORT = 9889  # port for hexstrike_mcp.py running in streamable-http mode
CONFIG_FILE = HEXSTRIKE_DIR / "hexstrike-ai-mcp.json"
NGROK_CONFIG = HEXSTRIKE_DIR / "ngrok_config.json"
ERROR_LOG = HEXSTRIKE_DIR / "hexstrike_error.log"
DOWNLOAD_TIMEOUT = 15  # seconds

CORE_FILES = {
    "hexstrike_server.py": "https://raw.githubusercontent.com/0x4m4/hexstrike-ai/master/hexstrike_server.py",
    "hexstrike_mcp.py": "https://raw.githubusercontent.com/0x4m4/hexstrike-ai/master/hexstrike_mcp.py",
}

# Track only the processes THIS script started (no more blind `pkill -f`)
processes = []
server_log_fh = None
log_lock = threading.Lock()


def cleanup(signum=None, frame=None):
    print("\n[*] Shutting down (manual)...")
    for p in processes:
        try:
            p.terminate()
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                p.kill()
            except Exception:
                pass
        except Exception:
            pass

    with log_lock:
        global server_log_fh
        if server_log_fh:
            try:
                server_log_fh.close()
            except Exception:
                pass
            server_log_fh = None

    print("[OK] Cleaned up")
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def ensure_core_files():
    print("[*] Checking core HexStrike files...")
    for name, url in CORE_FILES.items():
        dest = HEXSTRIKE_DIR / name
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"[OK] {name} OK ({dest.stat().st_size} bytes)")
            continue
        print(f"[*] Downloading {name} from upstream...")
        tmp_dest = dest.with_suffix(dest.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as resp, open(tmp_dest, "wb") as out:
                shutil.copyfileobj(resp, out)
            if tmp_dest.stat().st_size <= 1000:
                raise IOError(f"Downloaded file too small ({tmp_dest.stat().st_size} bytes) — likely corrupt/partial")
            tmp_dest.replace(dest)
            print(f"[OK] Downloaded {name} ({dest.stat().st_size} bytes)")
        except Exception as e:
            print(f"[FAIL] Gagal download {name}: {e}")
            tmp_dest.unlink(missing_ok=True)
            sys.exit(1)


def get_ngrok_token():
    token = os.getenv("NGROK_AUTHTOKEN", "").strip()
    if token:
        print("[OK] Ngrok token dari environment")
        return token
    if NGROK_CONFIG.exists():
        try:
            with open(NGROK_CONFIG) as f:
                cfg = json.load(f)
            token = cfg.get("authtoken", "").strip()
            if token and "your_ngrok" not in token.lower():
                print("[OK] Ngrok token dari ngrok_config.json")
                return token
        except Exception:
            pass

    print("\n" + "=" * 60)
    print("NGROK TOKEN REQUIRED")
    print("=" * 60)
    try:
        # getpass: input tidak ditampilkan di layar (secret-safe)
        token = getpass.getpass("Paste Ngrok Authtoken (input tersembunyi): ").strip()
    except EOFError:
        print("[FAIL] Tidak ada TTY untuk input interaktif. "
              "Set env var NGROK_AUTHTOKEN atau isi ngrok_config.json manual. Exit.")
        sys.exit(1)

    if not token:
        print("[FAIL] Token kosong. Exit.")
        sys.exit(1)

    with open(NGROK_CONFIG, "w") as f:
        json.dump({"authtoken": token, "region": "ap"}, f, indent=2)
    os.chmod(NGROK_CONFIG, 0o600)  # jangan biarkan file token world-readable
    print(f"[OK] Token disimpan ke {NGROK_CONFIG} (permission 600)")
    return token


def ensure_ngrok():
    if shutil.which("ngrok"):
        print("[OK] ngrok binary found")
        return
    print("[FAIL] ngrok tidak ditemukan. Install manual: https://ngrok.com/download")
    sys.exit(1)


def start_ngrok(token, port):
    print(f"[*] Starting ngrok on port {port}...")
    env = os.environ.copy()
    env["NGROK_AUTHTOKEN"] = token
    ngrok_log = HEXSTRIKE_DIR / "ngrok.log"
    proc = subprocess.Popen(
        ["ngrok", "http", str(port), f"--log={ngrok_log}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        start_new_session=True,
    )
    processes.append(proc)

    public_url = None
    for _ in range(25):
        time.sleep(1.2)
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3) as r:
                data = json.loads(r.read().decode())
                for t in data.get("tunnels", []):
                    url = t.get("public_url", "")
                    addr = str(t.get("config", {}).get("addr", ""))
                    # Cocokkan tunnel dengan port kita secara eksplisit,
                    # bukan asal ambil https pertama yang ketemu.
                    if url.startswith("https://") and addr.endswith(str(port)):
                        public_url = url
                        break
            if public_url:
                break
        except Exception:
            continue

    if not public_url:
        print("[FAIL] Gagal mendapatkan ngrok URL yang cocok dengan port "
              f"{port} (cek ngrok.log / tunnel lain yang mungkin bentrok)")
        cleanup()
    print(f"[OK] Ngrok active -> {public_url}")
    return public_url


def wait_for_port(port, timeout=15):
    """Cek koneksi TCP nyata ke port server, bukan cuma cek proses hidup."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def start_server():
    global server_log_fh
    print("[*] Starting HexStrike Server...")
    print(f"[*] Output juga ditulis ke: {ERROR_LOG}")
    print("-" * 60)
    server_script = HEXSTRIKE_DIR / "hexstrike_server.py"
    if not server_script.exists():
        print(f"[FAIL] File tidak ditemukan: {server_script}")
        sys.exit(1)

    server_log_fh = open(ERROR_LOG, "w")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(server_script)],
        cwd=HEXSTRIKE_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
        start_new_session=True,
    )
    processes.append(proc)

    def reader():
        for line in proc.stdout:
            print(line, end="")
            with log_lock:
                if server_log_fh and not server_log_fh.closed:
                    server_log_fh.write(line)
                    server_log_fh.flush()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    time.sleep(1.5)
    if proc.poll() is not None:
        print("-" * 60)
        print(f"[FAIL] Server gagal start (exit code {proc.returncode})")
        print(f"[FAIL] Lihat traceback di atas atau di file: {ERROR_LOG}")
        sys.exit(1)

    # Cek beneran apakah port sudah listening, bukan cuma "proses masih hidup"
    if not wait_for_port(SERVER_PORT, timeout=15):
        print("-" * 60)
        print(f"[FAIL] Server proses hidup tapi port {SERVER_PORT} tidak pernah listening "
              f"dalam 15 detik. Cek {ERROR_LOG}")
        sys.exit(1)

    print("-" * 60)
    print(f"[OK] HexStrike Server running & listening (PID: {proc.pid})")
    return proc


def start_mcp_http(server_port, mcp_port):
    print("[*] Starting HexStrike MCP (streamable-http)...")
    mcp_script = HEXSTRIKE_DIR / "hexstrike_mcp.py"
    proc = subprocess.Popen(
        [sys.executable, "-u", str(mcp_script),
         "--server", f"http://127.0.0.1:{server_port}",
         "--transport", "streamable-http",
         "--mcp-host", "127.0.0.1",
         "--mcp-port", str(mcp_port)],
        cwd=HEXSTRIKE_DIR,
        start_new_session=True,
    )
    processes.append(proc)

    if not wait_for_port(mcp_port, timeout=15):
        print(f"[FAIL] hexstrike_mcp.py tidak listening di port {mcp_port} dalam 15 detik.")
        sys.exit(1)

    print(f"[OK] HexStrike MCP (HTTP) running (PID: {proc.pid}) on port {mcp_port}")
    return proc


def update_mcp_config(public_url):
    mcp_endpoint = public_url.rstrip("/") + "/mcp"
    config = {
        "note": "Paste 'connector_url' below into Claude Web -> Settings -> Connectors -> Add custom connector",
        "connector_url": mcp_endpoint,
    }
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        print(f"[OK] MCP endpoint URL -> {mcp_endpoint}")
        return True
    except Exception as e:
        print(f"[FAIL] Gagal update config: {e}")
        return False


def main():
    print("""
+------------------------------------------------------------+
|  HexStrike AI Launcher v4.5 - no auto-shutdown on crash    |
+------------------------------------------------------------+
""")
    ensure_core_files()
    ensure_ngrok()
    token = get_ngrok_token()
    start_server()                              # Flask backend, lokal port 8888 (tidak di-tunnel)
    start_mcp_http(SERVER_PORT, MCP_PORT)       # hexstrike_mcp.py sebagai HTTP MCP server, port 8889
    public_url = start_ngrok(token, MCP_PORT)   # ngrok tunnel ke MCP server, bukan Flask backend
    update_mcp_config(public_url)

    print("\n" + "=" * 60)
    print("READY")
    print("=" * 60)
    print(f"Connector URL (Claude Web) : {public_url}/mcp")
    print(f"Local MCP    : http://127.0.0.1:{MCP_PORT}/mcp")
    print(f"Local Backend: http://127.0.0.1:{SERVER_PORT}")
    print(f"Config       : {CONFIG_FILE}")
    print("=" * 60)
    print("\n[*] Press Ctrl+C to stop manual\n")

    already_warned = False
    try:
        while True:
            time.sleep(1)
            for p in processes:
                if p.poll() is not None and "hexstrike_server" in str(p.args) and not already_warned:
                    print(f"\n[!] HexStrike Server berhenti (exit code {p.returncode}) — script TETAP JALAN")
                    print(f"[!] Cek traceback di: {ERROR_LOG}")
                    print("[!] Ngrok tunnel masih aktif tapi tidak ada backend yang jalan di port 8888")
                    print("[!] Tekan Ctrl+C kalau mau stop manual\n")
                    already_warned = True
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
