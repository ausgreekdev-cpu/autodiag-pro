"""Update check service tests — fakes injected, no network."""

from __future__ import annotations

import urllib.error

import pytest

from autodiag.services.update_check import (
    check_for_update,
    is_newer,
    parse_version,
)


def _payload(tag: str = "v9.9.9", url: str = "https://example.test/releases/r") -> dict:
    return {"tag_name": tag, "html_url": url}


def test_parse_version_accepts_v_prefix():
    assert parse_version("0.12.0") == (0, 12, 0)
    assert parse_version("v0.12.0") == (0, 12, 0)


@pytest.mark.parametrize("junk", ["", "v", "abc", "1.2.x", "1..2", "v0.12.0-rc1"])
def test_parse_version_rejects_junk(junk: str):
    with pytest.raises(ValueError):
        parse_version(junk)


def test_is_newer_compares_ascending():
    assert is_newer("v0.12.0", "0.11.0")
    assert is_newer("v0.11.1", "0.11.0")
    assert not is_newer("v0.11.0", "0.11.0")
    assert not is_newer("v0.10.0", "0.11.0")


def test_check_finds_newer_release():
    seen: list[tuple[str, float]] = []

    def fake(url: str, timeout: float) -> dict:
        seen.append((url, timeout))
        return _payload()

    result = check_for_update("0.1.0", fetch=fake)
    assert result.status == "update"
    assert result.latest == "v9.9.9"
    assert result.url == "https://example.test/releases/r"
    assert seen and seen[0][0].startswith("https://api.github.com/")


def test_check_current_release():
    result = check_for_update("9.9.9", fetch=lambda _u, _t: _payload())
    assert result.status == "current"
    assert result.latest == "v9.9.9"


def test_check_network_error_is_soft():
    def fake(_url: str, _timeout: float) -> dict:
        raise urllib.error.URLError("dns down")

    result = check_for_update("0.1.0", fetch=fake)
    assert result.status == "error"
    assert result.message is not None
    assert "dns down" in result.message


def test_check_http_error_reports_status():
    def fake(_url: str, _timeout: float) -> dict:
        raise urllib.error.HTTPError("https://api.test", 404, "Not Found", None, None)

    result = check_for_update("0.1.0", fetch=fake)
    assert result.status == "error"
    assert result.message == "HTTP 404"


def test_check_bad_tag_is_error():
    result = check_for_update("0.1.0", fetch=lambda _u, _t: _payload(tag="latest"))
    assert result.status == "error"
    assert "latest" in (result.message or "")


def test_check_missing_keys_is_error():
    result = check_for_update("0.1.0", fetch=lambda _u, _t: {})
    assert result.status == "error"
