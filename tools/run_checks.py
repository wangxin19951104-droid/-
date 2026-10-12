"""Run regression checks using temporary fixtures, with paid endpoints blocked."""
import compileall
import ipaddress
import re
import shutil
import sys
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ENDPOINTS = set()
ORIGINAL_BIND = ThreadingHTTPServer.server_bind

def fixture_bind(server):
    ORIGINAL_BIND(server)
    host, port = server.server_address[:2]
    if ipaddress.ip_address(host).is_loopback:
        ALLOWED_ENDPOINTS.add((host, port))

def block_live_connections(event, args):
    if event != "socket.connect":
        return
    address = args[1]
    if not isinstance(address, tuple) or address[:2] not in ALLOWED_ENDPOINTS:
        raise RuntimeError("Offline tests blocked a connection to a non-fixture endpoint.")

def main():
    if not shutil.which("ffmpeg"):
        print("FFmpeg is required for local video fixtures. Add ffmpeg to PATH.")
        return 2
    if not compileall.compile_dir(ROOT, quiet=1, rx=re.compile(r"[\\/](?:\.venv|cache)[\\/]")):
        return 1
    sys.path.insert(0, str(ROOT))
    sys.addaudithook(block_live_connections)
    with patch.object(ThreadingHTTPServer, "server_bind", fixture_bind):
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    raise SystemExit(main())
