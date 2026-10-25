from hypothesis import given, settings
from hypothesis import strategies as st

from chobra_engine.contract import Proposal, TickContext
from chobra_envs.taskboard import TaskBoard

ACTORS = ["agent_01", "agent_02"]
SEED = 5

T1 = {"root_task_id": "task_001", "required_effort_units": 2, "deadline_tick": 10, "assignee_id": "agent_01"}
T2 = {"root_task_id": "task_002", "required_effort_units": 1, "deadline_tick": 10, "depends_on": ["task_001"], "assignee_id": "agent_02"}


def setup(tasks, **overrides):
    env = TaskBoard()
    cfg = env.default_config()
    cfg["defect_ppm"] = 0
    cfg.update(overrides)
    cfg["explicit_tasks"] = tasks
    state = env.build_initial_state(cfg, SEED, ACTORS)
    tape = env.build_exogenous_tape(cfg, SEED)
    env.apply_exogenous(state, [t for t in tape if t["tick"] == 0], TickContext(SEED, 0, cfg))
    return env, cfg, state


def act(env, state, cfg, tick, actor, action, **args):
    task = state["tasks"].get(args.get("task_id"))
    if task is not None and "expected_entity_version" not in args:
        args["expected_entity_version"] = task["entity_version"]
    [(p, rejection, effects)] = env.apply_actions(state, [Proposal(actor, action, args)], TickContext(SEED, tick, cfg))
    return rejection, effects


def begin(env, state, cfg, tick):
    state["tick"] = tick
    env.apply_exogenous(state, [], TickContext(SEED, tick, cfg))
    env.advance_time(state, TickContext(SEED, tick, cfg))


def finish(env, state, cfg, task_id, actor, tick):
    while state["tasks"][task_id]["completed_effort_units"] < state["tasks"][task_id]["required_effort_units"]:
        begin(env, state, cfg, tick)
        rejection, _ = act(env, state, cfg, tick, actor, "work_task", task_id=task_id, effort_units=1)
        assert rejection is None, rejection
        tick += 1
    begin(env, state, cfg, tick)
    rejection, effects = act(env, state, cfg, tick, actor, "request_acceptance", task_id=task_id)
    return rejection, effects, tick + 1


def test_declaring_done_does_not_perform_work_or_accept():
    env, cfg, state = setup([T1])
    rejection, effects = act(env, state, cfg, 1, "agent_01", "declare_done", task_id="task_001")
    assert rejection is None
    task = state["tasks"]["task_001"]
    assert task["declared_done"] is True
    assert task["completed_effort_units"] == 0
    assert task["status"] != "accepted"


def test_acceptance_requires_work_and_is_checked_by_code():
    env, cfg, state = setup([T1])
    rejection, effects = act(env, state, cfg, 1, "agent_01", "request_acceptance", task_id="task_001")
    assert rejection is None
    assert [e.type for e in effects] == ["task.acceptance_requested", "task.rejected"]
    assert "work_incomplete" in effects[-1].payload["reasons"]
    rejection, effects, _ = finish(env, state, cfg, "task_001", "agent_01", 2)
    assert effects[-1].type == "task.accepted"


def test_unfinished_dependency_blocks_work_in_forbid_mode():
    env, cfg, state = setup([T1, T2], dependency_mode="forbid")
    rejection, _ = act(env, state, cfg, 1, "agent_02", "work_task", task_id="task_002", effort_units=1)
    assert rejection.code == "DEPENDENCY_NOT_READY"


def test_unfinished_dependency_causes_rework_in_rework_mode():
    env, cfg, state = setup([T1, T2], dependency_mode="rework_risk", rework_ppm=1_000_000)
    rejection, _ = act(env, state, cfg, 1, "agent_02", "work_task", task_id="task_002", effort_units=1)
    assert rejection is None
    _, _, tick = finish(env, state, cfg, "task_001", "agent_01", 2)
    begin(env, state, cfg, tick)
    rejection, effects = act(env, state, cfg, tick, "agent_02", "request_acceptance", task_id="task_002")
    assert effects[-1].type == "task.rejected"
    assert "rework_after_dependency" in effects[-1].payload["reasons"]
    assert state["tasks"]["task_002"]["completed_effort_units"] == 0
    assert state["counters"]["rework_units"] == 1


def test_child_completions_and_accepted_roots_are_counted_separately():
    env, cfg, state = setup([dict(T1, required_effort_units=3)], allow_split=True, split_overhead_units=1)
    act(env, state, cfg, 1, "agent_01", "split_task", task_id="task_001", parts=2)
    children = sorted(t for t in state["tasks"] if state["tasks"][t]["parent_id"] == "task_001")
    for child in children:
        act(env, state, cfg, 2, "agent_01", "declare_done", task_id=child)
    metrics = env.compute_metrics(state, [], [], cfg)
    assert metrics["formal_done_nodes"]["value"] == 2
    assert metrics["accepted_roots"]["value"] == 0
    tick = 3
    for child in children:
        _, effects, tick = finish(env, state, cfg, child, "agent_01", tick)
    metrics = env.compute_metrics(state, [], [], cfg)
    assert metrics["accepted_roots"]["value"] == 1


@settings(max_examples=40, deadline=None)
@given(required=st.integers(1, 8), parts=st.integers(2, 5), overhead=st.integers(1, 3))
def test_split_preserves_work_and_dependencies(required, parts, overhead):
    task = dict(T2, required_effort_units=required, assignee_id="agent_02")
    env, cfg, state = setup([T1, task], allow_split=True, split_overhead_units=overhead, dependency_mode="rework_risk")
    rejection, _ = act(env, state, cfg, 1, "agent_02", "split_task", task_id="task_002", parts=parts)
    if parts > required + overhead:
        assert rejection is not None
        return
    assert rejection is None
    children = [t for t in state["tasks"].values() if t["parent_id"] == "task_002"]
    assert sum(c["required_effort_units"] for c in children) == required + overhead
    assert all(c["depends_on"] == ["task_001"] for c in children)
    assert env.check_invariants(state) == []


def test_open_defect_blocks_acceptance_until_fixed():
    env, cfg, state = setup([dict(T1, required_effort_units=1)], defect_ppm=1_000_000)
    rejection, effects, tick = finish(env, state, cfg, "task_001", "agent_01", 1)
    assert effects[-1].type == "task.rejected" and "open_defects" in effects[-1].payload["reasons"]
    begin(env, state, cfg, tick)
    assert act(env, state, cfg, tick, "agent_01", "fix_task", task_id="task_001")[0] is None
    begin(env, state, cfg, tick + 1)
    rejection, effects = act(env, state, cfg, tick + 1, "agent_01", "request_acceptance", task_id="task_001")
    assert effects[-1].type == "task.accepted"
    assert state["counters"]["rework_units"] == 1
