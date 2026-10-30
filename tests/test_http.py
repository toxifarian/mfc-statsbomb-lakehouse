import pytest

from pitchlake.sources import http as h


class FakeResp:
    def __init__(self, status, content=b"[]", headers=None):
        self.status_code, self.content, self.headers, self.text = (
            status,
            content,
            headers or {},
            content.decode(),
        )


def _client(monkeypatch, responses):
    c = h.HttpClient(backoff_base_s=0, requests_per_second=0, max_retries=3)
    seq = iter(responses)
    monkeypatch.setattr(c.session, "get", lambda url, timeout: next(seq))
    monkeypatch.setattr(h.time, "sleep", lambda s: None)
    return c


def test_retries_transient_errors_then_succeeds(monkeypatch):
    c = _client(
        monkeypatch, [FakeResp(503), FakeResp(429, headers={"Retry-After": "0"}), FakeResp(200, b"[1]")]
    )
    resp = c.get("u")
    assert resp.content == b"[1]" and resp.attempts == 3


def test_auth_failure_raises_instead_of_returning_empty(monkeypatch):
    c = _client(monkeypatch, [FakeResp(401)])
    with pytest.raises(h.SourceHTTPError):
        c.get("u")


def test_404_is_distinguishable(monkeypatch):
    c = _client(monkeypatch, [FakeResp(404)])
    with pytest.raises(h.NotFound):
        c.get("u")


def test_gives_up_after_max_retries(monkeypatch):
    c = _client(monkeypatch, [FakeResp(500)] * 10)
    with pytest.raises(h.SourceHTTPError):
        c.get("u")
