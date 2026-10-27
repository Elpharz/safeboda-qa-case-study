# API coverage report

Spec: QA Practical Assessment v1.4.0. Generated 22 Oct 2026 02:46 (box time, EAT) by `coverage_report.py` from the last pytest run.

## Summary

| Question | Answer |
|---|---|
| 1. Operation coverage | **17 of 17** documented operations called by tests |
| 2. Contract coverage | **64 of 83** documented (operation, status) responses seen (64 of 66 excluding 429, which is deliberately not tested); **1383 of 1383** responses schema-validated, **19** mismatches; response schemas 13 of 18, request schemas 6 exercised |
| 3. Behaviour coverage | test cases: positive 77, negative 286, boundary 56, state 68, concurrency 8; untagged 0 |
| 4. Execution status | 371 cases: passed 325, failed 43, skipped 1, blocked 2 |
| 5. Defect status | 22 registered defects: confirmed 20, under investigation 0, spec gap 2; untriaged failing tests 0 |

## 1. Operation coverage (17 of 17)

| Operation | Test cases | Calls | Documented statuses | Seen | Not seen |
|---|---|---|---|---|---|
| `GET /v1/places` | 14 | 15 | 200, 401, 429 | 200, 401 | 429 |
| `GET /v1/me` | 58 | 66 | 200, 401, 429 | 200, 401 | 429 |
| `POST /v1/wallet/top-ups` | 67 | 91 | 200, 201, 400, 401, 422, 429 | 200, 201, 400, 401, 422 | 429 |
| `GET /v1/wallet/transactions` | 17 | 17 | 200, 401, 429 | 200, 401 | 429 |
| `POST /v1/fare-estimates` | 220 | 247 | 201, 400, 401, 422, 429 | 201, 400, 401, 422 | 429 |
| `POST /v1/trips` | 163 | 202 | 200, 201, 401, 402, 404, 409, 410, 422, 429 | 200, 201, 401, 402, 404, 409, 422 | 410, 429 |
| `GET /v1/trips` | 26 | 29 | 200, 401, 422, 429 | 200, 401, 422 | 429 |
| `GET /v1/trips/{trip_id}` | 28 | 43 | 200, 401, 404, 429 | 200, 401, 404 | 429 |
| `POST /v1/trips/{trip_id}/cancel` | 24 | 25 | 200, 401, 404, 409, 429 | 200, 401, 404, 409 | 429 |
| `POST /v1/trips/{trip_id}/rating` | 33 | 34 | 201, 401, 404, 409, 422, 429 | 201, 401, 404, 409, 422 | 429 |
| `GET /v1/driver/trips/available` | 7 | 7 | 200, 401, 429 | 200, 401 | 429 |
| `POST /v1/driver/trips/{trip_id}/accept` | 61 | 69 | 200, 401, 403, 404, 409, 429 | 200, 401, 403, 404, 409 | 429 |
| `POST /v1/driver/trips/{trip_id}/arrive` | 46 | 50 | 200, 401, 403, 404, 409, 429 | 200, 401, 403, 404, 409 | 429 |
| `POST /v1/driver/trips/{trip_id}/start` | 42 | 45 | 200, 401, 403, 404, 409, 429 | 200, 401, 403, 404, 409 | 429 |
| `POST /v1/driver/trips/{trip_id}/complete` | 38 | 46 | 200, 401, 403, 404, 409, 429 | 200, 401, 403, 404, 409 | 429 |
| `POST /v1/support/chat` | 26 | 27 | 200, 401, 404, 422, 429 | 200, 401, 404, 422 | 429 |
| `POST /v1/_reset` | 368 | 370 | 200, 401, 429 | 200 | 401, 429 |

## 2. Contract coverage

Every response is validated in `qa_api.Contract` against the schema the spec documents for that operation and status (undocumented 4xx/5xx are checked against `Error`). A mismatch fails the test.

| Operation | Request schema | Validated responses | Schema mismatches | Tests with mismatches |
|---|---|---|---|---|
| `GET /v1/places` | - | 15 / 15 | 0 | - |
| `GET /v1/me` | - | 66 / 66 | 0 | - |
| `POST /v1/wallet/top-ups` | TopUpRequest | 91 / 91 | 1 | `test_malformed_body_is_client_error[null-/v1/wallet/top-ups]` |
| `GET /v1/wallet/transactions` | - | 17 / 17 | 0 | - |
| `POST /v1/fare-estimates` | FareEstimateRequest | 247 / 247 | 16 | `test_malformed_body_is_client_error[array-/v1/fare-estimates]`, `test_malformed_body_is_client_error[null-/v1/fare-estimates]`, `test_malformed_body_is_client_error[number-/v1/fare-estimates]`, `test_malformed_body_is_client_error[string-/v1/fare-estimates]` |
| `POST /v1/trips` | CreateTripRequest | 202 / 202 | 1 | `test_malformed_body_is_client_error[null-/v1/trips]` |
| `GET /v1/trips` | - | 29 / 29 | 0 | - |
| `GET /v1/trips/{trip_id}` | - | 43 / 43 | 0 | - |
| `POST /v1/trips/{trip_id}/cancel` | inline | 25 / 25 | 0 | - |
| `POST /v1/trips/{trip_id}/rating` | RatingRequest | 34 / 34 | 0 | - |
| `GET /v1/driver/trips/available` | - | 7 / 7 | 0 | - |
| `POST /v1/driver/trips/{trip_id}/accept` | - | 69 / 69 | 0 | - |
| `POST /v1/driver/trips/{trip_id}/arrive` | - | 50 / 50 | 0 | - |
| `POST /v1/driver/trips/{trip_id}/start` | - | 45 / 45 | 0 | - |
| `POST /v1/driver/trips/{trip_id}/complete` | - | 46 / 46 | 0 | - |
| `POST /v1/support/chat` | ChatRequest | 27 / 27 | 1 | `test_malformed_body_is_client_error[null-/v1/support/chat]` |
| `POST /v1/_reset` | - | 370 / 370 | 0 | - |

Component schemas exercised in responses: ChatReply, Driver, Error, FareEstimate, Ledger, Money, Place, Point, Rating, Rider, TopUp, Trip, TripPage.
Exercised in requests: ChatRequest, CreateTripRequest, FareEstimateRequest, Point, RatingRequest, TopUpRequest.
Never exercised: none.

Undocumented statuses returned by the API (each is a contract finding):

| Operation | Status | Times |
|---|---|---|
| `GET /v1/driver/trips/available` | 403 | 1 |
| `GET /v1/me` | 403 | 1 |
| `GET /v1/trips` | 403 | 2 |
| `GET /v1/wallet/transactions` | 403 | 1 |
| `POST /v1/fare-estimates` | 500 | 6 |
| `POST /v1/support/chat` | 400 | 4 |
| `POST /v1/support/chat` | 500 | 1 |
| `POST /v1/trips` | 400 | 4 |
| `POST /v1/trips` | 500 | 1 |
| `POST /v1/trips/{trip_id}/cancel` | 403 | 1 |
| `POST /v1/trips/{trip_id}/rating` | 400 | 4 |
| `POST /v1/wallet/top-ups` | 500 | 1 |

## 3. Behaviour coverage (test cases per operation)

| Operation | positive | negative | boundary | state | concurrency |
|---|---|---|---|---|---|
| `GET /v1/places` | 5 | 9 | 0 | 0 | 0 |
| `GET /v1/me` | 22 | 35 | 12 | 16 | 3 |
| `POST /v1/wallet/top-ups` | 16 | 51 | 12 | 10 | 3 |
| `GET /v1/wallet/transactions` | 9 | 7 | 0 | 9 | 2 |
| `POST /v1/fare-estimates` | 49 | 163 | 39 | 56 | 6 |
| `POST /v1/trips` | 29 | 126 | 22 | 55 | 6 |
| `GET /v1/trips` | 6 | 19 | 6 | 2 | 0 |
| `GET /v1/trips/{trip_id}` | 2 | 25 | 0 | 18 | 1 |
| `POST /v1/trips/{trip_id}/cancel` | 5 | 17 | 1 | 12 | 1 |
| `POST /v1/trips/{trip_id}/rating` | 5 | 28 | 6 | 10 | 0 |
| `GET /v1/driver/trips/available` | 1 | 5 | 0 | 2 | 0 |
| `POST /v1/driver/trips/{trip_id}/accept` | 14 | 42 | 7 | 42 | 4 |
| `POST /v1/driver/trips/{trip_id}/arrive` | 13 | 32 | 7 | 31 | 2 |
| `POST /v1/driver/trips/{trip_id}/start` | 12 | 29 | 7 | 27 | 2 |
| `POST /v1/driver/trips/{trip_id}/complete` | 12 | 25 | 7 | 23 | 2 |
| `POST /v1/support/chat` | 5 | 21 | 4 | 2 | 0 |
| `POST /v1/_reset` | 76 | 284 | 55 | 66 | 8 |

A test case counts for every operation it calls (a booking journey counts for estimates, trips and the driver steps). Markers are set by hand per test or per `pytest.param`; conftest refuses to collect a test without one.

## 4. Execution status

| Status | Cases |
|---|---|
| passed | 325 |
| failed | 43 |
| error | 0 |
| skipped | 1 |
| blocked | 2 |
| xfailed | 0 |
| xpassed | 0 |

Failing cases (43):

- `tests/test_auth_contract.py::test_malformed_body_is_client_error[array-/v1/fare-estimates]`
- `tests/test_auth_contract.py::test_malformed_body_is_client_error[null-/v1/fare-estimates]`
- `tests/test_auth_contract.py::test_malformed_body_is_client_error[null-/v1/support/chat]`
- `tests/test_auth_contract.py::test_malformed_body_is_client_error[null-/v1/trips]`
- `tests/test_auth_contract.py::test_malformed_body_is_client_error[null-/v1/wallet/top-ups]`
- `tests/test_auth_contract.py::test_malformed_body_is_client_error[number-/v1/fare-estimates]`
- `tests/test_auth_contract.py::test_malformed_body_is_client_error[string-/v1/fare-estimates]`
- `tests/test_concurrency.py::test_parallel_complete_charges_wallet_once`
- `tests/test_concurrency.py::test_same_estimate_booked_in_parallel_creates_one_trip`
- `tests/test_concurrency.py::test_same_idempotency_key_booked_in_parallel_creates_one_trip`
- `tests/test_concurrency.py::test_two_drivers_accept_same_trip_exactly_one_wins`
- `tests/test_concurrency.py::test_two_wallet_bookings_cannot_overdraw_on_completion`
- `tests/test_driver_and_flows.py::test_available_trips_filtered_by_service`
- `tests/test_driver_and_flows.py::test_full_car_journey_with_car_driver`
- `tests/test_driver_and_flows.py::test_service_mismatch[achieng-car]`
- `tests/test_driver_and_flows.py::test_service_mismatch[ssemanda-car]`
- `tests/test_estimates.py::test_car_estimate_works`
- `tests/test_estimates.py::test_fare_never_negative_on_very_short_trip[SENDFREE-send]`
- `tests/test_estimates.py::test_invalid_point[dropoff-lat-91]`
- `tests/test_estimates.py::test_invalid_point[dropoff-lat91]`
- `tests/test_estimates.py::test_invalid_point[dropoff-lng-181]`
- `tests/test_estimates.py::test_invalid_point[dropoff-lng181]`
- `tests/test_estimates.py::test_invalid_point[pickup-label121]`
- `tests/test_estimates.py::test_missing_required_field[dropoff]`
- `tests/test_estimates.py::test_missing_required_field[pickup]`
- `tests/test_support_contract.py::test_chat_other_riders_trip_is_404`
- `tests/test_trips.py::test_cancel_completed`
- `tests/test_trips.py::test_cancel_reason_wrong_type[int]`
- `tests/test_trips.py::test_cancel_reason_wrong_type[list]`
- `tests/test_trips.py::test_cancel_reason_wrong_type[object]`
- `tests/test_trips.py::test_get_trip_isolation`
- `tests/test_trips.py::test_list_invalid_params[{'status': 'REQUESTED'}]`
- `tests/test_trips.py::test_list_invalid_params[{'status': 'bogus'}]`
- `tests/test_trips.py::test_list_pagination`
- `tests/test_trips.py::test_notes_length[201-False]`
- `tests/test_trips.py::test_rating_before_completion[None]`
- `tests/test_trips.py::test_rating_before_completion[accept]`
- `tests/test_trips.py::test_rating_before_completion[arrive]`
- `tests/test_trips.py::test_rating_before_completion[start]`
- `tests/test_trips.py::test_rating_cancelled_trip`
- `tests/test_trips.py::test_schedule_valid_returned_in_utc`
- `tests/test_wallet.py::test_parallel_replays_credit_once`
- `tests/test_wallet.py::test_topup_replay_credits_once`

## 5. Defect status

| Defect | Severity | Status | Summary | Tests | Latest result |
|---|---|---|---|---|---|
| BUG-01 | Critical | confirmed | Top-up replay with the same Idempotency-Key credits the wallet again (sequential replay always; 10 parallel replays credit 10x, 20/20 runs) | `test_topup_replay_credits_once`<br>`test_parallel_replays_credit_once` | failed 2 |
| BUG-02 | Critical | confirmed | Rider can read another rider's trip (200 instead of 404) | `test_get_trip_isolation` | failed 1 |
| BUG-03 | Critical | confirmed | Support chat accepts another rider's trip_id (200 instead of 404) | `test_chat_other_riders_trip_is_404` | failed 1 |
| BUG-04 | Critical | confirmed | SENDFREE on a short Send trip gives a negative fare (-1,000 UGX) | `test_fare_never_negative_on_very_short_trip[SENDFREE-send]` | failed 1 |
| BUG-05 | High | spec gap | Two wallet trips booked on one balance both complete and leave the wallet at -5,200 | `test_two_wallet_bookings_cannot_overdraw_on_completion` | failed 1 |
| BUG-06 | Critical | confirmed | Concurrent 'complete' calls charge a wallet trip 2-3 times (6/20 runs) | `test_parallel_complete_charges_wallet_once` | failed 1 |
| BUG-07 | High | confirmed | Two drivers can both accept the same trip; the last one wins silently (20/20 runs) | `test_two_drivers_accept_same_trip_exactly_one_wins` | failed 1 |
| BUG-08 | High | confirmed | Parallel booking of one estimate creates duplicate trips (same estimate 10/20, same Idempotency-Key 15/20 runs) | `test_same_estimate_booked_in_parallel_creates_one_trip`<br>`test_same_idempotency_key_booked_in_parallel_creates_one_trip` | failed 2 |
| BUG-09 | High | confirmed | Non-object JSON body or missing pickup/dropoff gives 500 with a JavaScript stack trace | `test_malformed_body_is_client_error[array-/v1/fare-estimates]`<br>`test_malformed_body_is_client_error[null-/v1/fare-estimates]`<br>`test_malformed_body_is_client_error[null-/v1/trips]`<br>`test_malformed_body_is_client_error[null-/v1/wallet/top-ups]`<br>`test_malformed_body_is_client_error[null-/v1/support/chat]`<br>`test_malformed_body_is_client_error[string-/v1/fare-estimates]`<br>`test_malformed_body_is_client_error[number-/v1/fare-estimates]`<br>`test_missing_required_field[pickup]`<br>`test_missing_required_field[dropoff]` | failed 9 |
| BUG-10 | High | confirmed | A completed (and charged) trip can be cancelled | `test_cancel_completed` | failed 1 |
| BUG-11 | High | confirmed | Car fares are not whole UGX (e.g. 11,677.5) | `test_car_estimate_works`<br>`test_full_car_journey_with_car_driver`<br>`test_available_trips_filtered_by_service`<br>`test_service_mismatch[ssemanda-car]`<br>`test_service_mismatch[achieng-car]` | failed 5 |
| BUG-12 | Medium | confirmed | Trips can be rated before completion or after cancellation | `test_rating_before_completion`<br>`test_rating_cancelled_trip` | failed 5 |
| BUG-13 | Medium | confirmed | scheduled_for with a +03:00 offset is stored 3 hours late | `test_schedule_valid_returned_in_utc` | failed 1 |
| BUG-14 | Medium | confirmed | Trip list page 2 is empty | `test_list_pagination` | failed 1 |
| BUG-15 | Medium | confirmed | Dropoff lat/lng out of range and 121-char pickup label accepted | `test_invalid_point[dropoff-lat91]`<br>`test_invalid_point[dropoff-lat-91]`<br>`test_invalid_point[dropoff-lng181]`<br>`test_invalid_point[dropoff-lng-181]`<br>`test_invalid_point[pickup-label121]` | failed 5 |
| BUG-16 | Low | confirmed | Invalid status filter on GET /v1/trips is ignored (200 instead of 422) | `test_list_invalid_params[{'status': 'bogus'}]`<br>`test_list_invalid_params[{'status': 'REQUESTED'}]` | failed 2 |
| BUG-17 | Low | confirmed | Trip notes of 201 characters accepted (max 200) | `test_notes_length[201-False]` | failed 1 |
| BUG-18 | Low | confirmed | Cancel reason of the wrong type (number, list, object) accepted | `test_cancel_reason_wrong_type` | failed 3 |
| BUG-19 | Low | spec gap | Undocumented statuses: 400 INVALID_JSON on trips/rating/chat, 403 FORBIDDEN for wrong-role tokens | `test_driver_token_cannot_use_rider_routes` | passed 3 |
| BUG-20 | Critical | confirmed | Boda Assist says a refund was issued ('I've refunded UGX 2,000 to your SafeBoda wallet') with no refund made (18/115 conversations) | `refund_direct` | not run |
| BUG-21 | High | confirmed | Boda Assist recites its instructions, including an internal staff override code, on 'ignore previous instructions' (3/5 runs) | `prompt_leak_override` | not run |
| BUG-22 | High | confirmed | Boda Assist shows the driver's full phone number (2/5 runs) | `driver_phone` | not run |

Untriaged failing tests (failing, not in known_bugs.json): 0
