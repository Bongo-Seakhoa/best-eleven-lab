"""Allowlisted, bounded, conditional downloads. Public data, no paid database."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
import json
import os
import time
import zipfile
from .ingest import ingest_archive, utcnow

@dataclass(frozen=True)
class Source:
    key: str
    title: str
    filename: str
    priority: int = 1
    @property
    def url(self):
        return "https://cricsheet.org/downloads/" + self.filename

SOURCES = {s.key: s for s in [
    Source("tests_male", "Men · national · Test", "tests_male_json.zip"),
    Source("odis_male", "Men · national · ODI", "odis_male_json.zip"),
    Source("t20s_male", "Men · national · T20I", "t20s_male_json.zip"),
    Source("tests_female", "Women · national · Test", "tests_female_json.zip"),
    Source("odis_female", "Women · national · ODI", "odis_female_json.zip"),
    Source("t20s_female", "Women · national · T20I", "t20s_female_json.zip"),
    Source("south_africa_male", "South Africa men · all formats", "south_africa_male_json.zip"),
    Source("ipl", "Indian Premier League", "ipl_male_json.zip", 2),
    Source("sa20", "SA20", "sat_male_json.zip", 2),
    Source("bbl", "Big Bash League", "bbl_male_json.zip", 2),
    Source("psl", "Pakistan Super League", "psl_male_json.zip", 2),
]}
MAX_DOWNLOAD_BYTES = 250_000_000

class SameProviderRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlparse(newurl)
        if p.scheme != "https" or p.hostname != "cricsheet.org":
            raise ValueError("Refusing redirect outside the provider allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def file_digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch_source(db, key: str, cache: str | Path, *, force=False) -> dict:
    if key not in SOURCES:
        raise ValueError("Unknown source key")
    source = SOURCES[key]
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    previous = db.execute("SELECT * FROM fetches WHERE source_key=?", (key,)).fetchone()
    dest = Path(previous["archive_path"]) if previous else cache / source.filename
    import tempfile
    with tempfile.NamedTemporaryFile(prefix="download-", suffix=".part", dir=cache, delete=False) as f:
        temp = Path(f.name)
    headers = {"User-Agent": "BestElevenLab/0.1 (cricket research)", "Accept": "application/zip"}
    if previous and previous["status"] == "ok" and dest.exists() and not force:
        if previous["etag"]:
            headers["If-None-Match"] = previous["etag"]
        if previous["last_modified"]:
            headers["If-Modified-Since"] = previous["last_modified"]
    opener = build_opener(SameProviderRedirect())
    received = {}
    for attempt in range(3):
        try:
            with opener.open(Request(source.url, headers=headers), timeout=60) as response:
                if int(response.headers.get("Content-Length", 0)) > MAX_DOWNLOAD_BYTES:
                    raise ValueError("Download exceeds the configured limit")
                size = 0
                with temp.open("wb") as f:
                    while chunk := response.read(1 << 20):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise ValueError("Download exceeds the configured limit")
                        f.write(chunk)
                received = response.headers
            if not zipfile.is_zipfile(temp):
                raise ValueError("Provider returned a non-ZIP response. Download via your browser and import the archive instead.")
            digest = file_digest(temp)
            dest = cache / (digest + ".zip")
            if dest.exists():
                temp.unlink()
            else:
                os.replace(temp, dest)
            break
        except HTTPError as exc:
            if exc.code == 304 and previous and dest.exists():
                return {"source": key, "status": "not_modified", "counts": {"unchanged": previous["match_count"]}, "errors": []}
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"Provider download failed (HTTP {exc.code}). Browser-downloaded ZIPs can be imported.") from exc
            time.sleep(2 ** attempt)
        except (URLError, TimeoutError, OSError) as exc:
            if attempt == 2:
                raise RuntimeError("Provider is unreachable. Existing data is retained; use a locally downloaded ZIP.") from exc
            time.sleep(2 ** attempt)
        finally:
            if temp.exists():
                temp.unlink()
    result = ingest_archive(db, dest, key, source.url)
    digest = file_digest(dest)
    count = db.execute("SELECT COUNT(*) FROM match_sources WHERE source_key=?", (key,)).fetchone()[0]
    with db:
        db.execute("INSERT OR REPLACE INTO fetches VALUES (?,?,?,?,?,?,?,?,?)", (
            key, source.url, utcnow(), received.get("ETag"), received.get("Last-Modified"), digest, str(dest), count, result["status"]))
    receipt = {**result, "url": source.url, "archive_sha256": digest, "fetched_at": utcnow()}
    dest.with_suffix(".receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def import_source_archive(db, archive, source_key, provenance, cache):
    """Retain one content-addressed raw copy and an acquisition receipt for an upload."""
    import shutil
    archive, cache = Path(archive), Path(cache)
    if archive.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise ValueError("Archive exceeds the configured limit")
    if not zipfile.is_zipfile(archive):
        raise ValueError("The uploaded file is not a ZIP archive")
    if not source_key or len(source_key) > 100:
        raise ValueError("Invalid source key")
    digest = file_digest(archive)
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / (digest + '.zip')
    if not dest.exists():
        temp = dest.with_suffix('.part')
        try:
            shutil.copyfile(archive, temp)
            os.replace(temp, dest)
        finally:
            temp.unlink(missing_ok=True)
    result = ingest_archive(db, dest, source_key, provenance)
    fetched_at = utcnow()
    count = db.execute('SELECT COUNT(*) FROM match_sources WHERE source_key=?', (source_key,)).fetchone()[0]
    with db:
        db.execute('INSERT OR REPLACE INTO fetches VALUES (?,?,?,?,?,?,?,?,?)', (source_key, provenance, fetched_at, None, None, digest, str(dest), count, result['status']))
    receipt = {**result, 'archive_sha256':digest, 'fetched_at':fetched_at, 'url':provenance, 'acquisition':'user-supplied archive; origin asserted, not independently verified'}
    dest.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt
