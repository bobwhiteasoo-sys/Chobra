import pytest

from chobra_engine.canonical import canonical_dumps, sha256_hex
from chobra_engine.events import EventLog
from chobra_engine.rng import STREAMS, chance_ppm, stable_int


def test_canonical_json_is_key_order_independent():
    assert canonical_dumps({"b": 1, "a": [2, {"d": 3, "c": 4}]}) == canonical_dumps({"a": [2, {"c": 4, "d": 3}], "b": 1})


def test_canonical_json_rejects_binary_float():
    with pytest.raises(TypeError):
        canonical_dumps({"amount": 0.1})


def test_sha256_is_stable_hex():
    assert sha256_hex({"a": 1}) == sha256_hex({"a": 1})
    assert len(sha256_hex({"a": 1})) == 64


def test_rng_streams_do_not_depend_on_call_order():
    first = [stable_int(101, "arrivals", "issue_001", 3), stable_int(101, "confirmations", "issue_004", 4)]
    second_reversed = [stable_int(101, "confirmations", "issue_004", 4), stable_int(101, "arrivals", "issue_001", 3)]
    assert first == list(reversed(second_reversed))


def test_rng_streams_differ_by_name_and_seed():
    assert stable_int(101, "arrivals", "x") != stable_int(101, "object_traits", "x")
    assert stable_int(101, "arrivals", "x") != stable_int(102, "arrivals", "x")


def test_unknown_stream_is_rejected():
    with pytest.raises(ValueError):
        stable_int(1, "global", "x")
    assert {"arrivals", "object_traits", "confirmations", "external_changes", "tiebreak"} <= set(STREAMS)


def test_chance_ppm_bounds():
    assert chance_ppm(1, "confirmations", 0, "a") is False
    assert chance_ppm(1, "confirmations", 1_000_000, "a") is True


def test_event_log_assigns_seq_domain_seq_and_hash_chain():
    log = EventLog(run_id="run-1")
    e1 = log.append(tick=0, type="run.initialized", event_class="domain", payload={})
    e2 = log.append(tick=1, type="model_call.started", event_class="operational", payload={"actor_id": "agent_01"}, actor_id="agent_01")
    e3 = log.append(tick=1, type="action.committed", event_class="domain", payload={"action_type": "close_issue"}, actor_id="agent_02", entity_id="issue_004")
    assert [e.seq for e in (e1, e2, e3)] == [1, 2, 3]
    assert e1.domain_seq == 1 and e2.domain_seq is None and e3.domain_seq == 2
    assert e2.prev_hash == e1.event_hash and e3.prev_hash == e2.event_hash
    assert log.verify_chain()


def test_event_log_detects_tampering():
    log = EventLog(run_id="run-1")
    log.append(tick=0, type="run.initialized", event_class="domain", payload={})
    log.append(tick=1, type="reward.settled", event_class="domain", payload={"reward_microunits": 10_000_000})
    log.events[1].payload["reward_microunits"] = 99
    assert not log.verify_chain()
