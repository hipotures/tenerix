#!/usr/bin/env python3
"""Fetch the immutable reviewed dependency locally; never installs or runs it."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
PIN = json.loads((ROOT / "provenance.json").read_text())
DEST = ROOT / ".upstream"


def verify():
    for name, expected in PIN["runtime_sha256"].items():
        actual = hashlib.sha256((DEST / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Upstream checksum mismatch: {name}")


if __name__ == "__main__":
    if not DEST.exists():
        subprocess.run(["git", "clone", "--no-checkout", PIN["url"], str(DEST)], check=True)
        subprocess.run(["git", "-C", str(DEST), "checkout", "--detach", PIN["commit"]], check=True)
    verify()
    print(f"Verified upstream {PIN['commit']}")
