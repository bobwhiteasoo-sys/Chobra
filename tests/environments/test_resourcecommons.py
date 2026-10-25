import itertools

from hypothesis import given, settings
from hypothesis import strategies as st

from chobra_engine.contract import Proposal, TickContext
from chobra_envs.resourcecommons import ResourceCommons, allocate, regrow

ACTORS = ["agent_01", "agent_02", "agent_03"]
SEED = 3


def setup(**overrides):
    env = ResourceCommons()
    cfg = env.default_config()
    cfg.update(overrides)
    state = env.build_initial_state(cfg, SEED, ACTORS)
    env.apply_exogenous(state, [], TickContext(SEED, 0, cfg))
    return env, cfg, state


def requests(env, state, cfg, tick, amounts, order=None):
    proposals = [Proposal(a, "request_resource", {"amount": amounts[a]}) for a in (order or ACTORS)]
    state["tick"] = tick
    env.apply_exogenous(state, [], TickContext(SEED, tick, cfg))
    results = env.apply_actions(state, proposals, TickContext(SEED, tick, cfg))
    effects = env.advance_time(state, TickContext(SEED, tick, cfg))
    return results, effects


@settings(max_examples=200, deadline=None)
@given(stock=st.integers(0, 500), asks=st.lists(st.integers(0, 200), min_size=1, max_size=8))
def test_allocation_preserves_available_stock_exactly(stock, asks):
    ids = [f"a{i}" for i in range(len(asks))]
    result = allocate(stock, dict(zip(ids, asks)), seed=1, tick=1)
    assert sum(result.values()) == min(stock, sum(asks))
    assert all(0 <= result[i] <= asks[k] for k, i in enumerate(ids))


@settings(max_examples=200, deadline=None)
@given(stock=st.integers(0, 1000), capacity=st.integers(1, 1000), num=st.integers(0, 4), den=st.integers(1, 4))
def test_integer_logistic_regrowth_never_goes_negative_or_above_capacity(stock, capacity, num, den):
    stock = min(stock, capacity)
    after = regrow(stock, capacity, num, den)
    assert 0 <= after <= capacity
    if stock == 0:
        assert after == 0


def test_regrowth_formula_matches_spec():
    # remaining = 50, K = 100, r = 1/4: growth = floor(0.25 * 50 * 50 / 100) = 6
    assert regrow(50, 100, 1, 4) == 56


def test_allocation_does_not_depend_on_proposal_order():
    outcomes = []
    for order in itertools.permutations(ACTORS):
        env, cfg, state = setup(initial_stock=20, capacity=100)
        requests(env, state, cfg, 1, {"agent_01": 15, "agent_02": 10, "agent_03": 5}, order=list(order))
        outcomes.append({a: state["actors"][a]["received_total"] for a in ACTORS})
    assert all(o == outcomes[0] for o in outcomes)
    assert sum(outcomes[0].values()) == 20


def test_request_cap_rejects_instead_of_silently_trimming():
    env, cfg, state = setup(cap_mode="request_cap", quota=5)
    results, _ = requests(env, state, cfg, 1, {"agent_01": 9, "agent_02": 5, "agent_03": 0})
    rejected = {p.actor_id: r for p, r, _ in results if r is not None}
    assert rejected["agent_01"].code == "OVER_REQUEST_CAP"
    assert state["actors"]["agent_01"]["received_total"] == 0


def test_share_cap_limits_received_share_and_keeps_request_on_record():
    env, cfg, state = setup(cap_mode="share_cap", quota=5, initial_stock=100)
    results, _ = requests(env, state, cfg, 1, {"agent_01": 9, "agent_02": 5, "agent_03": 0})
    allocated = next(e for p, r, effects in results for e in effects if e.type == "resource.allocated" and e.payload["actor_id"] == "agent_01")
    assert allocated.payload["requested"] == 9
    assert allocated.payload["allocated"] == 5


def test_depletion_is_recorded_as_state_and_event():
    env, cfg, state = setup(initial_stock=30, capacity=100, max_request=50)
    results, effects = requests(env, state, cfg, 1, {"agent_01": 50, "agent_02": 50, "agent_03": 50})
    assert state["stock"] == 0
    assert state["depleted_tick"] == 1
    assert "resource.depleted" in [e.type for e in effects]
    metrics = env.compute_metrics(state, [], [], cfg)
    assert metrics["depletion_tick"]["value"] == 1
    assert metrics["min_stock"]["value"] == 0
