"""Freemium tiers, feature gates, signed licence keys, manager lifecycle."""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autodiag.services import license as license_mod
from autodiag.services.license import (
    EULA_VERSION,
    FEATURE_TIERS,
    FREE_STATE,
    HISTORY_FREE_LIMIT,
    LicenseError,
    LicenseManager,
    LicenseState,
    Tier,
    feature_tier,
    load_license_text,
    sign_license,
    tier_label,
)


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return key, base64.b64encode(pub).decode("ascii")


def _pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _payload(**overrides: object) -> dict:
    payload: dict = {
        "format": 1,
        "tier": "pro",
        "licensee": "Test User",
        "issued": "2026-10-13",
    }
    payload.update(overrides)
    return payload


def _signed(key: Ed25519PrivateKey, payload: dict) -> str:
    return json.dumps({**payload, "sig": sign_license(_pem(key), payload)})


@pytest.fixture()
def embedded_key(monkeypatch):
    """Point verification at a fresh ephemeral public key."""
    key, pub_b64 = _keypair()
    monkeypatch.setattr(license_mod, "LICENSE_PUBLIC_KEY_B64", pub_b64)
    return key


# -- tiers --------------------------------------------------------------------


def test_tier_labels_and_ordering():
    assert Tier.FREE < Tier.PRO < Tier.WORKSHOP
    assert [tier_label(t) for t in Tier] == ["Free", "Pro", "Workshop"]


@pytest.mark.parametrize(
    ("feature", "minimum"),
    [
        ("uds.read", Tier.PRO),
        ("uds.write", Tier.WORKSHOP),
        ("pdf.export", Tier.PRO),
        ("work_order", Tier.WORKSHOP),
        ("history.full", Tier.PRO),
    ],
)
def test_feature_tiers(feature, minimum):
    assert feature_tier(feature) == minimum
    assert FEATURE_TIERS[feature] == minimum


def test_unlisted_feature_is_free():
    assert feature_tier("live_data") == Tier.FREE


@pytest.mark.parametrize("feature", FEATURE_TIERS)
def test_allows_matrix(feature):
    minimum = FEATURE_TIERS[feature]
    for tier in Tier:
        expected = tier >= minimum
        assert LicenseState(tier).allows(feature) is expected


def test_history_limit_by_tier():
    assert FREE_STATE.history_limit() == HISTORY_FREE_LIMIT == 10
    assert LicenseState(Tier.PRO).history_limit() is None
    assert LicenseState(Tier.WORKSHOP).history_limit() is None


def test_expired_key_falls_back_to_free():
    state = LicenseState(
        Tier.PRO, source="key", expires=date(2026, 1, 1)
    )
    assert state.allows("pdf.export", today=date(2025, 12, 31)) is True
    assert state.allows("pdf.export", today=date(2026, 1, 2)) is False
    assert state.history_limit(today=date(2026, 1, 2)) == HISTORY_FREE_LIMIT
    assert state.effective_tier(today=date(2026, 1, 2)) == Tier.FREE


# -- signed key files -----------------------------------------------------------


def test_sign_and_verify_roundtrip(embedded_key):
    payload = _payload(tier="workshop")
    state = load_license_text(_signed(embedded_key, payload))
    assert state.tier == Tier.WORKSHOP
    assert state.source == "key"
    assert state.licensee == "Test User"
    assert state.allows("uds.write")


def test_tampered_payload_rejected(embedded_key):
    document = json.loads(_signed(embedded_key, _payload()))
    document["tier"] = "workshop"
    with pytest.raises(LicenseError, match="signature"):
        load_license_text(json.dumps(document))


def test_wrong_signing_key_rejected(embedded_key):
    stranger, _ = _keypair()
    with pytest.raises(LicenseError, match="signature"):
        load_license_text(_signed(stranger, _payload()))


def test_unknown_tier_rejected(embedded_key):
    with pytest.raises(LicenseError, match="unknown tier"):
        load_license_text(_signed(embedded_key, _payload(tier="platinum")))


def test_future_issue_date_rejected(embedded_key):
    with pytest.raises(LicenseError, match="future"):
        load_license_text(
            _signed(embedded_key, _payload(issued="2027-01-01")),
            today=date(2026, 10, 13),
        )


def test_expired_key_rejected_at_load(embedded_key):
    document = _signed(
        embedded_key, _payload(issued="2025-01-01", expires="2026-01-01")
    )
    with pytest.raises(LicenseError, match="expired"):
        load_license_text(document, today=date(2026, 10, 13))


def test_garbage_inputs_rejected():
    with pytest.raises(LicenseError, match="JSON"):
        load_license_text("not json at all")
    with pytest.raises(LicenseError, match="format"):
        load_license_text(json.dumps({"format": 99}))
    with pytest.raises(LicenseError, match="object"):
        load_license_text(json.dumps([1, 2, 3]))


# -- manager --------------------------------------------------------------------


def test_fresh_manager_is_free(tmp_path):
    manager = LicenseManager(key_path=tmp_path / "license.json")
    assert manager.current().tier == Tier.FREE
    assert not manager.current().allows("pdf.export")


def test_install_persists_and_refreshes(embedded_key, tmp_path):
    key_path = tmp_path / "license.json"
    source = tmp_path / "delivered.json"
    source.write_text(_signed(embedded_key, _payload(tier="pro")), encoding="utf-8")

    manager = LicenseManager(key_path=key_path)
    state = manager.install_key(source)
    assert state.tier == Tier.PRO
    assert manager.current().allows("pdf.export")
    assert key_path.is_file()

    reopened = LicenseManager(key_path=key_path)
    assert reopened.current().tier == Tier.PRO


def test_install_rejects_invalid_and_keeps_state(embedded_key, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": 1, "tier": "pro"}), encoding="utf-8")
    manager = LicenseManager(key_path=tmp_path / "license.json")
    with pytest.raises(LicenseError):
        manager.install_key(bad)
    assert manager.current().tier == Tier.FREE
    assert not (tmp_path / "license.json").exists()


def test_remove_key_returns_to_free(embedded_key, tmp_path):
    key_path = tmp_path / "license.json"
    source = tmp_path / "delivered.json"
    source.write_text(_signed(embedded_key, _payload()), encoding="utf-8")
    manager = LicenseManager(key_path=key_path)
    manager.install_key(source)
    assert manager.current().allows("pdf.export")
    manager.remove_key()
    assert manager.current().tier == Tier.FREE
    assert not key_path.exists()


def test_missing_key_file_is_free(tmp_path):
    manager = LicenseManager(key_path=tmp_path / "nope.json")
    manager.refresh()
    assert manager.current().tier == Tier.FREE


def test_explicit_state_skips_disk(tmp_path):
    state = LicenseState(Tier.WORKSHOP, source="key", licensee="suite")
    manager = LicenseManager(key_path=tmp_path / "unused.json", state=state)
    assert manager.current() is state
    assert not (tmp_path / "unused.json").exists()


def test_get_and_set_license_roundtrip(tmp_path):
    fresh = LicenseManager(key_path=tmp_path / "l.json")
    license_mod.set_license(fresh)
    try:
        assert license_mod.get_license() is fresh
    finally:
        license_mod.set_license(None)


# -- EULA ------------------------------------------------------------------------


def test_docs_eula_matches_bundled_copy():
    root = Path(__file__).resolve().parent.parent
    bundled = (root / "autodiag" / "data" / "eula.txt").read_text(encoding="utf-8")
    docs = (root / "docs" / "eula.md").read_text(encoding="utf-8")
    assert docs == bundled, "docs/eula.md is stale — re-copy autodiag/data/eula.txt"


def test_eula_version_is_stable():
    assert EULA_VERSION == "1"


def test_store_source_round_trip(embedded_key):
    payload = _payload(source="store")
    state = license_mod._load_state(_signed(embedded_key, payload))
    assert state.source == "store"


def test_unknown_source_rejected(embedded_key):
    payload = _payload(source="bogus")
    with pytest.raises(license_mod.LicenseError, match="unknown license source"):
        license_mod._load_state(_signed(embedded_key, payload))
