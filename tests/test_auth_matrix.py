"""401 for every authenticated operation in the spec: missing token, forged token, missing candidate key.

The operation list is read from openapi.json, so a new endpoint is covered automatically. Path ids point
at a real trip owned by Nakato, so a 404 here would mean the API looks the trip up BEFORE checking auth
(which leaks whether a trip id exists).
"""
import json
from pathlib import Path

import pytest

from qa_api import ACACIA, NTINDA, OKELLO_PHONE, assert_error

SPEC = json.loads((Path(__file__).resolve().parents[1] / "openapi.json").read_text())
BODIES = {  # a valid body per operation, so only auth can be the reason for refusal
    "POST /v1/wallet/top-ups": {"amount": 1000, "provider": "mtn_momo", "phone": OKELLO_PHONE},
    "POST /v1/fare-estimates": {"pickup": ACACIA, "dropoff": NTINDA, "service_type": "boda"},
    "POST /v1/trips": {"estimate_id": "est_000000000000", "payment_method": "cash"},
    "POST /v1/trips/{trip_id}/rating": {"stars": 5},
    "POST /v1/support/chat": {"message": "hi"},
}


def _ops(token_scheme_only):
    out = []
    for path, item in SPEC["paths"].items():
        for method, op in item.items():
            schemes = {k for req in op.get("security", []) for k in req}
            if token_scheme_only and not schemes & {"riderToken", "driverToken"}:
                continue
            if path == "/v1/_reset":
                continue  # resetting with a bad key is covered by test_places_requires_candidate_key style checks
            out.append(pytest.param(method.upper(), path, id=f"{method.upper()} {path}"))
    return out


def _call(api, method, path, as_=None, send_key=True):
    t = api.new_trip("nakato")
    url = path.replace("{trip_id}", t["id"])
    return api.call(method, url, as_=as_, json=BODIES.get(f"{method} {path}"), send_key=send_key,
                    headers={"Idempotency-Key": "auth-matrix"} if method == "POST" else None)


@pytest.mark.negative
@pytest.mark.parametrize("token", [pytest.param(None, id="no-token"), pytest.param("tok_forged_000000", id="bad-token")])
@pytest.mark.parametrize("method,path", _ops(token_scheme_only=True))
def test_every_token_operation_rejects_missing_or_bad_token(api, method, path, token):
    assert_error(_call(api, method, path, as_=token), 401)


@pytest.mark.negative
@pytest.mark.parametrize("method,path", _ops(token_scheme_only=False))
def test_every_operation_rejects_missing_candidate_key(api, method, path):
    """Valid rider/driver token but no X-Candidate-Key."""
    as_ = "ssemanda" if "/driver/" in path else "nakato"
    assert_error(_call(api, method, path, as_=as_, send_key=False), 401)
