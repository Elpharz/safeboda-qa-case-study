"""Race conditions on the things that cost money or double-assign drivers."""
import uuid

import pytest

from qa_api import run_parallel

pytestmark = pytest.mark.concurrency


@pytest.mark.state
def test_two_drivers_accept_same_trip_exactly_one_wins(api):
    t = api.new_trip()
    rs = run_parallel(lambda i: api.driver_step(["ssemanda", "achieng"][i], t["id"], "accept"), 2)
    codes = sorted(r.status_code for r in rs)
    assert codes == [200, 409], codes
    winner = api.get_trip("nakato", t["id"])["driver"]["name"]
    assert winner in ("Joseph Ssemanda", "Grace Achieng")


@pytest.mark.state
def test_same_estimate_booked_in_parallel_creates_one_trip(api):
    est = api.new_estimate()
    rs = run_parallel(lambda i: api.book("nakato", est["id"], idem=str(uuid.uuid4())), 8)
    codes = sorted(r.status_code for r in rs)
    assert codes.count(201) == 1 and codes.count(409) == 7, codes
    assert api.get("/v1/trips", "nakato").json()["total"] == 1


@pytest.mark.state
def test_same_idempotency_key_booked_in_parallel_creates_one_trip(api):
    est, key = api.new_estimate(), str(uuid.uuid4())
    rs = run_parallel(lambda i: api.book("nakato", est["id"], idem=key), 8)
    assert {r.status_code for r in rs} <= {200, 201}, [r.status_code for r in rs]
    assert len({r.json()["id"] for r in rs}) == 1
    assert api.get("/v1/trips", "nakato").json()["total"] == 1


@pytest.mark.state
def test_parallel_complete_charges_wallet_once(api):
    t = api.new_trip("nakato", "wallet")
    api.drive(t["id"], upto="start")
    rs = run_parallel(lambda i: api.driver_step("ssemanda", t["id"], "complete"), 6)
    codes = [r.status_code for r in rs]
    charges = len([x for x in api.ledger("nakato")["data"] if x["type"] == "trip_charge"])
    charged = 25000 - api.balance("nakato")
    # Check money first so the failure message says what the rider lost, not just the status codes.
    assert (charges, charged) == (1, t["fare"]["amount"]), \
        f"wallet charged {charges}x ({charged} UGX for a {t['fare']['amount']} UGX fare); statuses {codes}"
    assert codes.count(200) == 1, codes


@pytest.mark.state
def test_cancel_and_accept_race_leaves_consistent_state(api):
    t = api.new_trip()

    def act(i):
        return api.post(f"/v1/trips/{t['id']}/cancel", "nakato") if i == 0 else api.driver_step("ssemanda", t["id"], "accept")

    run_parallel(act, 2)
    final = api.get_trip("nakato", t["id"])
    assert final["status"] in ("cancelled", "accepted")
    assert (final["status"] == "accepted") == (final["driver"] is not None), f"inconsistent: {final['status']} / {final['driver']}"


@pytest.mark.negative
@pytest.mark.state
@pytest.mark.boundary
@pytest.mark.spec_gap
def test_two_wallet_bookings_cannot_overdraw_on_completion(api):
    """Spec checks balance at booking but charges at completion. Two bookings, each affordable
    alone, must not leave the wallet negative. Spec is silent on which step should refuse."""
    probe = api.new_estimate("okello")
    fare = probe["fare"]["amount"]
    if fare <= 3000:
        pytest.skip("fare fits in starting balance")
    need = fare - 3000
    if need < 500:
        pytest.skip("cannot construct balance")
    api.topup("okello", need)  # balance == fare exactly: affordable once, not twice
    ests = [api.new_estimate("okello") for _ in range(2)]
    rs = [api.book("okello", e["id"], "wallet") for e in ests]
    booked = [r.json()["id"] for r in rs if r.status_code == 201]
    for tid, drv in zip(booked, ("ssemanda", "achieng")):
        api.drive(tid, driver=drv)
    assert api.balance("okello") >= 0, f"wallet overdrawn: {api.balance('okello')}"
