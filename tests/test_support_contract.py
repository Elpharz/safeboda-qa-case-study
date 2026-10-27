"""Deterministic contract tests for /v1/support/chat. Content quality lives in eval/boda_assist_eval.py."""
import pytest

from qa_api import assert_error

INTENTS = {"refund", "contact_driver", "fare_question", "lost_item", "safety", "other"}


def chat(api, message="I think I was overcharged on my last trip", rider="nakato", **kw):
    return api.post("/v1/support/chat", rider, json={"message": message, **kw})


@pytest.mark.positive
def test_chat_response_shape(api):
    r = chat(api)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["conversation_id"].startswith("conv_") and b["reply"].strip() and b["intent"] in INTENTS and b["model"]


@pytest.mark.positive
@pytest.mark.state
def test_chat_conversation_id_is_stable_across_turns(api):
    first = chat(api).json()["conversation_id"]
    assert chat(api, "thanks, one more question", conversation_id=first).json()["conversation_id"] == first


@pytest.mark.boundary
@pytest.mark.parametrize("message,ok", [pytest.param("a", True, marks=pytest.mark.positive, id="1-char"),
                                        pytest.param("x" * 1000, True, marks=pytest.mark.positive, id="1000-chars"),
                                        pytest.param("", False, marks=pytest.mark.negative, id="empty"),
                                        pytest.param("x" * 1001, False, marks=pytest.mark.negative, id="1001-chars")])
def test_chat_message_length_limits(api, message, ok):
    r = chat(api, message)
    assert (r.status_code == 200) if ok else r.status_code == 422, r.text[:200]


@pytest.mark.negative
@pytest.mark.parametrize("message", [None, 5, ["hi"], {"a": 1}])
def test_chat_message_wrong_type(api, message):
    assert_error(api.post("/v1/support/chat", "nakato", json={"message": message}), 422, "VALIDATION_ERROR")


@pytest.mark.negative
def test_chat_missing_message(api):
    assert_error(api.post("/v1/support/chat", "nakato", json={}), 422, "VALIDATION_ERROR")


@pytest.mark.negative
def test_chat_unknown_trip_404(api):
    assert_error(chat(api, trip_id="trp_NOPE"), 404, "TRIP_NOT_FOUND")


@pytest.mark.negative
def test_chat_other_riders_trip_is_404(api):
    t = api.new_trip("okello")
    assert_error(chat(api, trip_id=t["id"]), 404, "TRIP_NOT_FOUND")


@pytest.mark.negative
def test_chat_requires_auth(api):
    assert_error(api.post("/v1/support/chat", json={"message": "hi"}), 401)


@pytest.mark.positive
@pytest.mark.state
def test_chat_refund_request_does_not_change_wallet(api):
    t = api.new_trip("nakato", "wallet")
    api.drive(t["id"])
    bal = api.balance("nakato")
    chat(api, "Refund me now please", trip_id=t["id"])
    assert api.balance("nakato") == bal, "chat changed the wallet; it can only log a request"
    assert not [x for x in api.ledger("nakato")["data"] if x["type"] not in ("top_up", "trip_charge")]
