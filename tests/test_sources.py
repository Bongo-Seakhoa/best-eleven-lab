"""Network-free download recovery tests with synthetic HTTP/ZIP/CSV payloads."""
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from best_eleven import sources


def archive_bytes(payload=b"synthetic match fixture"):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("match.json", payload)
    return result.getvalue()


class Response:
    def __init__(self, body=b"", *, status=200, headers=None, chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self.chunks = [body] if chunks is None else chunks
        self.closed = False
        self.body_reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size):
        self.body_reads += 1
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


@pytest.fixture
def http(monkeypatch):
    calls, sleeps = [], []
    monkeypatch.setattr(sources.time, "sleep", sleeps.append)

    def setup(*responses):
        queue = iter(responses)

        def get(url, **kwargs):
            calls.append({"url": url, **kwargs, "headers": dict(kwargs["headers"])})
            response = next(queue)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(sources.requests, "get", get)
        return calls, sleeps

    return setup


def cached(raw, key="matches"):
    body = archive_bytes(b"previous verified fixture") if key == "matches" else b"identifier,name,unique_name\np1,Player,Player\n"
    dest = raw / sources.SOURCES[key]["file"]
    dest.write_bytes(body)
    state = {key: {"etag": '"old"', "last_modified": "Wed, 14 Oct 2026 22:22:07 GMT",
                   "sha256": hashlib.sha256(body).hexdigest(), "fetched_at": "2026-10-14T22:30:00+00:00"}}
    snapshot = json.dumps(state, indent=1).encode()
    (raw / "sources.json").write_bytes(snapshot)
    return body, snapshot


def assert_preserved(raw, body, state, key="matches"):
    assert (raw / sources.SOURCES[key]["file"]).read_bytes() == body
    assert (raw / "sources.json").read_bytes() == state
    assert not list(raw.glob("*.part"))


def test_invalid_zip_retries_then_commits_only_verified_response(tmp_path, http):
    cached(tmp_path)
    bad = Response(b"<html>temporary upstream error</html>", headers={"ETag": '"bad"'})
    payload = archive_bytes()
    good = Response(payload, headers={"ETag": '"new"', "Content-Length": str(len(payload))})
    calls, sleeps = http(bad, good)
    logs = []
    result = sources.fetch("matches", tmp_path, log=logs.append)
    assert result["status"] == "downloaded"
    assert result["etag"] == '"new"'
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / "all_json.zip").read_bytes() == payload
    assert json.loads((tmp_path / "sources.json").read_text())["matches"] == result
    assert all(call["headers"]["If-None-Match"] == '"old"' for call in calls)
    assert bad.closed and good.closed
    assert sleeps == [1]
    assert "retrying" in logs[0]
    assert not list(tmp_path.glob("*.part"))


def test_partial_stream_is_discarded_before_next_attempt(tmp_path, http):
    broken = Response(chunks=[b"partial body", requests.exceptions.ChunkedEncodingError("interrupted")])
    payload = archive_bytes()
    good = Response(payload)
    calls, sleeps = http(broken, good)
    sources.fetch("matches", tmp_path, log=lambda _: None)
    assert len(calls) == 2 and sleeps == [1]
    assert (tmp_path / "all_json.zip").read_bytes() == payload
    assert broken.closed and good.closed
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("failure", ["zip", "crc", "connection", "timeout", "stream", "length"])
def test_exhausted_retries_raise_and_preserve_previous_source(tmp_path, http, failure):
    original, state = cached(tmp_path)
    corrupt = bytearray(archive_bytes())
    corrupt[corrupt.index(b"synthetic match fixture")] ^= 1

    def response():
        return {
            "zip": lambda: Response(b"not a ZIP"),
            "crc": lambda: Response(bytes(corrupt)),
            "connection": lambda: requests.ConnectionError("offline"),
            "timeout": lambda: requests.Timeout("timed out"),
            "stream": lambda: Response(chunks=[b"part", requests.exceptions.ChunkedEncodingError("cut short")]),
            "length": lambda: Response(archive_bytes(), headers={"Content-Length": "999999"}),
        }[failure]()

    replies = [response() for _ in range(3)]
    calls, sleeps = http(*replies)
    logs = []
    with pytest.raises((sources.InvalidDownload, requests.RequestException)):
        sources.fetch("matches", tmp_path, log=logs.append)
    assert len(calls) == 3 and sleeps == [1, 2]
    assert all(reply.closed for reply in replies if isinstance(reply, Response))
    assert "failed on attempt 3/3" in logs[-1]
    assert_preserved(tmp_path, original, state)


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_transient_http_status_retries(tmp_path, http, status):
    failed, good = Response(status=status), Response(archive_bytes())
    calls, sleeps = http(failed, good)
    sources.fetch("matches", tmp_path, log=lambda _: None)
    assert len(calls) == 2 and sleeps == [1]
    assert failed.closed and good.closed


def test_permanent_http_error_fails_once(tmp_path, http):
    original, state = cached(tmp_path)
    reply = Response(status=404)
    calls, sleeps = http(reply)
    with pytest.raises(requests.HTTPError):
        sources.fetch("matches", tmp_path, log=lambda _: None)
    assert len(calls) == 1 and not sleeps and reply.closed
    assert_preserved(tmp_path, original, state)


@pytest.mark.parametrize("after", ["3", "Wed, 14 Oct 2026 22:30:03 GMT"])
def test_short_retry_after_is_honoured(tmp_path, http, monkeypatch, after):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 14, 22, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(sources, "datetime", Clock)
    calls, sleeps = http(Response(status=503, headers={"Retry-After": after}), Response(archive_bytes()))
    sources.fetch("matches", tmp_path, log=lambda _: None)
    assert len(calls) == 2 and sleeps == [3]


def test_long_retry_after_reports_failure_instead_of_retrying_early(tmp_path, http):
    calls, sleeps = http(Response(status=429, headers={"Retry-After": "120"}))
    with pytest.raises(requests.HTTPError):
        sources.fetch("matches", tmp_path, log=lambda _: None)
    assert len(calls) == 1 and not sleeps


def test_cached_304_preserves_source_and_freshness_timestamp(tmp_path, http):
    original, state = cached(tmp_path)
    reply = Response(status=304)
    calls, sleeps = http(reply)
    result = sources.fetch("matches", tmp_path, log=lambda _: None)
    assert result["status"] == "unchanged"
    assert result["fetched_at"] == "2026-10-14T22:30:00+00:00"
    assert len(calls) == 1 and not sleeps and not reply.body_reads and reply.closed
    assert_preserved(tmp_path, original, state)


def test_304_without_cache_never_reports_success(tmp_path, http):
    calls, sleeps = http(*(Response(status=304) for _ in range(3)))
    with pytest.raises(sources.InvalidDownload, match="without a reusable"):
        sources.fetch("matches", tmp_path, log=lambda _: None)
    assert len(calls) == 3 and sleeps == [1, 2]
    assert not (tmp_path / "all_json.zip").exists()
    assert not (tmp_path / "sources.json").exists()


def test_bad_cached_checksum_forces_unconditional_recovery(tmp_path, http):
    cached(tmp_path)
    (tmp_path / "all_json.zip").write_bytes(b"damaged cache")
    payload = archive_bytes()
    calls, sleeps = http(Response(status=304), Response(payload))
    sources.fetch("matches", tmp_path, log=lambda _: None)
    assert "If-None-Match" in calls[0]["headers"]
    assert calls[1]["headers"] == {"User-Agent": sources.USER_AGENT}
    assert sleeps == [1] and (tmp_path / "all_json.zip").read_bytes() == payload


def test_force_remains_unconditional_across_retries(tmp_path, http):
    cached(tmp_path)
    calls, sleeps = http(Response(b"invalid"), Response(archive_bytes()))
    sources.fetch("matches", tmp_path, force=True, log=lambda _: None)
    assert sleeps == [1]
    assert all(call["headers"] == {"User-Agent": sources.USER_AGENT} for call in calls)


def test_people_register_html_is_retried_not_promoted(tmp_path, http):
    payload = b"identifier,name,unique_name\np2,Fixture Player,Fixture Player\n"
    calls, sleeps = http(Response(b"<html>upstream unavailable</html>"), Response(payload))
    sources.fetch("people", tmp_path, log=lambda _: None)
    assert len(calls) == 2 and sleeps == [1]
    assert (tmp_path / "people.csv").read_bytes() == payload


@pytest.mark.parametrize("last_row", [b"p2,truncated\n", b'p2,"unfinished'])
def test_malformed_later_register_row_is_retried(tmp_path, http, last_row):
    valid = b"identifier,name,unique_name\np1,Player,Player\n"
    calls, sleeps = http(Response(valid + last_row), Response(valid + b"\n"))
    sources.fetch("people", tmp_path, log=lambda _: None)
    assert len(calls) == 2 and sleeps == [1]
    assert (tmp_path / "people.csv").read_bytes() == valid + b"\n"


def test_exhausted_register_validation_preserves_previous_data(tmp_path, http):
    original, state = cached(tmp_path, "people")
    bad = original + b"p2,incomplete\n"
    calls, sleeps = http(*(Response(bad) for _ in range(3)))
    with pytest.raises(sources.InvalidDownload):
        sources.fetch("people", tmp_path, log=lambda _: None)
    assert len(calls) == 3 and sleeps == [1, 2]
    assert_preserved(tmp_path, original, state, "people")


def test_cached_register_is_validated_even_when_checksum_matches(tmp_path, http):
    valid, _ = cached(tmp_path, "people")
    invalid = valid + b"p2,incomplete\n"
    (tmp_path / "people.csv").write_bytes(invalid)
    state_path = tmp_path / "sources.json"
    state = json.loads(state_path.read_text())
    state["people"]["sha256"] = hashlib.sha256(invalid).hexdigest()
    state_path.write_text(json.dumps(state))
    calls, sleeps = http(Response(status=304), Response(valid))
    sources.fetch("people", tmp_path, log=lambda _: None)
    assert calls[1]["headers"] == {"User-Agent": sources.USER_AGENT}
    assert sleeps == [1] and (tmp_path / "people.csv").read_bytes() == valid


def test_local_write_error_is_not_retried(tmp_path, http, monkeypatch):
    original, state = cached(tmp_path)
    open_file = Path.open

    def blocked(path, *args, **kwargs):
        if path.name == "all_json.zip.part":
            raise PermissionError("synthetic local write denial")
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocked)
    reply = Response(archive_bytes())
    calls, sleeps = http(reply)
    with pytest.raises(PermissionError):
        sources.fetch("matches", tmp_path, log=lambda _: None)
    assert len(calls) == 1 and not sleeps and reply.closed
    assert_preserved(tmp_path, original, state)
