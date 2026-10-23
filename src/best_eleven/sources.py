"""Acquire Cricsheet's archive and people register.

Downloads are conditional (ETag / Last-Modified), verified as complete zip
archives before replacing the previous copy, and recorded with a SHA-256 in
data/raw/sources.json.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import time
import zipfile
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

USER_AGENT = "best-eleven-lab/0.3 (https://github.com/Bongo-Seakhoa/best-eleven-lab)"
SOURCES = {
    "matches": {"url": "https://cricsheet.org/downloads/all_json.zip", "file": "all_json.zip"},
    "people": {"url": "https://cricsheet.org/register/people.csv", "file": "people.csv"},
}
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY = 30


class InvalidDownload(ValueError):
    """The response cannot be used as the requested source file."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_download(key: str, path: Path) -> None:
    if key == "matches":
        try:
            with zipfile.ZipFile(path) as archive:
                if not archive.namelist():
                    raise zipfile.BadZipFile("empty archive")
                bad = archive.testzip()
                if bad:
                    raise zipfile.BadZipFile(f"corrupt archive member {bad}")
        except (zipfile.BadZipFile, EOFError, zlib.error) as exc:
            raise InvalidDownload(f"invalid match archive: {exc}") from exc
    else:
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = csv.reader(handle, strict=True)
                header = next(rows, [])
                if header[:3] != ["identifier", "name", "unique_name"]:
                    raise InvalidDownload("invalid people register: missing CSV header")
                count = 0
                for row in rows:
                    if not row:
                        continue
                    if len(row) != len(header):
                        raise InvalidDownload("invalid people register: incomplete CSV record")
                    count += 1
                if not count:
                    raise InvalidDownload("invalid people register: no records")
        except (UnicodeError, csv.Error) as exc:
            raise InvalidDownload(f"invalid people register: {exc}") from exc


def _retry_delay(exc: Exception, attempt: int) -> float | None:
    delay = float(2 ** (attempt - 1))
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None or not (response.status_code in (408, 429) or 500 <= response.status_code < 600):
            return None
        value = response.headers.get("Retry-After")
        if value:
            try:
                requested = float(value)
            except ValueError:
                try:
                    when = parsedate_to_datetime(value)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    requested = (when - datetime.now(timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    requested = 0
            if math.isfinite(requested):
                delay = max(delay, requested)
    # Do not retry before a server's longer Retry-After; report it instead.
    return delay if delay <= MAX_RETRY_DELAY else None


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
    tmp = dest.with_suffix(dest.suffix + ".part")
    state_tmp = state_path.with_suffix(".json.part")
    retryable = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError,
                 requests.exceptions.ContentDecodingError, requests.HTTPError, InvalidDownload)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with requests.get(src["url"], headers=headers, stream=True, timeout=120) as r:
                if r.status_code == 304:
                    conditional = "If-None-Match" in headers or "If-Modified-Since" in headers
                    if not dest.exists() or not conditional:
                        raise InvalidDownload("304 response without a reusable cached source")
                    try:
                        if prev.get("sha256") and _sha256(dest) != prev["sha256"]:
                            raise InvalidDownload("cached source checksum mismatch")
                        if key == "people" or not prev.get("sha256"):
                            _validate_download(key, dest)
                    except InvalidDownload:
                        headers = {"User-Agent": USER_AGENT}
                        raise
                    log(f"{key}: unchanged since {prev.get('fetched_at')}")
                    return {**prev, "status": "unchanged"}
                r.raise_for_status()
                with tmp.open("wb") as handle:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        handle.write(chunk)
                length = r.headers.get("Content-Length", "")
                if not r.headers.get("Content-Encoding") and length.isdigit() and tmp.stat().st_size != int(length):
                    raise InvalidDownload("incomplete response body")
                etag, modified = r.headers.get("ETag"), r.headers.get("Last-Modified")
            _validate_download(key, tmp)
            rec = {"url": src["url"], "file": str(dest), "bytes": tmp.stat().st_size, "sha256": _sha256(tmp),
                   "etag": etag, "last_modified": modified,
                   "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "downloaded"}
            state[key] = rec
            state_tmp.write_text(json.dumps(state, indent=1))
            tmp.replace(dest)
            state_tmp.replace(state_path)
            log(f"{key}: downloaded {rec['bytes']:,} bytes")
            return rec
        except retryable as exc:
            tmp.unlink(missing_ok=True)
            delay = _retry_delay(exc, attempt)
            if attempt == MAX_ATTEMPTS or delay is None:
                log(f"{key}: download failed on attempt {attempt}/{MAX_ATTEMPTS}: {exc}")
                raise
            log(f"{key}: attempt {attempt}/{MAX_ATTEMPTS} failed ({exc}); retrying in {delay:g}s")
            time.sleep(delay)
        finally:
            tmp.unlink(missing_ok=True)
            state_tmp.unlink(missing_ok=True)
