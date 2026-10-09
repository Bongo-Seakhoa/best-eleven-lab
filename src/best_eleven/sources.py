"""Acquire Cricsheet's archive and people register.

Downloads are conditional (ETag / Last-Modified), verified as complete zip
archives before replacing the previous copy, and recorded with a SHA-256 in
data/raw/sources.json.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

USER_AGENT = "best-eleven-lab/0.3 (https://github.com/Bongo-Seakhoa/best-eleven-lab)"
SOURCES = {
    "matches": {"url": "https://cricsheet.org/downloads/all_json.zip", "file": "all_json.zip"},
    "people": {"url": "https://cricsheet.org/register/people.csv", "file": "people.csv"},
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(key: str, raw_dir: str | Path = "data/raw", *, force: bool = False, log=print) -> dict:
    src = SOURCES[key]
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    state_path = raw / "sources.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    prev = state.get(key, {})
    dest = raw / src["file"]
    headers = {"User-Agent": USER_AGENT}
    if dest.exists() and not force:
        if prev.get("etag"):
            headers["If-None-Match"] = prev["etag"]
        if prev.get("last_modified"):
            headers["If-Modified-Since"] = prev["last_modified"]
    with requests.get(src["url"], headers=headers, stream=True, timeout=120) as r:
        if r.status_code == 304:
            log(f"{key}: unchanged since {prev.get('fetched_at')}")
            return {**prev, "status": "unchanged"}
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            shutil.copyfileobj(r.raw, f, length=1 << 20)
        etag, modified = r.headers.get("ETag"), r.headers.get("Last-Modified")
    if dest.suffix == ".zip":
        with zipfile.ZipFile(tmp) as z:
            bad = z.testzip()
            if bad:
                tmp.unlink()
                raise ValueError(f"corrupt archive member {bad}")
    tmp.replace(dest)
    rec = {"url": src["url"], "file": str(dest), "bytes": dest.stat().st_size, "sha256": _sha256(dest),
           "etag": etag, "last_modified": modified,
           "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "downloaded"}
    state[key] = rec
    state_path.write_text(json.dumps(state, indent=1))
    log(f"{key}: downloaded {rec['bytes']:,} bytes")
    return rec
