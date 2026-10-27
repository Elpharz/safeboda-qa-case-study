"""Fare estimates: shape, pricing rules, promos, validation."""
import math

import pytest

from qa_api import (ACACIA, JUST_FAR_ENOUGH_FROM_ACACIA, NAIROBI, NEAR_ACACIA, NTINDA, TOO_CLOSE_TO_ACACIA, assert_error,
                    parse_dt)


def haversine_km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dphi, dl = p2 - p1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@pytest.mark.positive
def test_estimate_happy_path_shape(api):
    est = api.new_estimate()
    assert est["id"].startswith("est_")
    assert est["service_type"] == "boda" and est["promo_code"] is None
    assert est["eta_minutes"] > 0 and isinstance(est["eta_minutes"], int)
    f = est["fare"]
    assert f["currency"] == "UGX" and f["discount"] == 0
    assert f["amount"] == f["original_amount"] > 0


@pytest.mark.positive
def test_estimate_valid_for_five_minutes(api):
    est = api.new_estimate()
    delta = (parse_dt(est["expires_at"]) - parse_dt(est["created_at"])).total_seconds()
    assert abs(delta - 300) <= 2, delta


@pytest.mark.positive
def test_distance_is_plausible_vs_straight_line(api):
    est = api.new_estimate()
    straight = haversine_km(ACACIA, NTINDA)
    assert 0.9 * straight <= est["distance_km"] <= 2.5 * straight, (est["distance_km"], straight)


@pytest.mark.positive
def test_estimate_is_deterministic(api):
    a, b = api.new_estimate(), api.new_estimate()
    assert a["fare"] == b["fare"] and a["distance_km"] == b["distance_km"]
    assert a["id"] != b["id"]


@pytest.mark.positive
@pytest.mark.parametrize("service", ["boda", "send"])
def test_boda_and_send_round_to_nearest_100(api, service):
    f = api.new_estimate(service=service)["fare"]
    assert f["original_amount"] % 100 == 0, f


@pytest.mark.positive
def test_car_estimate_works(api):
    f = api.new_estimate(service="car")["fare"]
    assert f["amount"] > 0


@pytest.mark.positive
def test_longer_trip_never_cheaper(api):
    short = api.new_estimate(dropoff=NEAR_ACACIA, pickup=ACACIA)
    long_ = api.new_estimate()
    assert short["distance_km"] < long_["distance_km"]
    assert short["fare"]["original_amount"] <= long_["fare"]["original_amount"]


@pytest.mark.positive
def test_reverse_route_similar_distance(api):
    a, b = api.new_estimate(), api.new_estimate(pickup=NTINDA, dropoff=ACACIA)
    assert abs(a["distance_km"] - b["distance_km"]) < 0.5


# ---- promos ----------------------------------------------------------------------
@pytest.mark.positive
def test_safe20_is_twenty_percent_off(api):
    f = api.new_estimate(promo="SAFE20")["fare"]
    assert f["amount"] == f["original_amount"] - f["discount"]
    assert abs(f["discount"] - 0.2 * f["original_amount"]) <= 50, f


@pytest.mark.positive
def test_boda2000_takes_2000_off_boda(api):
    f = api.new_estimate(promo="BODA2000")["fare"]
    assert f["discount"] == min(2000, f["original_amount"]) and f["amount"] == f["original_amount"] - f["discount"]


@pytest.mark.positive
def test_sendfree_takes_4000_off_send(api):
    f = api.new_estimate(service="send", promo="SENDFREE")["fare"]
    assert f["discount"] == min(4000, f["original_amount"]) and f["amount"] == f["original_amount"] - f["discount"]


@pytest.mark.negative
@pytest.mark.parametrize("promo,service", [("BODA2000", "car"), ("BODA2000", "send"), ("SENDFREE", "boda"), ("SENDFREE", "car")])
def test_promo_not_applicable_to_other_service(api, promo, service):
    assert_error(api.estimate(promo=promo, service=service), 422, "PROMO_NOT_APPLICABLE")


@pytest.mark.negative
@pytest.mark.parametrize("promo", ["NOPE", "SAFE21", "SAFE20 ", "SAFE200", "' OR 1=1"])
def test_unknown_promo_rejected(api, promo):
    assert_error(api.estimate(promo=promo), 422, "INVALID_PROMO")


@pytest.mark.positive
@pytest.mark.boundary
@pytest.mark.parametrize("promo,service", [("BODA2000", "boda"), ("SENDFREE", "send"), ("SAFE20", "boda"), ("SAFE20", "car")])
def test_fare_never_negative_on_very_short_trip(api, promo, service):
    f = api.new_estimate(pickup=ACACIA, dropoff=NEAR_ACACIA, service=service, promo=promo)["fare"]
    assert f["amount"] >= 0 and f["discount"] <= f["original_amount"] and f["amount"] == f["original_amount"] - f["discount"]


@pytest.mark.negative
def test_lowercase_promo_never_5xx(api):
    assert api.estimate(promo="safe20").status_code in (201, 422)


# ---- validation --------------------------------------------------------------------
@pytest.mark.negative
@pytest.mark.parametrize("field", ["pickup", "dropoff", "service_type"])
def test_missing_required_field(api, field):
    body = {"pickup": ACACIA, "dropoff": NTINDA, "service_type": "boda"}
    body.pop(field)
    assert_error(api.post("/v1/fare-estimates", "nakato", json=body), 422, "VALIDATION_ERROR")


@pytest.mark.negative
@pytest.mark.parametrize("bad", [
    pytest.param({**ACACIA, "lat": 91}, marks=pytest.mark.boundary, id="lat91"), pytest.param({**ACACIA, "lat": -91}, marks=pytest.mark.boundary, id="lat-91"),
    pytest.param({**ACACIA, "lng": 181}, marks=pytest.mark.boundary, id="lng181"), pytest.param({**ACACIA, "lng": -181}, marks=pytest.mark.boundary, id="lng-181"),
    pytest.param({**ACACIA, "lat": "0.33"}, id="lat-string"), pytest.param({"lat": 0.3}, id="no-lng"),
    pytest.param({**ACACIA, "label": "x" * 121}, marks=pytest.mark.boundary, id="label121"), pytest.param({**ACACIA, "lat": None}, id="lat-null")])
@pytest.mark.parametrize("which", ["pickup", "dropoff"])
def test_invalid_point(api, which, bad):
    kw = {"pickup": ACACIA, "dropoff": NTINDA}
    kw[which] = bad
    r = api.estimate(**kw)
    assert_error(r, 422)


@pytest.mark.negative
@pytest.mark.parametrize("service", ["bus", "BODA", "", None, 1])
def test_invalid_service_type(api, service):
    r = api.post("/v1/fare-estimates", "nakato", json={"pickup": ACACIA, "dropoff": NTINDA, "service_type": service})
    assert_error(r, 422, "VALIDATION_ERROR")


@pytest.mark.negative
def test_same_location_rejected(api):
    assert_error(api.estimate(pickup=ACACIA, dropoff=dict(ACACIA)), 422, "SAME_LOCATION")


@pytest.mark.boundary
@pytest.mark.spec_gap
@pytest.mark.parametrize("dropoff,ok", [pytest.param(TOO_CLOSE_TO_ACACIA, False, marks=pytest.mark.negative, id="50m"),
                                        pytest.param(JUST_FAR_ENOUGH_FROM_ACACIA, True, marks=pytest.mark.positive, id="100m"),
                                        pytest.param(NEAR_ACACIA, True, marks=pytest.mark.positive, id="400m")])
def test_same_location_threshold(api, dropoff, ok):
    """Spec names SAME_LOCATION but gives no distance. Measured 22 Oct 2026: <=70 m rejected, >=75 m accepted.
    Pins the behaviour so a change (e.g. 500 m threshold breaking short trips) is noticed. Confirm the number with product."""
    r = api.estimate(pickup=ACACIA, dropoff=dropoff)
    if ok:
        assert r.status_code == 201, r.text[:200]
    else:
        assert_error(r, 422, "SAME_LOCATION")


@pytest.mark.negative
@pytest.mark.parametrize("point", [NAIROBI, {"lat": 0, "lng": 0}, {"lat": 51.5, "lng": -0.12}], ids=["nairobi", "null-island", "london"])
def test_pickup_outside_service_area(api, point):
    assert_error(api.estimate(pickup=point, dropoff=NTINDA), 422, "OUTSIDE_SERVICE_AREA")


@pytest.mark.negative
def test_estimate_requires_rider_auth(api):
    r = api.post("/v1/fare-estimates", json={"pickup": ACACIA, "dropoff": NTINDA, "service_type": "boda"})
    assert_error(r, 401)


@pytest.mark.negative
@pytest.mark.state
@pytest.mark.boundary
@pytest.mark.slow
def test_expired_estimate_cannot_be_booked(api):
    """Waits 5+ minutes. Nightly only (RUN_SLOW=1)."""
    import time
    est = api.new_estimate()
    time.sleep(305)
    assert_error(api.book("nakato", est["id"]), 410, "ESTIMATE_EXPIRED")
