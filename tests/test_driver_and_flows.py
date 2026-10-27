"""Driver state machine, assignment rules and end-to-end journeys."""
import pytest

from qa_api import GARDEN_CITY, MAKERERE, assert_error, parse_dt


def _ids(resp):
    return {t.get("id") or t.get("trip_id") for t in resp.json()["data"]}


# ---- full journeys -------------------------------------------------------------------
@pytest.mark.positive
@pytest.mark.state
def test_full_wallet_journey_book_accept_complete_rate(api):
    before = api.balance("nakato")
    t = api.new_trip("nakato", "wallet", promo="SAFE20")
    assert t["id"] in _ids(api.get("/v1/driver/trips/available", "ssemanda"))

    seen = []
    for step, expected in (("accept", "accepted"), ("arrive", "arrived"), ("start", "in_progress"), ("complete", "completed")):
        r = api.driver_step("ssemanda", t["id"], step)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == expected
        seen.append(expected)
        assert api.get_trip("nakato", t["id"])["status"] == expected, "rider view out of sync with driver action"

    final = api.get_trip("nakato", t["id"])
    assert [h["status"] for h in final["status_history"]] == ["requested"] + seen
    times = [parse_dt(h["at"]) for h in final["status_history"]]
    assert times == sorted(times), "status_history timestamps go backwards"
    assert parse_dt(final["updated_at"]) >= parse_dt(final["created_at"])
    assert final["driver"]["name"] == "Joseph Ssemanda" and final["driver"]["plate"] == "UFA 412K"
    assert api.balance("nakato") == before - t["fare"]["amount"]

    r = api.post(f"/v1/trips/{t['id']}/rating", "nakato", json={"stars": 5, "comment": "Great"})
    assert r.status_code == 201
    assert api.get_trip("nakato", t["id"])["rating"]["stars"] == 5


@pytest.mark.positive
@pytest.mark.state
def test_full_car_journey_with_car_driver(api):
    t = api.new_trip("nakato", "cash", service="car")
    assert api.drive(t["id"], driver="mugisha")["driver"]["plate"] == "UBK 733Q"


@pytest.mark.positive
@pytest.mark.state
def test_send_journey_with_boda_driver(api):
    t = api.new_trip("nakato", "cash", service="send")
    assert api.drive(t["id"], driver="achieng")["status"] == "completed"


# ---- availability & assignment ----------------------------------------------------------
@pytest.mark.positive
def test_available_trips_filtered_by_service(api):
    boda, car = api.new_trip(service="boda")["id"], api.new_trip(service="car")["id"]
    joseph, david = _ids(api.get("/v1/driver/trips/available", "ssemanda")), _ids(api.get("/v1/driver/trips/available", "mugisha"))
    assert boda in joseph and car not in joseph
    assert car in david and boda not in david


@pytest.mark.state
def test_cancelled_and_accepted_trips_not_available(api):
    a, b = api.new_trip()["id"], api.new_trip()["id"]
    api.post(f"/v1/trips/{a}/cancel", "nakato")
    api.driver_step("ssemanda", b, "accept")
    avail = _ids(api.get("/v1/driver/trips/available", "achieng"))
    assert a not in avail and b not in avail


@pytest.mark.negative
@pytest.mark.parametrize("driver,service", [("mugisha", "boda"), ("mugisha", "send"), ("ssemanda", "car"), ("achieng", "car")])
def test_service_mismatch(api, driver, service):
    t = api.new_trip(service=service)
    assert_error(api.driver_step(driver, t["id"], "accept"), 403, "SERVICE_MISMATCH")
    assert api.get_trip("nakato", t["id"])["status"] == "requested"


@pytest.mark.negative
@pytest.mark.state
def test_second_driver_cannot_take_accepted_trip(api):
    t = api.new_trip()
    api.driver_step("ssemanda", t["id"], "accept")
    assert_error(api.driver_step("achieng", t["id"], "accept"), 409, "TRIP_NOT_AVAILABLE")
    assert api.get_trip("nakato", t["id"])["driver"]["name"] == "Joseph Ssemanda"


@pytest.mark.negative
@pytest.mark.state
def test_driver_cannot_accept_cancelled_trip(api):
    t = api.new_trip()
    api.post(f"/v1/trips/{t['id']}/cancel", "nakato")
    assert_error(api.driver_step("ssemanda", t["id"], "accept"), 409, "TRIP_NOT_AVAILABLE")


@pytest.mark.negative
@pytest.mark.state
def test_driver_busy_with_active_trip(api):
    a, b = api.new_trip()["id"], api.new_trip(pickup=GARDEN_CITY, dropoff=MAKERERE)["id"]
    assert api.driver_step("ssemanda", a, "accept").status_code == 200
    assert_error(api.driver_step("ssemanda", b, "accept"), 409, "DRIVER_BUSY")


@pytest.mark.positive
@pytest.mark.state
def test_driver_free_again_after_completion(api):
    a = api.new_trip()["id"]
    api.drive(a)
    assert api.driver_step("ssemanda", api.new_trip()["id"], "accept").status_code == 200


@pytest.mark.state
def test_accept_is_idempotent_or_conflicts_cleanly(api):
    t = api.new_trip()
    api.driver_step("ssemanda", t["id"], "accept")
    r = api.driver_step("ssemanda", t["id"], "accept")
    assert r.status_code in (200, 409) and r.status_code < 500


@pytest.mark.negative
@pytest.mark.parametrize("step", ["accept", "arrive", "start", "complete"])
def test_unknown_trip_404(api, step):
    assert_error(api.driver_step("ssemanda", "trp_NOPE", step), 404, "TRIP_NOT_FOUND")


# ---- state machine ---------------------------------------------------------------------------
@pytest.mark.parametrize("upto,illegal", [
    ("accept", "start"), ("accept", "complete"),
    ("arrive", "arrive"), ("arrive", "complete"),
    ("start", "arrive"), ("start", "start"),
    ("complete", "arrive"), ("complete", "start"), ("complete", "complete"),
])
@pytest.mark.negative
@pytest.mark.state
def test_invalid_transitions(api, upto, illegal):
    t = api.new_trip("nakato", "wallet")
    api.drive(t["id"], upto=upto)
    before = api.get_trip("nakato", t["id"])
    assert_error(api.driver_step("ssemanda", t["id"], illegal), 409, "INVALID_TRANSITION")
    after = api.get_trip("nakato", t["id"])
    assert after["status"] == before["status"] and len(after["status_history"]) == len(before["status_history"])


@pytest.mark.negative
@pytest.mark.state
def test_double_complete_charges_once(api):
    t = api.new_trip("nakato", "wallet")
    api.drive(t["id"])
    api.driver_step("ssemanda", t["id"], "complete")
    assert api.balance("nakato") == 25000 - t["fare"]["amount"]
    assert len([x for x in api.ledger("nakato")["data"] if x["type"] == "trip_charge"]) == 1


@pytest.mark.negative
@pytest.mark.state
@pytest.mark.parametrize("step", ["arrive", "start", "complete"])
def test_non_assigned_driver_cannot_progress_trip(api, step):
    t = api.new_trip()
    api.drive(t["id"], upto="accept" if step == "arrive" else {"start": "arrive", "complete": "start"}[step])
    assert_error(api.driver_step("achieng", t["id"], step), 403, "NOT_ASSIGNED_DRIVER")


@pytest.mark.negative
@pytest.mark.state
@pytest.mark.parametrize("step", ["arrive", "start", "complete"])
def test_driver_cannot_progress_unaccepted_trip(api, step):
    t = api.new_trip()
    r = api.driver_step("ssemanda", t["id"], step)
    assert r.status_code in (403, 409), f"unaccepted trip moved by {step}: {r.status_code} {r.text}"
    assert api.get_trip("nakato", t["id"])["status"] == "requested"


@pytest.mark.negative
def test_rider_cannot_call_driver_endpoints(api):
    t = api.new_trip()
    r = api.driver_step("nakato", t["id"], "accept")
    assert r.status_code in (401, 403)
    assert api.get_trip("nakato", t["id"])["status"] == "requested"
