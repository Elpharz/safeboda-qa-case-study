"""Top-ups, idempotency, ledger invariants, concurrency on money."""
import uuid

import pytest

from qa_api import OKELLO_PHONE, assert_error, run_parallel

VALID = {"amount": 10000, "provider": "mtn_momo", "phone": OKELLO_PHONE}


@pytest.mark.positive
def test_topup_credits_wallet(api):
    r = api.topup("okello", **VALID)
    assert r.status_code == 201, r.text
    b = r.json()
    assert (b["status"], b["currency"], b["provider"], b["phone"], b["amount"]) == \
           ("successful", "UGX", "mtn_momo", OKELLO_PHONE, 10000)
    assert b["id"] and b["provider_reference"]
    assert b["wallet_balance_after"] == 13000
    assert api.balance("okello") == 13000


@pytest.mark.positive
@pytest.mark.parametrize("provider", ["mtn_momo", "airtel_money"])
def test_topup_both_providers(api, provider):
    r = api.topup("okello", 1000, provider=provider, phone=OKELLO_PHONE)
    assert r.status_code == 201 and r.json()["provider"] == provider


@pytest.mark.positive
@pytest.mark.state
def test_topup_replay_credits_once(api):
    key = str(uuid.uuid4())
    r1 = api.topup("okello", idem=key, **VALID)
    r2 = api.topup("okello", idem=key, **VALID)
    assert (r1.status_code, r2.status_code) == (201, 200), (r1.text, r2.text)
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.json()["wallet_balance_after"] == r1.json()["wallet_balance_after"]
    assert api.balance("okello") == 13000, "wallet credited more than once"
    assert len([t for t in api.ledger("okello")["data"] if t["type"] == "top_up"]) == 1


@pytest.mark.negative
@pytest.mark.state
def test_topup_same_key_different_amount_is_422(api):
    key = str(uuid.uuid4())
    assert api.topup("okello", idem=key, **VALID).status_code == 201
    r = api.topup("okello", idem=key, amount=20000, provider="mtn_momo", phone=OKELLO_PHONE)
    assert_error(r, 422, "IDEMPOTENCY_KEY_REUSED")
    assert api.balance("okello") == 13000


@pytest.mark.negative
@pytest.mark.state
@pytest.mark.parametrize("patch", [{"provider": "airtel_money"}, {"phone": "+256700100999"}], ids=["provider", "phone"])
def test_topup_same_key_different_body_any_field_is_422(api, patch):
    key = str(uuid.uuid4())
    api.topup("okello", idem=key, **VALID)
    r = api.topup("okello", idem=key, **{**VALID, **patch})
    assert_error(r, 422, "IDEMPOTENCY_KEY_REUSED")


@pytest.mark.positive
@pytest.mark.state
@pytest.mark.inferred
def test_idempotency_key_is_scoped_per_rider(api):
    """A key used by one rider must not replay (or leak) that rider's top-up to another."""
    key = str(uuid.uuid4())
    api.topup("okello", idem=key, **VALID)
    r = api.topup("nakato", 10000, idem=key)
    assert r.status_code == 201, f"cross-rider key collision: {r.status_code} {r.text}"
    assert api.balance("nakato") == 35000


@pytest.mark.negative
def test_topup_requires_idempotency_key(api):
    r = api.post("/v1/wallet/top-ups", "okello", json=VALID)
    assert_error(r, 400, "IDEMPOTENCY_KEY_REQUIRED")
    assert api.balance("okello") == 3000


@pytest.mark.negative
def test_topup_empty_idempotency_key_rejected(api):
    r = api.post("/v1/wallet/top-ups", "okello", json=VALID, headers={"Idempotency-Key": ""})
    assert r.status_code == 400, r.text
    assert api.balance("okello") == 3000


@pytest.mark.negative
def test_topup_invalid_json(api):
    r = api.post("/v1/wallet/top-ups", "okello", raw="{nope", headers={"Idempotency-Key": "k1"})
    assert_error(r, 400, "INVALID_JSON")


@pytest.mark.negative
def test_topup_requires_auth(api):
    r = api.post("/v1/wallet/top-ups", json=VALID, headers={"Idempotency-Key": "k"})
    assert_error(r, 401)


@pytest.mark.parametrize("amount,ok", [
    pytest.param(499, False, marks=[pytest.mark.boundary, pytest.mark.negative]), pytest.param(500, True, marks=[pytest.mark.boundary, pytest.mark.positive]),
    pytest.param(501, True, marks=[pytest.mark.boundary, pytest.mark.positive]), pytest.param(2_000_000, True, marks=[pytest.mark.boundary, pytest.mark.positive]),
    pytest.param(2_000_001, False, marks=[pytest.mark.boundary, pytest.mark.negative]), pytest.param(0, False, marks=[pytest.mark.boundary, pytest.mark.negative]),
    pytest.param(-1, False, marks=pytest.mark.negative), pytest.param(-10000, False, marks=pytest.mark.negative), pytest.param(10**18, False, marks=pytest.mark.negative)])
def test_topup_amount_boundaries(api, amount, ok):
    r = api.topup("okello", amount, phone=OKELLO_PHONE)
    if ok:
        assert r.status_code == 201, r.text
        assert api.balance("okello") == 3000 + amount
    else:
        assert_error(r, 422, "VALIDATION_ERROR")
        assert api.balance("okello") == 3000, "balance changed by a rejected top-up"


@pytest.mark.negative
@pytest.mark.parametrize("amount", ["10000", 10000.5, True, None, [10000], {"v": 1}], ids=repr)
def test_topup_amount_wrong_type(api, amount):
    r = api.topup("okello", body={"amount": amount, "provider": "mtn_momo", "phone": OKELLO_PHONE})
    assert_error(r, 422, "VALIDATION_ERROR")
    assert api.balance("okello") == 3000


@pytest.mark.negative
@pytest.mark.parametrize("phone", ["+256800100487", "0700100487", pytest.param("+25670010048", marks=pytest.mark.boundary),
                                   pytest.param("+2567001004871", marks=pytest.mark.boundary),
                                   "+256 700100487", "256700100487", "+256700100487\n", "+2567001004ab", "", None, 700100487])
def test_topup_phone_pattern(api, phone):
    r = api.topup("okello", body={"amount": 1000, "provider": "mtn_momo", "phone": phone})
    assert_error(r, 422, "VALIDATION_ERROR")
    assert api.balance("okello") == 3000


@pytest.mark.negative
@pytest.mark.parametrize("provider", ["mpesa", "MTN_MOMO", "", None, 5])
def test_topup_provider_enum(api, provider):
    r = api.topup("okello", body={"amount": 1000, "provider": provider, "phone": OKELLO_PHONE})
    assert_error(r, 422, "VALIDATION_ERROR")


@pytest.mark.negative
@pytest.mark.parametrize("missing", ["amount", "provider", "phone"])
def test_topup_missing_field(api, missing):
    body = {k: v for k, v in VALID.items() if k != missing}
    assert_error(api.topup("okello", body=body), 422, "VALIDATION_ERROR")


# ---- ledger ---------------------------------------------------------------------
@pytest.mark.positive
@pytest.mark.state
def test_ledger_reconciles_after_topups(api):
    api.topup("okello", 1500)
    api.topup("okello", 2500, provider="airtel_money")
    led = api.ledger("okello")
    assert led["opening_balance"] == 3000
    assert led["opening_balance"] + sum(t["amount"] for t in led["data"]) == led["balance"] == api.balance("okello") == 7000
    assert len(led["data"]) == 2


@pytest.mark.positive
def test_ledger_entry_matches_topup(api):
    top = api.topup("okello", 4000).json()
    entry = api.ledger("okello")["data"][0]
    assert (entry["type"], entry["amount"], entry["reference"], entry["balance_after"]) == \
           ("top_up", 4000, top["id"], 7000)


@pytest.mark.positive
def test_wallets_are_isolated(api):
    api.topup("okello", 5000)
    assert api.balance("nakato") == 25000
    assert api.ledger("nakato")["data"] == []


# ---- concurrency -----------------------------------------------------------------
@pytest.mark.positive
@pytest.mark.state
@pytest.mark.concurrency
def test_parallel_replays_credit_once(api):
    key = str(uuid.uuid4())
    rs = run_parallel(lambda i: api.topup("okello", idem=key, **VALID), 10)
    codes = sorted(r.status_code for r in rs)
    assert codes.count(201) == 1 and codes.count(200) == 9, codes
    assert len({r.json()["id"] for r in rs}) == 1
    assert api.balance("okello") == 13000, "parallel replays double-credited"


@pytest.mark.positive
@pytest.mark.state
@pytest.mark.concurrency
def test_parallel_distinct_topups_no_lost_update(api):
    rs = run_parallel(lambda i: api.topup("okello", 1000, **{"provider": "mtn_momo", "phone": OKELLO_PHONE}), 10)
    assert all(r.status_code == 201 for r in rs), [r.status_code for r in rs]
    assert api.balance("okello") == 13000, "lost update under concurrent top-ups"
    led = api.ledger("okello")
    assert len(led["data"]) == 10
    assert led["opening_balance"] + sum(t["amount"] for t in led["data"]) == led["balance"]
