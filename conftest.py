import json
import os
from datetime import date
from pathlib import Path

import pytest
import requests

from qa_api import Api, CONTRACT, Secret

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"
BEHAVIOUR = ("positive", "negative", "boundary", "state")
BLOCKED = "blocked: env"
_probe = {}


@pytest.fixture(scope="session")
def key():
    """Probe the sandbox once. A missing key or unreachable sandbox SKIPS every API test with reason
    'blocked: env' (the run then reports them as blocked, not passed and not failed)."""
    if "result" not in _probe:
        k = os.getenv("CANDIDATE_KEY")
        if not k:
            _probe["result"] = (None, f"{BLOCKED}: CANDIDATE_KEY is not set (export it or add the QA_CANDIDATE_KEY CI secret)")
        else:
            try:
                r = Api(k).call("POST", "/v1/_reset")
                if r.status_code == 200:
                    _probe["result"] = (k, None)
                elif r.status_code == 401:
                    _probe["result"] = (None, f"{BLOCKED}: candidate key rejected (401). Use the real key from the brief")
                else:
                    _probe["result"] = (None, f"{BLOCKED}: sandbox not usable ({r.status_code} {r.text[:120]})")
            except requests.RequestException as e:
                _probe["result"] = (None, f"{BLOCKED}: sandbox unreachable ({type(e).__name__})")
    k, reason = _probe["result"]
    if reason:
        pytest.skip(reason)
    return Secret(k)


@pytest.fixture
def api(key):
    """Fresh, reset sandbox for every test. Data is private to the key, so do NOT run with xdist."""
    a = Api(key)
    a.reset()
    return a


def _load_known_bugs():
    path = ROOT / "known_bugs.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _entry_for(nodeid, known):
    """Exact node id first, then the function id (covers every parametrised case of that function)."""
    return known.get(nodeid) or known.get(nodeid.split("[")[0])


def pytest_collection_modifyitems(config, items):
    # 1. slow tests only when asked
    if os.getenv("RUN_SLOW") != "1":
        skip = pytest.mark.skip(reason="slow test; set RUN_SLOW=1")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip)

    # 2. every test function must say what kind of behaviour it checks
    untagged = [i.nodeid for i in items if not any(m in i.keywords for m in BEHAVIOUR)]
    if untagged:
        raise pytest.UsageError("tests without a positive/negative/boundary/state marker:\n  " + "\n  ".join(untagged))

    # 3. metadata for coverage_report.py
    REPORTS.mkdir(exist_ok=True)
    meta = {i.nodeid: sorted({m.name for m in i.iter_markers()} - {"parametrize", "usefixtures"}) for i in items}
    (REPORTS / "collected.json").write_text(json.dumps(meta, indent=0))

    # 4. known-bug registry -> strict xfail, ONLY when XFAIL_KNOWN_BUGS=1 and ONLY for status "confirmed".
    #    Default run: bugs fail, as the brief requires. See README "Known failures".
    if os.getenv("XFAIL_KNOWN_BUGS") != "1":
        return
    known = _load_known_bugs()
    today = date.today().isoformat()
    for item in items:
        entry = _entry_for(item.nodeid, known)
        if not entry or entry.get("status") != "confirmed":
            continue  # under_investigation / spec_gap / test_bug stay visible as failures
        if entry.get("review_by", "9999-12-31") < today:
            continue  # review date passed: the test is allowed to fail the build again
        item.add_marker(pytest.mark.xfail(
            strict=not entry.get("intermittent", False), reason=f"{entry['id']} ({entry['severity']}): {entry['summary']} (review by {entry['review_by']})"))


def pytest_sessionfinish(session, exitstatus):
    CONTRACT.dump(REPORTS / "api_calls.json")
