"""The Pages skip decision must use verified inputs from the live site."""
from contextlib import contextmanager
from copy import deepcopy
import json

import pytest
import requests

from best_eleven import pages


@pytest.fixture
def inputs(tmp_path):
    source_state = tmp_path / "sources.json"
    source_state.write_text(json.dumps({
        "matches": {"sha256": "a" * 64},
        "people": {"sha256": "b" * 64},
    }), encoding="utf-8")
    return pages.build_inputs(source_state, "revision", {"python": "3.12.10"})


def mock_live(monkeypatch, published):
    @contextmanager
    def get(url, **kwargs):
        assert url == pages.PUBLISHED_INPUTS
        assert kwargs["params"] == {"run": "100-1"}

        class Response:
            def raise_for_status(self):
                if isinstance(published, requests.HTTPError):
                    raise published

            def json(self):
                if isinstance(published, ValueError):
                    raise published
                return published

        yield Response()

    monkeypatch.setattr(pages.requests, "get", get)


def test_scheduled_match_skips_rebuild(monkeypatch, inputs):
    mock_live(monkeypatch, deepcopy(inputs))
    assert not pages.needs_build("schedule", inputs, "100-1")


@pytest.mark.parametrize("field", ["matches", "people", "revision", "runtime", "schema"])
def test_change_since_last_publication_requires_build(monkeypatch, inputs, field):
    published = deepcopy(inputs)
    values = published["sourceDigests"] if field in published["sourceDigests"] else published
    values[field] = "older"
    mock_live(monkeypatch, published)
    assert pages.needs_build("schedule", inputs, "100-1")


@pytest.mark.parametrize("published", [requests.HTTPError("404"), ValueError("invalid JSON"), [], {}])
def test_missing_or_invalid_live_provenance_requires_build(monkeypatch, inputs, published):
    mock_live(monkeypatch, published)
    assert pages.needs_build("schedule", inputs, "100-1")


def test_unreachable_live_metadata_requires_build(monkeypatch, inputs):
    def offline(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(pages.requests, "get", offline)
    assert pages.needs_build("schedule", inputs, "100-1")


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "schedule"])
def test_recovery_and_missing_local_inputs_do_not_depend_on_live_metadata(monkeypatch, inputs, event):
    def unexpected_request(*args, **kwargs):
        pytest.fail("A forced build should not read publication metadata")

    monkeypatch.setattr(pages.requests, "get", unexpected_request)
    assert pages.needs_build(event, None if event == "schedule" else inputs, "100-1")


def test_incomplete_local_sources_cannot_seed_provenance(tmp_path):
    source_state = tmp_path / "sources.json"
    source_state.write_text('{"matches": {"sha256": "invalid"}, "people": {"sha256": "invalid"}}', encoding="utf-8")
    assert pages.build_inputs(source_state, "revision", {}) is None
