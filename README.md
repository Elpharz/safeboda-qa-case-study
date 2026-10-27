# SafeBoda QA sandbox: API test suite (Part 2)

## Status and results (measured)
Last full run: **22 Oct 2026, 02:27-02:44 EAT** (17m19s), Python 3.13 locally (CI pins 3.12), against the staging sandbox, spec v1.4.0.

| | Cases |
|---|---|
| Collected | 371 (145 test functions) |
| Passed | 325 |
| Failed: product bugs | 43 (all registered in `known_bugs.json`, written up in `BUGS.md`; 0 untriaged) |
| Blocked: environment | 2 (`test_book_cash_trip`, `test_estimate_is_single_use`: sandbox read timeouts, raised as `SandboxUnavailable`; both passed on re-run) |
| Skipped | 1 (`test_expired_estimate_cannot_be_booked`, needs `RUN_SLOW=1`) |

**22 product defects**: 6 Critical, 8 High, 4 Medium, 4 Low; 20 confirmed, 2 spec gaps (questions for the product owner).
Three come from the Boda Assist evaluation, not pytest. Race bugs were repeated 20 times; `BUGS.md` gives n/20 for each.
Two race bugs (BUG-06 double charge, BUG-08 duplicate trips) reproduce in only 6-15 of 20 runs; both reproduced in this run
(e.g. "wallet charged 2x (10400 UGX for a 5200 UGX fare)"), but a single run can miss them.
Earlier runs: 21 Oct 23:46 EAT 37 failed / 273 passed (old suite, before the fixes below); 22 Oct 01:54 and 02:08 EAT,
40 product failures each plus 1-3 network errors (race bugs did not reproduce in those two).

Reports in `reports/`: `report.html` (pytest-html), `junit.xml`, `pytest-output.txt`, `coverage.html` + `COVERAGE.md`
(coverage dashboard), `boda_assist_report.md` + transcripts.

## Coverage (from `coverage_report.py`, last run)
| Question | Answer |
|---|---|
| Operations | **17 of 17** documented operations called |
| Contract | **64 of 66** documented (operation, status) responses seen, excluding 429 (64 of 83 with it). **Every** response (1,383 of 1,383) validated against its spec schema; **19 mismatches**, all real bugs (negative fare, fractional car fares, unvalidated coordinates echoed back, 500s with a `stack` field). 11 undocumented statuses observed (400/403/500), listed in the report |
| Behaviour | every case tagged: positive 77, negative 286, boundary 56, state 68, concurrency 8 |
| Execution | 325 passed, 43 failed, 2 blocked, 1 skipped (per case in `coverage.html`) |
| Defects | 20 confirmed, 0 under investigation, 2 spec gap; 0 untriaged failures |

Not seen: the two `410 ESTIMATE_EXPIRED` paths need the slow test, and 429 is deliberately not provoked (see Skipped).

## Tool choices and why
| Choice | Why |
|---|---|
| **pytest + requests** | Real teams already know Python; parametrisation gives hundreds of boundary cases in few lines; plain functions are easy to review; fixtures give a reset per test; rich plugins (html, junit). Postman is better for exploration, worse for diffs, concurrency and code review |
| `ThreadPoolExecutor` + barrier | Fires requests at the same instant for race tests, no extra tool. k6 is the next step for real load, not needed for correctness races |
| pytest-html + JUnit XML | Human report plus machine format for CI dashboards |
| GitHub Actions | Secret store for the key, artifacts for reports |

## What is covered (371 cases)
Auth and error envelope; places; wallet top-up (validation boundaries, idempotency replay and key reuse, ledger reconciliation, isolation);
fare estimates (pricing, rounding, promos, never negative, validation, service area); booking (single-use estimate, replay, wallet vs cash,
balance boundary, scheduling window and UTC); cancellation rules and driver release; listing and pagination; ratings; driver state machine,
assignment, service mismatch, busy driver; full journeys; concurrency (double accept, double book, double complete, replay storms, lost updates);
support-chat contract; malformed input never 5xx or leaks; 401 for every operation (no token, forged token, no candidate key, generated from the spec); response schema of every call. Boda Assist quality is a separate evaluation: see `EVALUATION.md`.

## Skipped, and why
- **429 rate limit** on every operation (17 documented responses). The 600 req/min limit is per shared candidate key; provoking it
  would lock the key out for the rest of the run. Next step: a spare key in a separate nightly job.
- **Estimate expiry (410)** waits 5 minutes: written (`test_expired_estimate_cannot_be_booked`), runs nightly with `RUN_SLOW=1`.
- **Load / performance.** Shared sandbox; correctness races are covered, throughput is not. k6 is the next step.
- **Driver rating aggregate** on the driver profile: not exposed by the API.
- **LLM judge** in the Boda Assist evaluation: the harness supports it (`JUDGE_API_KEY`), but the results above are regex detectors
  plus my reading of every flagged transcript.
- Tests marked `inferred` / `spec_gap` assert intent the spec implies but does not spell out. Failures there are questions to the
  product owner, not bugs (BUG-05, BUG-19, the SAME_LOCATION threshold).

## Run it
```bash
# Python 3.12 (CI) or 3.13 (tested locally)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export CANDIDATE_KEY=<your real key from the brief>   # never commit this; without it every API test is skipped "blocked: env"
pytest                                   # ~12 minutes; do NOT use xdist (shared per-key state)
XFAIL_KNOWN_BUGS=1 pytest                # team mode: confirmed known bugs become xfail (see below)
python coverage_report.py                # -> reports/COVERAGE.md + reports/coverage.html (after a pytest run)
python tools/repro_bugs.py BUG-02        # one-request reproduction of a bug, prints request_id
python qa_api.py --refresh-spec          # replace the vendored openapi.json with the live spec
pytest -m concurrency                    # races only
RUN_SLOW=1 pytest                        # include the 5-minute expiry test
python eval/boda_assist_eval.py --runs 30
```
Reports: `reports/` (junit.xml, report.html, coverage.html, COVERAGE.md, boda_assist_report.md, transcripts). Env overrides: `BASE_URL`,
`TOKEN_*`, `SCHEMA_VALIDATION=0` (turn the schema check off), `REFRESH_SPEC=1`, `OPENAPI_SPEC`, `JUDGE_API_KEY`, `JUDGE_MODEL`.

### How the suite is built
- `qa_api.py`: thin client. **Every response is validated against the vendored `openapi.json`** (jsonschema; OpenAPI `nullable`
  handled): a documented status must match its schema, an undocumented 4xx/5xx must still match `Error`. A mismatch raises
  `SchemaMismatch` and fails the test. Every call is logged to `reports/api_calls.json` for the coverage report.
- Markers: every test (or each `pytest.param` case) carries `positive`, `negative`, `boundary` and/or `state`; conftest refuses
  to collect an untagged test. `concurrency`, `slow`, `inferred`, `spec_gap` as before.
- The key never reaches reports: it is held in a `Secret` str that prints as `'***'`, and network errors are re-raised as
  `SandboxUnavailable` without the requests/urllib3 frames (whose locals contain the request headers). I found the key in a
  traceback of an earlier run's `pytest-output.txt` before adding this; the coverage report counts these failures as **blocked**.
- `tests/test_auth_matrix.py` reads the operation list from the spec, so a new endpoint automatically gets its 401 tests.

## Known failures in a real team
Tests that find bugs **fail**; nothing is deleted or skipped, and a default `pytest` run is red while bugs exist, as the brief asks.
`known_bugs.json` is the defect registry: each failing test id maps to `id`, `severity`, `status` (`confirmed` /
`under_investigation` / `spec_gap`), `summary`, `ticket`, `review_by` and `intermittent`. One defect id has one status
(the coverage report fails on a conflict).

On a team, once a bug has a ticket, run CI with `XFAIL_KNOWN_BUGS=1`: only **confirmed** entries become **strict xfail**, so
main stays green while the bug is open and new regressions stand out; the build goes red when the test unexpectedly passes
(fixed: remove the entry) and again after `review_by` (stops "known" becoming "forgotten"). `intermittent` race bugs get a
non-strict xfail so a lucky pass does not break the build. `under_investigation` and `spec_gap` entries are never hidden.

## CI
`.github/workflows/api-tests.yml` (works if this folder is the repo root): runs pytest, then `coverage_report.py`, then the Boda
Assist eval; uploads `reports/` (including coverage.html) even on failure; fails the build on any failed test; the key comes from the
`QA_CANDIDATE_KEY` secret and never appears in code; runs serialised because state is per key. I have not yet run it on GitHub.
PR: 5 eval runs. Nightly: slow tests + 30 eval runs.

## AI use
AI assistance was used for drafting; all tests, results and findings were reviewed, run and verified by me against the sandbox.

## With more time
Contract test generated from `openapi.json` (schemathesis) for response-shape drift; property-based fare tests; per-rider rate-limit (429) test on a spare key;
Boda Assist mined scenarios from real tickets and judge calibration against human labels; trend dashboard; k6 smoke load on book-accept-complete; mutation checks on the tests.
