"""Offline checks of scripts/refresh_data.py's HTTP retry logic (no network access)."""

from __future__ import annotations

import http.client
import io
import json
from typing import Any

import pytest

from scripts import refresh_data


class _Response(io.BytesIO):
    """A minimal stand-in for the object ``urllib.request.urlopen`` returns."""

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def _serve(monkeypatch: pytest.MonkeyPatch, outcomes: list[Any]) -> list[int]:
    """Stub urlopen: each call pops an outcome (bytes to return, or an exception to raise)."""
    calls: list[int] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> _Response:
        calls.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)

    monkeypatch.setattr(refresh_data.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(refresh_data.time, "sleep", lambda seconds: None)
    return calls


def test_fetch_json_returns_decoded_body(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, [json.dumps([{"pages": 1}, []]).encode()])
    assert refresh_data.fetch_json("https://example.invalid/x", 1, 3) == [{"pages": 1}, []]
    assert len(calls) == 1


def test_incomplete_read_is_retried_then_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A body cut off mid-transfer (http.client.IncompleteRead) must use the retries."""
    truncated = [http.client.IncompleteRead(b"[") for _ in range(4)]
    calls = _serve(monkeypatch, truncated)
    with pytest.raises(refresh_data.RefreshError, match="IncompleteRead"):
        refresh_data.fetch_json("https://example.invalid/x", 1, 3)
    assert len(calls) == 4  # first attempt + 3 retries


def test_incomplete_read_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, [http.client.IncompleteRead(b""), b'[{"pages": 1}, [1]]'])
    assert refresh_data.fetch_json("https://example.invalid/x", 1, 3) == [{"pages": 1}, [1]]
    assert len(calls) == 2


def test_non_json_body_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, [b"<html>", b"not json", b"[{}, []]"])
    assert refresh_data.fetch_json("https://example.invalid/x", 1, 2) == [{}, []]
    assert len(calls) == 3
