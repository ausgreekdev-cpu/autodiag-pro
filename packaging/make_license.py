"""Issue a signed AutoDiag Pro licence key file.

Requires the Ed25519 signing private key (never committed to the repo):

  python packaging/make_license.py --tier pro --licensee "Jane Doe" \
      --key ~/.autodiag-signing/license-signing.key --out jane-pro.json

Optional: --expires YYYY-MM-DD (subscription-style keys fall back to Free
after this date). The matching public key is embedded in
autodiag/services/license.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # run from anywhere

from autodiag.services.license import (  # noqa: E402
    LICENSE_FORMAT,
    Tier,
    sign_license,
)

_TIERS = tuple(t.name.lower() for t in Tier)


def build_payload(
    *, tier: str, licensee: str, issued: str, expires: str | None
) -> dict:
    payload: dict = {
        "format": LICENSE_FORMAT,
        "tier": tier,
        "licensee": licensee,
        "issued": issued,
    }
    if expires:
        payload["expires"] = expires
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", required=True, choices=_TIERS)
    parser.add_argument("--licensee", required=True, help="customer/shop name")
    parser.add_argument("--key", default=os.environ.get("LICENSE_SIGNING_KEY"),
                        help="Ed25519 private key PEM (or $LICENSE_SIGNING_KEY)")
    parser.add_argument("--issued", default=date.today().isoformat())
    parser.add_argument("--expires", default=None, help="YYYY-MM-DD")
    parser.add_argument("--out", required=True, help="output .json path")
    args = parser.parse_args(argv)

    if not args.key:
        parser.error("--key (or $LICENSE_SIGNING_KEY) is required")
    key_path = Path(args.key)
    if not key_path.is_file():
        print(f"signing key not found: {key_path}", file=sys.stderr)
        return 2

    payload = build_payload(
        tier=args.tier,
        licensee=args.licensee.strip(),
        issued=args.issued,
        expires=args.expires,
    )
    signature = sign_license(key_path.read_bytes(), payload)
    document = {**payload, "sig": signature}

    out = Path(args.out)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({args.tier} for {args.licensee!r})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
