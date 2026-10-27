"""Booking, wallet charging, cancellation, listing, scheduling, rating."""
import uuid
from datetime import timedelta

import pytest

from qa_api import (ACACIA, NTINDA, assert_error, parse_dt, utcnow)


# ---- booking -------------------------------------------------------------------
@pytest.mark.positive
def test_book_cash_trip(api):
    est = api.new_estimate()
    r = api.book("nakato", est["id"], "cash", notes="Meet me at the main gate")
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["id"].startswith("trp_") and t["status"] == "requested" and t["driver"] is None
    assert t["fare"] == est["fare"] and t["payment_method"] == "cash" and t["notes"] == "Meet me at the main gate"
    assert t["pickup"]["lat"] == ACACIA["lat"] and t["dropoff"]["lat"] == NTINDA["lat"]
    assert t["service_type"] == "boda" and t["distance_km"] == est["distance_km"]
    assert [h["status"] for h in t["status_history"]] == ["requested"]


@pytest.mark.negative
@pytest.mark.state
def test_estimate_is_single_use(api):
    est = api.new_estimate()
    assert api.book("nakato", est["id"]).status_code == 201
    assert_error(api.book("nakato", est["id"]), 409, "ESTIMATE_ALREADY_USED")
    assert api.get("/v1/trips", "nakato").json()["total"] == 1


@pytest.mark.positive
@pytest.mark.state
def test_booking_replay_returns_first_trip(api):
    est, key = api.new_estimate(), str(uuid.uuid4())
    r1, r2 = api.book("nakato", est["id"], idem=key), api.book("nakato", est["id"], idem=key)
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json()["id"] == r2.json()["id"]
    assert api.get("/v1/trips", "nakato").json()["total"] == 1


@pytest.mark.negative
def test_unknown_estimate_404(api):
    assert_error(api.book("nakato", "est_000000000000"), 404, "ESTIMATE_NOT_FOUND")


@pytest.mark.negative
@pytest.mark.state
def test_cannot_book_another_riders_estimate(api):
    est = api.new_estimate("nakato")
    assert_error(api.book("okello", est["id"]), 404, "ESTIMATE_NOT_FOUND")
    assert api.book("nakato", est["id"]).status_code == 201, "estimate was burned by the foreign attempt"


@pytest.mark.negative
@pytest.mark.parametrize("body", [{"payment_method": "cash"}, {"estimate_id": "x"}, {"estimate_id": "x", "payment_method": "card"},
                                  {"estimate_id": 5, "payment_method": "cash"}], ids=["no-est", "no-method", "bad-method", "est-int"])
def test_booking_validation(api, body):
    r = api.post("/v1/trips", "nakato", json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code in (404, 422) and r.status_code < 500, r.text


@pytest.mark.boundary
@pytest.mark.parametrize("length,ok", [pytest.param(200, True, marks=pytest.mark.positive), pytest.param(201, False, marks=pytest.mark.negative)])
def test_notes_length(api, length, ok):
    est = api.new_estimate()
    r = api.book("nakato", est["id"], notes="n" * length)
    assert r.status_code == (201 if ok else 422), r.text[:200]


# ---- wallet payments --------------------------------------------------------------
@pytest.mark.positive
@pytest.mark.state
def test_wallet_not_charged_at_booking_but_on_completion(api):
    before = api.balance("nakato")
    trip = api.new_trip("nakato", "wallet")
    assert api.balance("nakato") == before, "charged at booking, spec says on completion"
    api.drive(trip["id"], upto="start")
    assert api.balance("nakato") == before
    done = api.driver_step("ssemanda", trip["id"], "complete").json()
    assert done["status"] == "completed"
    assert api.balance("nakato") == before - trip["fare"]["amount"]


@pytest.mark.positive
@pytest.mark.state
def test_wallet_charge_is_discounted_fare(api):
    trip = api.new_trip("nakato", "wallet", promo="SAFE20")
    api.drive(trip["id"])
    assert trip["fare"]["discount"] > 0
    assert api.balance("nakato") == 25000 - trip["fare"]["amount"]


@pytest.mark.positive
@pytest.mark.state
def test_ledger_has_one_trip_charge_and_reconciles(api):
    trip = api.new_trip("nakato", "wallet")
    api.drive(trip["id"])
    led = api.ledger("nakato")
    charges = [t for t in led["data"] if t["type"] == "trip_charge"]
    assert len(charges) == 1
    assert charges[0]["reference"] == trip["id"] and abs(charges[0]["amount"]) == trip["fare"]["amount"]
    assert led["opening_balance"] + sum(t["amount"] for t in led["data"]) == led["balance"] == api.balance("nakato")


@pytest.mark.positive
@pytest.mark.state
def test_cash_trip_does_not_touch_wallet(api):
    trip = api.new_trip("nakato", "cash")
    api.drive(trip["id"])
    assert api.balance("nakato") == 25000 and api.ledger("nakato")["data"] == []


@pytest.mark.negative
def test_wallet_booking_insufficient_balance(api):
    est = api.new_estimate("okello")
    if est["fare"]["amount"] <= 3000:
        pytest.skip("fare fits in the 3,000 starting balance")
    r = api.book("okello", est["id"], "wallet")
    assert_error(r, 402, "INSUFFICIENT_BALANCE")
    assert api.get("/v1/trips", "okello").json()["total"] == 0


@pytest.mark.negative
@pytest.mark.state
@pytest.mark.inferred
def test_failed_wallet_booking_does_not_burn_estimate(api):
    est = api.new_estimate("okello")
    if est["fare"]["amount"] <= 3000:
        pytest.skip("fare fits in the balance")
    assert api.book("okello", est["id"], "wallet").status_code == 402
    assert api.book("okello", est["id"], "cash").status_code == 201


@pytest.mark.boundary
@pytest.mark.parametrize("delta,expected", [pytest.param(-1, 402, marks=pytest.mark.negative), pytest.param(0, 201, marks=pytest.mark.positive),
                                            pytest.param(1, 201, marks=pytest.mark.positive)])
def test_wallet_balance_boundary(api, delta, expected):
    """Balance == fare must be accepted ('at least fare.amount'); fare-1 rejected."""
    est = api.new_estimate("okello")
    needed = est["fare"]["amount"] - 3000 + delta
    if needed < 500:
        pytest.skip("cannot reach this balance with the 500 minimum top-up")
    assert api.topup("okello", needed).status_code == 201
    assert api.balance("okello") == est["fare"]["amount"] + delta
    assert api.book("okello", est["id"], "wallet").status_code == expected


# ---- cancellation ---------------------------------------------------------------------
@pytest.mark.positive
@pytest.mark.state
def test_cancel_requested_trip(api):
    t = api.new_trip("nakato", "wallet")
    r = api.post(f"/v1/trips/{t['id']}/cancel", "nakato", json={"reason": "Driver is taking too long"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["status"] == "cancelled" and b["cancel_reason"] == "Driver is taking too long"
    assert b["status_history"][-1]["status"] == "cancelled"
    assert api.balance("nakato") == 25000 and api.ledger("nakato")["data"] == []


@pytest.mark.positive
def test_cancel_without_body(api):
    t = api.new_trip()
    assert api.post(f"/v1/trips/{t['id']}/cancel", "nakato").status_code == 200


@pytest.mark.positive
@pytest.mark.state
@pytest.mark.parametrize("upto", ["accept", "arrive"])
def test_cancel_after_accept_or_arrive_allowed_and_frees_driver(api, upto):
    t1 = api.new_trip()
    api.drive(t1["id"], upto=upto)
    assert api.post(f"/v1/trips/{t1['id']}/cancel", "nakato").status_code == 200
    t2 = api.new_trip()
    r = api.driver_step("ssemanda", t2["id"], "accept")
    assert r.status_code == 200, f"driver still busy after rider cancelled: {r.text}"


@pytest.mark.negative
@pytest.mark.state
def test_cancel_twice(api):
    t = api.new_trip()
    api.post(f"/v1/trips/{t['id']}/cancel", "nakato")
    assert_error(api.post(f"/v1/trips/{t['id']}/cancel", "nakato"), 409, "ALREADY_CANCELLED")


@pytest.mark.negative
@pytest.mark.state
def test_cancel_in_progress(api):
    t = api.new_trip()
    api.drive(t["id"], upto="start")
    assert_error(api.post(f"/v1/trips/{t['id']}/cancel", "nakato"), 409, "TRIP_IN_PROGRESS")


@pytest.mark.negative
@pytest.mark.state
def test_cancel_completed(api):
    t = api.new_trip("nakato", "wallet")
    api.drive(t["id"])
    assert_error(api.post(f"/v1/trips/{t['id']}/cancel", "nakato"), 409, "TRIP_COMPLETED")
    assert api.balance("nakato") == 25000 - t["fare"]["amount"]


@pytest.mark.negative
def test_cannot_cancel_someone_elses_trip(api):
    t = api.new_trip("nakato")
    assert_error(api.post(f"/v1/trips/{t['id']}/cancel", "okello"), 404, "TRIP_NOT_FOUND")
    assert api.get_trip("nakato", t["id"])["status"] == "requested"


@pytest.mark.negative
@pytest.mark.boundary
def test_cancel_reason_length(api):
    t = api.new_trip()
    r = api.post(f"/v1/trips/{t['id']}/cancel", "nakato", json={"reason": "r" * 201})
    assert r.status_code == 422 or (r.status_code == 200 and len(r.json()["cancel_reason"]) <= 200), r.text[:200]


@pytest.mark.negative
def test_cancel_unknown_trip_404(api):
    assert_error(api.post("/v1/trips/trp_000000000000/cancel", "nakato"), 404, "TRIP_NOT_FOUND")


@pytest.mark.negative
def test_driver_token_cannot_cancel_rider_trip(api):
    t = api.new_trip()
    api.drive(t["id"], upto="accept")
    r = api.post(f"/v1/trips/{t['id']}/cancel", "ssemanda")
    assert r.status_code in (401, 403, 404), f"driver cancelled the rider's trip: {r.status_code} {r.text[:200]}"
    assert api.get_trip("nakato", t["id"])["status"] == "accepted"


@pytest.mark.negative
@pytest.mark.parametrize("reason", [123, ["late"], {"r": 1}], ids=["int", "list", "object"])
def test_cancel_reason_wrong_type(api, reason):
    """Spec: reason is a string (maxLength 200). Wrong type must be refused and the trip left alone."""
    t = api.new_trip()
    assert_error(api.post(f"/v1/trips/{t['id']}/cancel", "nakato", json={"reason": reason}), 422, "VALIDATION_ERROR")
    assert api.get_trip("nakato", t["id"])["status"] == "requested"


@pytest.mark.negative
@pytest.mark.state
def test_other_rider_cannot_cancel_accepted_trip(api):
    t = api.new_trip("nakato")
    api.drive(t["id"], upto="accept")
    assert_error(api.post(f"/v1/trips/{t['id']}/cancel", "okello"), 404, "TRIP_NOT_FOUND")
    assert api.get_trip("nakato", t["id"])["status"] == "accepted"


# ---- read access ---------------------------------------------------------------------
@pytest.mark.negative
def test_get_trip_isolation(api):
    t = api.new_trip("nakato")
    assert api.get(f"/v1/trips/{t['id']}", "nakato").status_code == 200
    assert_error(api.get(f"/v1/trips/{t['id']}", "okello"), 404, "TRIP_NOT_FOUND")


@pytest.mark.positive
def test_list_only_own_trips(api):
    api.new_trip("nakato")
    assert api.get("/v1/trips", "okello").json()["total"] == 0


@pytest.mark.positive
def test_list_pagination(api):
    ids = {api.new_trip()["id"] for _ in range(3)}
    p1 = api.get("/v1/trips", "nakato", params={"page_size": 2}).json()
    p2 = api.get("/v1/trips", "nakato", params={"page_size": 2, "page": 2}).json()
    assert (p1["total"], p1["page"], p1["page_size"], len(p1["data"]), len(p2["data"])) == (3, 1, 2, 2, 1)
    assert {t["id"] for t in p1["data"]} | {t["id"] for t in p2["data"]} == ids, "pages overlap or lose trips"


@pytest.mark.positive
@pytest.mark.boundary
def test_list_default_page_size_is_10(api):
    for _ in range(11):
        api.new_trip()
    r = api.get("/v1/trips", "nakato").json()
    assert r["page_size"] == 10 and len(r["data"]) == 10 and r["total"] == 11


@pytest.mark.boundary
def test_list_page_past_end_is_empty(api):
    api.new_trip()
    r = api.get("/v1/trips", "nakato", params={"page": 5})
    assert r.status_code == 200 and r.json()["data"] == []


@pytest.mark.positive
@pytest.mark.state
def test_list_status_filter(api):
    a, b = api.new_trip(), api.new_trip()
    api.post(f"/v1/trips/{b['id']}/cancel", "nakato")
    for status, expect in (("requested", {a["id"]}), ("cancelled", {b["id"]})):
        r = api.get("/v1/trips", "nakato", params={"status": status}).json()
        assert {t["id"] for t in r["data"]} == expect and r["total"] == len(expect)


@pytest.mark.negative
@pytest.mark.parametrize("params", [pytest.param({"page": 0}, marks=pytest.mark.boundary), {"page": -1}, pytest.param({"page_size": 0}, marks=pytest.mark.boundary),
                                    pytest.param({"page_size": 51}, marks=pytest.mark.boundary), {"page": "abc"}, {"page_size": "x"},
                                    {"status": "bogus"}, {"status": "REQUESTED"}, {"page": 1.5}, {"page_size": -5}], ids=str)
def test_list_invalid_params(api, params):
    assert_error(api.get("/v1/trips", "nakato", params=params), 422)


@pytest.mark.negative
def test_list_trips_driver_token_rejected(api):
    r = api.get("/v1/trips", "ssemanda")
    assert r.status_code in (401, 403), f"driver token listed rider trips: {r.status_code}"


@pytest.mark.negative
def test_list_other_riders_trips_not_visible_with_filters(api):
    t = api.new_trip("nakato")
    api.post(f"/v1/trips/{t['id']}/cancel", "nakato")
    for params in ({"status": "cancelled"}, {"page_size": 50}):
        assert api.get("/v1/trips", "okello", params=params).json()["total"] == 0


@pytest.mark.positive
@pytest.mark.boundary
def test_list_page_size_50_allowed(api):
    assert api.get("/v1/trips", "nakato", params={"page_size": 50}).status_code == 200


# ---- scheduling ---------------------------------------------------------------------------
def _iso(dt):
    return dt.isoformat()


@pytest.mark.positive
def test_schedule_valid_returned_in_utc(api):
    est = api.new_estimate()
    when = (utcnow() + timedelta(hours=2)).astimezone(__import__("datetime").timezone(timedelta(hours=3)))
    r = api.book("nakato", est["id"], scheduled_for=_iso(when))
    assert r.status_code == 201, r.text
    got = r.json()["scheduled_for"]
    assert parse_dt(got).utcoffset() == timedelta(0), f"not UTC: {got}"
    assert abs((parse_dt(got) - when).total_seconds()) < 1, "instant changed during conversion"


@pytest.mark.boundary
@pytest.mark.parametrize("delta,ok", [
    pytest.param(timedelta(minutes=-5), False, marks=pytest.mark.negative), pytest.param(timedelta(minutes=10), False, marks=pytest.mark.negative),
    pytest.param(timedelta(minutes=29), False, marks=[pytest.mark.boundary, pytest.mark.negative]), pytest.param(timedelta(minutes=31), True, marks=[pytest.mark.boundary, pytest.mark.positive]),
    pytest.param(timedelta(days=6, hours=23), True, marks=[pytest.mark.boundary, pytest.mark.positive]),
    pytest.param(timedelta(days=7, minutes=10), False, marks=[pytest.mark.boundary, pytest.mark.negative]), pytest.param(timedelta(days=30), False, marks=pytest.mark.negative)])
def test_schedule_window(api, delta, ok):
    est = api.new_estimate()
    r = api.book("nakato", est["id"], scheduled_for=_iso(utcnow() + delta))
    if ok:
        assert r.status_code == 201, r.text
    else:
        assert_error(r, 422, "INVALID_SCHEDULE")


@pytest.mark.negative
@pytest.mark.parametrize("value", ["tomorrow", "2026-13-45T00:00:00Z", 12345, "", "2026-10-28"])
def test_schedule_garbage_never_5xx(api, value):
    est = api.new_estimate()
    r = api.book("nakato", est["id"], scheduled_for=value)
    assert r.status_code in (422, 201) and r.status_code < 500


@pytest.mark.positive
def test_schedule_null_means_now(api):
    est = api.new_estimate()
    r = api.book("nakato", est["id"], scheduled_for=None)
    assert r.status_code == 201 and r.json()["scheduled_for"] is None


# ---- rating -----------------------------------------------------------------------------------
def _completed(api):
    t = api.new_trip()
    api.drive(t["id"])
    return t["id"]


@pytest.mark.positive
@pytest.mark.state
def test_rate_completed_trip(api):
    tid = _completed(api)
    r = api.post(f"/v1/trips/{tid}/rating", "nakato", json={"stars": 5, "comment": "Safe ride, had a helmet ready"})
    assert r.status_code == 201, r.text
    assert (r.json()["trip_id"], r.json()["stars"]) == (tid, 5)
    assert api.get_trip("nakato", tid)["rating"]["stars"] == 5


@pytest.mark.positive
@pytest.mark.boundary
@pytest.mark.state
@pytest.mark.parametrize("stars", [1, 5])
def test_rating_boundaries_ok(api, stars):
    assert api.post(f"/v1/trips/{_completed(api)}/rating", "nakato", json={"stars": stars}).status_code == 201


@pytest.mark.negative
@pytest.mark.parametrize("body", [pytest.param({"stars": 0}, marks=pytest.mark.boundary), pytest.param({"stars": 6}, marks=pytest.mark.boundary), {"stars": -1},
                                  {"stars": "5"}, {"stars": 4.5}, {"stars": None}, {},
                                  pytest.param({"stars": 5, "comment": "c" * 501}, marks=pytest.mark.boundary), {"stars": True}], ids=str)
def test_rating_validation(api, body):
    assert_error(api.post(f"/v1/trips/{_completed(api)}/rating", "nakato", json=body), 422, "VALIDATION_ERROR")


@pytest.mark.positive
@pytest.mark.boundary
def test_rating_comment_500_ok(api):
    assert api.post(f"/v1/trips/{_completed(api)}/rating", "nakato", json={"stars": 4, "comment": "c" * 500}).status_code == 201


@pytest.mark.negative
@pytest.mark.state
def test_rating_only_once(api):
    tid = _completed(api)
    api.post(f"/v1/trips/{tid}/rating", "nakato", json={"stars": 5})
    assert_error(api.post(f"/v1/trips/{tid}/rating", "nakato", json={"stars": 1}), 409, "ALREADY_RATED")
    assert api.get_trip("nakato", tid)["rating"]["stars"] == 5, "second rating overwrote the first"


@pytest.mark.negative
@pytest.mark.state
@pytest.mark.parametrize("upto", [None, "accept", "arrive", "start"])
def test_rating_before_completion(api, upto):
    t = api.new_trip()
    if upto:
        api.drive(t["id"], upto=upto)
    assert_error(api.post(f"/v1/trips/{t['id']}/rating", "nakato", json={"stars": 5}), 409, "TRIP_NOT_COMPLETED")


@pytest.mark.negative
@pytest.mark.state
def test_rating_cancelled_trip(api):
    t = api.new_trip()
    api.post(f"/v1/trips/{t['id']}/cancel", "nakato")
    assert_error(api.post(f"/v1/trips/{t['id']}/rating", "nakato", json={"stars": 5}), 409, "TRIP_NOT_COMPLETED")


@pytest.mark.negative
def test_cannot_rate_someone_elses_trip(api):
    tid = _completed(api)
    assert_error(api.post(f"/v1/trips/{tid}/rating", "okello", json={"stars": 1}), 404, "TRIP_NOT_FOUND")


@pytest.mark.negative
def test_rating_unknown_trip(api):
    assert_error(api.post("/v1/trips/trp_NOPE/rating", "nakato", json={"stars": 5}), 404, "TRIP_NOT_FOUND")
