#!/usr/bin/env python3
"""Re-run the single-request reproduction of each bug in BUGS.md and print status, request_id and body excerpt.

    CANDIDATE_KEY=... python tools/repro_bugs.py            # all
    CANDIDATE_KEY=... python tools/repro_bugs.py BUG-02     # one

Uses the same helpers as the suite; resets the sandbox before each bug. Race bugs are not here: use
`pytest -m concurrency` in a loop (see BUGS.md for the n/20 figures).
"""
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SCHEMA_VALIDATION", "0")  # we want to SEE the bad responses here, not raise on them
from qa_api import ACACIA, NEAR_ACACIA, NTINDA, OKELLO_PHONE, Api, utcnow  # noqa: E402


def rid(r):
    try:
        return r.json().get("error", {}).get("request_id") or r.headers.get("x-request-id") or "-"
    except ValueError:
        return r.headers.get("x-request-id") or "-"


def show(bug, r, note=""):
    print(f"{bug}: {r.request.method} {r.request.path_url} -> {r.status_code} request_id={rid(r)} {note}\n    {r.text[:260]}")


def bug01(a):
    k = str(uuid.uuid4())
    body = {"amount": 10000, "provider": "mtn_momo", "phone": OKELLO_PHONE}
    r1 = a.post("/v1/wallet/top-ups", "okello", json=body, headers={"Idempotency-Key": k})
    r2 = a.post("/v1/wallet/top-ups", "okello", json=body, headers={"Idempotency-Key": k})
    show("BUG-01", r2, f"(first {r1.status_code}, ids {r1.json().get('id')} / {r2.json().get('id')}, balance now {a.balance('okello')}, expected 13000)")


def bug02(a):
    t = a.new_trip("nakato")
    show("BUG-02", a.get(f"/v1/trips/{t['id']}", "okello"), "(Okello reading Nakato's trip)")


def bug03(a):
    t = a.new_trip("okello")
    show("BUG-03", a.post("/v1/support/chat", "nakato", json={"message": "Refund me", "trip_id": t["id"]}), "(Nakato chatting about Okello's trip)")


def bug04(a):
    show("BUG-04", a.estimate(pickup=ACACIA, dropoff=NEAR_ACACIA, service="send", promo="SENDFREE"))


def bug05(a):
    est = a.new_estimate("okello")
    a.topup("okello", est["fare"]["amount"] - 3000)
    ids = [a.book("okello", a.new_estimate("okello")["id"], "wallet").json()["id"] for _ in range(2)]
    for tid, d in zip(ids, ("ssemanda", "achieng")):
        a.drive(tid, driver=d)
    print(f"BUG-05: two wallet trips booked on balance == fare and completed; balance now {a.balance('okello')}")


def bug09(a):
    show("BUG-09", a.post("/v1/fare-estimates", "nakato", raw="null"))


def bug10(a):
    t = a.new_trip("nakato", "wallet")
    a.drive(t["id"])
    show("BUG-10", a.post(f"/v1/trips/{t['id']}/cancel", "nakato"))


def bug11(a):
    show("BUG-11", a.estimate(service="car"))


def bug12(a):
    t = a.new_trip()
    show("BUG-12", a.post(f"/v1/trips/{t['id']}/rating", "nakato", json={"stars": 5}), "(trip still 'requested')")


def bug13(a):
    est = a.new_estimate()
    from datetime import timezone
    when = (utcnow() + timedelta(hours=2)).astimezone(timezone(timedelta(hours=3))).replace(microsecond=0)
    r = a.book("nakato", est["id"], scheduled_for=when.isoformat())
    show("BUG-13", r, f"(sent {when.isoformat()}, expected {when.astimezone(timezone.utc).isoformat()}, got {r.json().get('scheduled_for')})")


def bug14(a):
    for _ in range(3):
        a.new_trip()
    show("BUG-14", a.get("/v1/trips", "nakato", params={"page_size": 2, "page": 2}), "(3 trips, page 2 of size 2 should hold 1)")


def bug15(a):
    show("BUG-15", a.estimate(dropoff={"lat": 91, "lng": 32.59352, "label": "Acacia Mall"}))


def bug16(a):
    show("BUG-16", a.get("/v1/trips", "nakato", params={"status": "bogus"}))


def bug17(a):
    show("BUG-17", a.book("nakato", a.new_estimate()["id"], notes="n" * 201))


def bug18(a):
    t = a.new_trip()
    show("BUG-18", a.post(f"/v1/trips/{t['id']}/cancel", "nakato", json={"reason": 123}))


def bug19(a):
    show("BUG-19a", a.post("/v1/trips", "nakato", raw="{nope", headers={"Idempotency-Key": "x"}))
    show("BUG-19b", a.get("/v1/me", "ssemanda"))


BUGS = {k.upper().replace("BUG", "BUG-"): v for k, v in globals().items() if k.startswith("bug") and k[3:].isdigit()}

if __name__ == "__main__":
    api = Api(os.environ["CANDIDATE_KEY"])
    for name, fn in BUGS.items():
        if len(sys.argv) > 1 and name not in sys.argv[1:]:
            continue
        api.reset()
        fn(api)
