"""Ford ECU SecurityAccess seed-key algorithms.

Reversed from ``libfnvfsa.so`` (ECG2 GWM); publicly documented at
https://gist.github.com/JJTech0130/3ff9b5c0b348326f12f7c41d30464158

Three algorithms cover Ford's $27 seed/key exchange:

* **Algorithm 0** (legacy): 24-bit Galois LFSR cipher — 3-byte seed,
  5-byte (40-bit) secret.  Described in
  https://flaviodgarcia.com/publications/BtB.pdf
* **Algorithm 1**: HMAC-SHA1 with a ``zaCK`` prefix — 16-byte seed,
  12-byte fixedBytes.  Returns bytes 4..20 of the digest.
* **Algorithm 2**: HMAC-SHA1 with a ``JaKe`` suffix — 16-byte seed,
  12-byte fixedBytes.  Returns bytes 0..18 of the digest.

The **secret / fixedBytes** are per-ECU values embedded in firmware; they
must be provided by the user (or a future in-app ECU database).
"""

from __future__ import annotations

import hashlib
import hmac

# Algorithm 0 constants (24-bit Galois LFSR).
_LFSR_INIT = 0x000000
_LFSR_TAPS = 0x800000  # x^24 + x^7 + x^2 + x + 1


def _nibble_permute(y: bytes) -> bytes:
    n = [y[0] >> 4, y[0] & 0xF, y[1] >> 4, y[1] & 0xF, y[2] >> 4, y[2] & 0xF]
    n3, n4, n2, n0, n5, n1 = n[3], n[4], n[2], n[0], n[5], n[1]
    return bytes([(n3 << 4) | n4, (n2 << 4) | n0, (n5 << 4) | n1])


def ford_legacy_key(challenge: bytes, secret: bytes) -> bytes:
    """Algorithm 0 — 24-bit Galois LFSR.

    Args:
        challenge: 3-byte seed from the ECU (``$27 01`` response payload).
        secret: 5-byte (40-bit) secret for this ECU.

    Returns:
        3-byte key to send back via ``$27 02``.
    """
    if len(challenge) != 3 or len(secret) != 5:
        raise ValueError("algorithm 0 needs a 3-byte challenge and 5-byte secret")
    c = int.from_bytes(challenge, "big")
    s = int.from_bytes(secret, "big")
    state = _LFSR_INIT
    for i in range(64):
        r = (c >> i) & 1 if i < 24 else (s >> (i - 24)) & 1
        fb = ((state >> 23) & 1) ^ r
        state = ((state << 1) | fb) & 0xFFFFFF
        if fb:
            state ^= _LFSR_TAPS
    return _nibble_permute(state.to_bytes(3, "big"))


def ford_hmac_key(mode: int, seed: bytes, fixed_bytes: bytes) -> bytes:
    """Algorithm 1 or 2 — HMAC-SHA1.

    Args:
        mode: ``1`` (zaCK prefix) or ``2`` (JaKe suffix).
        seed: 16-byte seed from the ECU.
        fixed_bytes: 12-byte per-ECU secret.

    Returns:
        16-byte (mode 1) or 18-byte (mode 2) key.
    """
    if len(seed) != 16 or len(fixed_bytes) != 12:
        raise ValueError(
            "algorithms 1/2 need a 16-byte seed and 12-byte fixedBytes"
        )
    if mode == 1:
        data = b"zaCK" + seed
    elif mode == 2:
        data = seed + b"JaKe"
    else:
        raise ValueError("mode must be 1 or 2")
    h = hmac.new(fixed_bytes, data, hashlib.sha1)
    digest = h.digest()
    return digest[4:20] if mode == 1 else digest[0:18]


def compute_key(
    algorithm: int,
    seed: bytes,
    secret: bytes,
) -> bytes:
    """Dispatch to the correct Ford algorithm.

    Args:
        algorithm: 0 (legacy LFSR), 1 (HMAC zaCK), or 2 (HMAC JaKe).
        seed: challenge bytes from the ECU.
        secret: per-ECU secret (5 bytes for alg 0, 12 for alg 1/2).

    Returns:
        Key bytes for ``$27 02``.

    Raises:
        ValueError: unknown algorithm or wrong input lengths.
    """
    if algorithm == 0:
        return ford_legacy_key(seed, secret)
    if algorithm in (1, 2):
        return ford_hmac_key(algorithm, seed, secret)
    raise ValueError(f"unknown algorithm {algorithm}")
