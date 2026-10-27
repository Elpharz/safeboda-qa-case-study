"""Auth, error envelope, places, profile and 'bad input must never 500'."""
import pytest

from qa_api import (Api, NAIROBI, START_BALANCE, assert_error, assert_no_leak, OKELLO_PHONE)

RIDER_ROUTES = [("GET", "/v1/me"), ("GET", "/v1/wallet/transactions"), ("GET", "/v1/trips")]
DRIVER_ROUTES = [("GET", "/v1/driver/trips/available")]


@pytest.mark.negative
def test_places_requires_candidate_key(api):
    assert_error(api.get("/v1/places", send_key=False), 401)


@pytest.mark.negative
def test_invalid_candidate_key_rejected(api):
    assert_error(api.get("/v1/places", key="cand_not_a_real_key"), 401)


@pytest.mark.negative
@pytest.mark.parametrize("method,path", RIDER_ROUTES)
def test_rider_routes_require_token(api, method, path):
    assert_error(api.call(method, path), 401)


@pytest.mark.negative
@pytest.mark.parametrize("method,path", RIDER_ROUTES)
def test_rider_routes_reject_bad_token(api, method, path):
    assert_error(api.call(method, path, as_="rdr_tok_forged_000000"), 401)


@pytest.mark.negative
@pytest.mark.parametrize("method,path", RIDER_ROUTES)
def test_driver_token_cannot_use_rider_routes(api, method, path):
    r = api.call(method, path, as_="ssemanda")
    assert r.status_code in (401, 403), f"driver token accepted on rider route: {r.status_code}"


@pytest.mark.negative
@pytest.mark.parametrize("method,path", DRIVER_ROUTES)
def test_rider_token_cannot_use_driver_routes(api, method, path):
    r = api.call(method, path, as_="nakato")
    assert r.status_code in (401, 403), f"rider token accepted on driver route: {r.status_code}"


@pytest.mark.negative
def test_driver_routes_require_token(api):
    assert_error(api.get("/v1/driver/trips/available"), 401)


@pytest.mark.negative
def test_error_envelope_shape(api):
    assert_error(api.get("/v1/trips/trp_DOESNOTEXIST", "nakato"), 404, "TRIP_NOT_FOUND")


# ---- profile ---------------------------------------------------------------
@pytest.mark.positive
@pytest.mark.parametrize("rider,balance", START_BALANCE.items())
def test_starting_balances(api, rider, balance):
    me = api.me(rider)
    assert me["wallet"] == {"balance": balance, "currency": "UGX"}


@pytest.mark.positive
def test_okello_phone(api):
    assert api.me("okello")["phone"] == OKELLO_PHONE


@pytest.mark.positive
@pytest.mark.state
def test_reset_restores_balances(api):
    api.topup("okello", 5000)
    assert api.balance("okello") == 8000
    api.reset()
    assert api.balance("okello") == 3000
    assert api.ledger("okello")["data"] == []


# ---- places ----------------------------------------------------------------
@pytest.mark.positive
def test_places_search_finds_ntinda(api):
    r = api.get("/v1/places", params={"q": "ntinda"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data and all("ntinda" in (p["name"] + p["area"]).lower() for p in data)


@pytest.mark.positive
def test_places_search_case_insensitive(api):
    lower = api.get("/v1/places", params={"q": "ntinda"}).json()["data"]
    upper = api.get("/v1/places", params={"q": "NTINDA"}).json()["data"]
    assert {p["id"] for p in lower} == {p["id"] for p in upper}


@pytest.mark.positive
def test_places_no_match_is_empty_list_not_error(api):
    r = api.get("/v1/places", params={"q": "zzzzqqqq"})
    assert r.status_code == 200 and r.json()["data"] == []


@pytest.mark.positive
def test_places_without_q_lists_places(api):
    r = api.get("/v1/places")
    assert r.status_code == 200 and len(r.json()["data"]) > 0


@pytest.mark.positive
def test_places_coordinates_are_in_kampala_area(api):
    for p in api.get("/v1/places").json()["data"]:
        assert -0.2 < p["lat"] < 0.8 and 32.2 < p["lng"] < 33.0, p


@pytest.mark.negative
@pytest.mark.parametrize("q", ["' OR 1=1 --", "<script>alert(1)</script>", "a" * 5000, "%00", "ntinda%", "\u202eevil"])
def test_places_hostile_queries_do_not_5xx(api, q):
    r = api.get("/v1/places", params={"q": q})
    assert r.status_code < 500, r.text[:200]
    assert_no_leak(r.text)


# ---- malformed bodies never 5xx and never leak internals ---------------------
BAD_BODIES = ["not json", "[]", "null", '{"a":', '"str"', "123", "{" * 5000, "\x00\x01"]
POST_TARGETS = [
    ("/v1/fare-estimates", {}),
    ("/v1/trips", {}),
    ("/v1/wallet/top-ups", {"Idempotency-Key": "bad-body-key"}),
    ("/v1/trips/trp_X/rating", {}),
    ("/v1/support/chat", {}),
]


@pytest.mark.negative
@pytest.mark.parametrize("path,headers", POST_TARGETS, ids=[p for p, _ in POST_TARGETS])
@pytest.mark.parametrize("body", BAD_BODIES, ids=["not-json", "array", "null", "truncated", "string", "number", "deep-nesting", "binary"])
def test_malformed_body_is_client_error(api, path, headers, body):
    r = api.post(path, "nakato", raw=body, headers=headers)
    assert r.status_code in (400, 404, 422), f"{path} -> {r.status_code}: {r.text[:200]}"
    assert_no_leak(r.text)
    assert "error" in r.json()


@pytest.mark.positive
def test_nairobi_constant_sanity():
    assert NAIROBI["lat"] < 0 and NAIROBI["lng"] > 36
