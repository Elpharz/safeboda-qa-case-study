"""Thin API helper layer shared by the pytest suite and the Boda Assist evaluation.

No secrets live here. CANDIDATE_KEY must come from the environment.
Rider/driver tokens are the shared staging test accounts from the brief and
can be overridden with env vars.
"""
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from jsonschema import Draft202012Validator, FormatChecker

BASE_URL = os.getenv("BASE_URL", "https://staging-twende-backend.safeboda.com/api/qa-sandbox").rstrip("/")
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))

TOKENS = {
    "nakato": os.getenv("TOKEN_NAKATO", "rdr_tok_nakato_5f2a91"),
    "okello": os.getenv("TOKEN_OKELLO", "rdr_tok_okello_8c71d4"),
    "ssemanda": os.getenv("TOKEN_SSEMANDA", "drv_tok_ssemanda_3e09b7"),  # boda + send
    "achieng": os.getenv("TOKEN_ACHIENG", "drv_tok_achieng_7a44c2"),    # boda + send
    "mugisha": os.getenv("TOKEN_MUGISHA", "drv_tok_mugisha_1b6f80"),    # car
}
START_BALANCE = {"nakato": 25000, "okello": 3000}
OKELLO_PHONE = "+256700100487"

ACACIA = {"lat": 0.33495, "lng": 32.59352, "label": "Acacia Mall"}
NTINDA = {"lat": 0.35402, "lng": 32.61498, "label": "Ntinda Shopping Complex"}
# ~400 m north of Acacia. The API rejects points closer than ~70 m as SAME_LOCATION (measured 22 Oct 2026),
# so the old 50 m point made short-trip tests fail in setup. Verified: 201, distance_km 0.52.
NEAR_ACACIA = {"lat": 0.33855, "lng": 32.59352, "label": "Near Acacia"}
TOO_CLOSE_TO_ACACIA = {"lat": 0.33540, "lng": 32.59352, "label": "50 m from Acacia"}
JUST_FAR_ENOUGH_FROM_ACACIA = {"lat": 0.33585, "lng": 32.59352, "label": "100 m from Acacia"}
GARDEN_CITY = {"lat": 0.3189, "lng": 32.5934, "label": "Garden City"}
MAKERERE = {"lat": 0.3340, "lng": 32.5680, "label": "Makerere University"}
NAIROBI = {"lat": -1.2864, "lng": 36.8172, "label": "Nairobi CBD"}

ERROR_KEYS = {"code", "message", "request_id"}
LEAK_PATTERNS = [r"Traceback", r"\bat \S+ \(.*:\d+:\d+\)", r"\.py\b", r"node_modules", r"/usr/", r"/app/",
                 r"\bSELECT\b.*\bFROM\b", r"psycopg|sqlalchemy|sqlite|mongodb|ECONN", r"Exception in", r"stack ?trace"]


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def utcnow():
    return datetime.now(timezone.utc)


def assert_no_leak(text):
    for p in LEAK_PATTERNS:
        assert not re.search(p, text, re.I | re.S), f"internal detail leaked ({p}): {text[:300]}"


def assert_error(r, status, code=None):
    assert r.status_code == status, f"expected {status} got {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert set(body) == {"error"}, f"bad error envelope: {body}"
    assert set(body["error"]) == ERROR_KEYS, f"bad error keys: {body['error']}"
    if code:
        assert body["error"]["code"] == code, f"expected code {code} got {body['error']['code']}"
    assert_no_leak(r.text)
    return body["error"]


def run_parallel(fn, n):
    """Run fn(i) n times at (almost) the same instant. Returns results in index order."""
    barrier = threading.Barrier(n)

    def wrapped(i):
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(wrapped, range(n)))


# ---- response-schema validation against the OpenAPI spec --------------------------------
SPEC_PATH = Path(os.getenv("OPENAPI_SPEC", Path(__file__).with_name("openapi.json")))
SPEC_URL = BASE_URL + "/openapi.json"


class SandboxUnavailable(Exception):
    """Network-level failure (timeout, TLS, connection reset). Environment problem, not a product bug."""


class Secret(str):
    """A str that never prints its value (pytest shows fixture values in failure reports)."""

    def __repr__(self):
        return "'***'"


class SchemaMismatch(AssertionError):
    """A response did not match the schema the spec documents for that operation and status."""


def _to_jsonschema(node):
    """OpenAPI 3.0 -> JSON Schema 2020-12: `nullable`, component $refs."""
    if isinstance(node, list):
        return [_to_jsonschema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {k: _to_jsonschema(v) for k, v in node.items() if k not in ("nullable", "example")}
    if "$ref" in out:
        out["$ref"] = out["$ref"].replace("#/components/schemas/", "#/$defs/")
    if node.get("nullable"):
        return {"anyOf": [out, {"type": "null"}]}
    return out


def _is_datetime(v):
    if not isinstance(v, str):
        return True
    try:
        parse_dt(v)
        return "T" in v
    except ValueError:
        return False


class Contract:
    """Validates every response against the vendored spec and records what was exercised.

    Documented status  -> body must match that status's schema (SchemaMismatch otherwise).
    Undocumented 4xx/5xx -> body must still match the shared Error schema (the spec says all errors use it).
    Every call is logged (operation, status, validated?, test id) so coverage_report.py can show what was hit.
    SCHEMA_VALIDATION=0 turns the check off (logging stays on).
    """

    def __init__(self, spec_path=SPEC_PATH):
        self.enabled = os.getenv("SCHEMA_VALIDATION", "1") != "0"
        self.calls = []
        self._lock = threading.Lock()
        spec = json.loads(Path(spec_path).read_text())
        self.defs = _to_jsonschema(spec.get("components", {}).get("schemas", {}))
        self.ops = []
        for path, item in spec["paths"].items():
            rx = re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$")
            for m, op in item.items():
                if m.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    continue
                schemas = {}
                for code, resp in op.get("responses", {}).items():
                    sch = (resp.get("content") or {}).get("application/json", {}).get("schema")
                    schemas[code] = self._validator(sch) if sch else None
                self.ops.append((m.upper(), rx, f"{m.upper()} {path}", schemas))
        self.error_validator = self._validator({"$ref": "#/components/schemas/Error"})

    def _validator(self, schema):
        fc = FormatChecker()
        fc.checks("date-time")(_is_datetime)
        return Draft202012Validator({**_to_jsonschema(schema), "$defs": self.defs}, format_checker=fc)

    def match(self, method, path):
        path = path.split("?")[0]
        for m, rx, name, schemas in self.ops:
            if m == method.upper() and rx.match(path):
                return name, schemas
        return None, {}

    def check(self, method, path, r):
        __tracebackhide__ = True
        name, schemas = self.match(method, path)
        code = str(r.status_code)
        documented = code in schemas
        validator = schemas.get(code) if documented else (self.error_validator if r.status_code >= 400 else None)
        errors = []
        if validator is not None:
            try:
                body = r.json()
            except ValueError:
                body = None
                errors = [f"response is not JSON: {r.text[:120]!r}"]
            if body is not None or not errors:
                errors = errors or [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                                    for e in validator.iter_errors(body)]
        with self._lock:
            self.calls.append({"op": name or f"{method.upper()} {path} (undocumented)", "status": r.status_code,
                               "documented": documented, "validated": validator is not None,
                               "schema_ok": not errors, "test": os.getenv("PYTEST_CURRENT_TEST", "").rsplit(" ", 1)[0]})
        if errors and self.enabled:
            where = f"{name} -> {code}" + ("" if documented else " (undocumented status, checked against Error)")
            raise SchemaMismatch(f"response does not match spec for {where}: " + "; ".join(errors[:5]))

    def dump(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.calls))


def refresh_spec(dest=SPEC_PATH):
    """Download the live spec over the vendored copy: python qa_api.py --refresh-spec"""
    r = requests.get(SPEC_URL, timeout=TIMEOUT)
    r.raise_for_status()
    Path(dest).write_text(json.dumps(r.json(), indent=2))
    return dest


if os.getenv("REFRESH_SPEC") == "1":
    refresh_spec()
CONTRACT = Contract()


class Api:
    def __init__(self, key):
        self.key = Secret(key)

    def __repr__(self):
        return "<Api key=***>"

    # ---- raw calls -------------------------------------------------------
    def call(self, method, path, as_=None, json=None, raw=None, headers=None, params=None, send_key=True, key=None):
        __tracebackhide__ = True
        h = {}
        if send_key:
            h["X-Candidate-Key"] = key if key is not None else self.key
        if as_:
            h["Authorization"] = f"Bearer {TOKENS.get(as_, as_)}"
        if raw is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        # Retry transient connection errors only for calls that are safe to repeat.
        # Never retry other POSTs: the first attempt may have reached the server and changed state.
        attempts = 3 if (method == "GET" or path == "/v1/_reset") else 1
        for i in range(attempts):
            try:
                r = requests.request(method, BASE_URL + path, headers=h, json=json, data=raw,
                                     params=params, timeout=TIMEOUT)
                CONTRACT.check(method, path, r)
                return r
            except requests.RequestException as e:
                if isinstance(e, requests.ConnectionError) and i < attempts - 1:
                    time.sleep(1 + i)
                    continue
                # Re-raise WITHOUT the requests/urllib3 frames: their locals include the request headers,
                # i.e. the candidate key, which would otherwise end up in pytest output and CI artifacts.
                raise SandboxUnavailable(f"{method} {path}: {type(e).__name__} talking to the sandbox") from None

    def get(self, path, as_=None, **kw):
        return self.call("GET", path, as_, **kw)

    def post(self, path, as_=None, **kw):
        return self.call("POST", path, as_, **kw)

    def reset(self):
        r = self.call("POST", "/v1/_reset")
        assert r.status_code == 200, f"reset failed: {r.status_code} {r.text}"

    # ---- wallet ------------------------------------------------------------
    def me(self, rider):
        r = self.get("/v1/me", rider)
        assert r.status_code == 200, r.text
        return r.json()

    def balance(self, rider):
        return self.me(rider)["wallet"]["balance"]

    def ledger(self, rider):
        r = self.get("/v1/wallet/transactions", rider)
        assert r.status_code == 200, r.text
        return r.json()

    def topup(self, rider, amount=10000, provider="mtn_momo", phone=None, idem=None, body=None):
        phone = phone or (OKELLO_PHONE if rider == "okello" else self.me(rider)["phone"])
        payload = body if body is not None else {"amount": amount, "provider": provider, "phone": phone}
        return self.post("/v1/wallet/top-ups", rider, json=payload,
                         headers={"Idempotency-Key": idem or str(uuid.uuid4())})

    # ---- trips -------------------------------------------------------------
    def estimate(self, rider="nakato", pickup=ACACIA, dropoff=NTINDA, service="boda", promo=None, **extra):
        body = {"pickup": pickup, "dropoff": dropoff, "service_type": service, **extra}
        if promo:
            body["promo_code"] = promo
        return self.post("/v1/fare-estimates", rider, json=body)

    def new_estimate(self, rider="nakato", **kw):
        r = self.estimate(rider, **kw)
        assert r.status_code == 201, f"estimate failed: {r.status_code} {r.text}"
        return r.json()

    def book(self, rider, estimate_id, payment="cash", idem=None, **extra):
        headers = {"Idempotency-Key": idem or str(uuid.uuid4())}
        return self.post("/v1/trips", rider, json={"estimate_id": estimate_id, "payment_method": payment, **extra},
                         headers=headers)

    def new_trip(self, rider="nakato", payment="cash", promo=None, service="boda", pickup=ACACIA, dropoff=NTINDA, **extra):
        est = self.new_estimate(rider, pickup=pickup, dropoff=dropoff, service=service, promo=promo)
        r = self.book(rider, est["id"], payment, **extra)
        assert r.status_code == 201, f"booking failed: {r.status_code} {r.text}"
        return r.json()

    def get_trip(self, rider, trip_id):
        r = self.get(f"/v1/trips/{trip_id}", rider)
        assert r.status_code == 200, r.text
        return r.json()

    def driver_step(self, driver, trip_id, step):
        return self.post(f"/v1/driver/trips/{trip_id}/{step}", driver)

    def drive(self, trip_id, driver="ssemanda", upto="complete"):
        """accept -> arrive -> start -> complete, stopping after `upto`. Returns last trip body."""
        last = None
        for step in ("accept", "arrive", "start", "complete"):
            r = self.driver_step(driver, trip_id, step)
            assert r.status_code == 200, f"{step} failed: {r.status_code} {r.text}"
            last = r.json()
            if step == upto:
                break
        return last


if __name__ == "__main__":
    import sys
    if "--refresh-spec" in sys.argv:
        print(f"spec written to {refresh_spec()}")
