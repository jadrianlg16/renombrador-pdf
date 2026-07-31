from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_START_PORT = 8765
DEFAULT_END_PORT = 8799


def port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_available_port(host: str, requested: int | None = None) -> int:
    if requested is not None:
        if not port_is_available(host, requested):
            raise RuntimeError(
                f"El puerto {requested} ya esta ocupado. Cierra el otro programa "
                "o ejecuta launcher.py sin --port para elegir uno automaticamente."
            )
        return requested

    for port in range(DEFAULT_START_PORT, DEFAULT_END_PORT + 1):
        if port_is_available(host, port):
            return port
    raise RuntimeError(
        f"No encontre un puerto libre entre {DEFAULT_START_PORT} y {DEFAULT_END_PORT}."
    )


def wait_until_ready(url: str, process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    health_url = f"{url}/api/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"El servidor termino antes de iniciar (codigo {process.returncode})."
            )
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                payload = json.load(response)
                if response.status == 200 and payload.get("app_id") == "renombrador-pdf":
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.25)
    raise RuntimeError("El servidor no respondio dentro de 30 segundos.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicia el Renombrador PDF local.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    os.chdir(BASE_DIR)
    os.environ.setdefault("PDF_INPUT_DIR", str(BASE_DIR / "data" / "inbox"))
    os.environ.setdefault("PDF_STATE_DIR", str(BASE_DIR / "data" / "state"))

    tesseract_default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if "TESSERACT_CMD" not in os.environ and tesseract_default.exists():
        os.environ["TESSERACT_CMD"] = str(tesseract_default)

    try:
        port = find_available_port(args.host, args.port)
    except RuntimeError as exc:
        print(f"\nERROR: {exc}\n", file=sys.stderr)
        return 1

    url = f"http://{args.host}:{port}"
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        args.host,
        "--port",
        str(port),
    ]

    print("\nRenombrador PDF")
    print(f"Carpeta de PDF: {os.environ['PDF_INPUT_DIR']}")
    print(f"Direccion: {url}")
    print("Para cerrar el sistema, presiona Ctrl+C en esta ventana.\n")

    process = subprocess.Popen(command, cwd=BASE_DIR, env=os.environ.copy())
    try:
        wait_until_ready(url, process)
        if not args.no_browser:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        return process.wait()
    except KeyboardInterrupt:
        print("\nCerrando el Renombrador PDF...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 0
    except RuntimeError as exc:
        print(f"\nERROR: {exc}\n", file=sys.stderr)
        process.terminate()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
