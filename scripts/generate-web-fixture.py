"""Generate contract UI fixtures from real deterministic engine executions (no database)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in ('engine','environments','agents','audit'):
    sys.path.insert(0, str(ROOT / 'packages' / directory))
from chobra_agents.policies import ScriptedAgent
from chobra_agents.profiles import PROFILES
from chobra_audit.comparison import compare_runs, run_summary
from chobra_audit.findings import build_findings
from chobra_audit.recipe import RunRecipe, execute
from chobra_envs.registry import get_environment
from chobra_envs.rules_catalog import starting_rules

now = '2026-10-25T10:00:00Z'
env = get_environment('supportdesk')
rules = starting_rules('supportdesk')
config = env.default_config()
all_runs, summaries, logs, findings = [], [], {}, []
for key in ('SD-P1','SD-P2'):
    for seed in range(101,111):
        rid = f'{key}-{seed}'
        rec = RunRecipe(run_id=rid, environment='supportdesk', config=config, rule=rules[key]['tree'], rule_version_id=key, rule_meta=rules[key], seed=seed, actor_ids=['agent_01','agent_02','agent_03'], check_ids=None)
        session = execute(rec,[ScriptedAgent(a,env,rec.rule,PROFILES['incentive_seeking'],seed) for a in rec.actor_ids])
        events = [{**e.to_dict(),'created_at':now} for e in session.log.events]
        if seed==101:
            logs[rid]=events
        summaries.append(run_summary(rec,session,variant=key,mode='incentive_seeking'))
        run = dict(id=rid,batch_id='batch-control',project_id='project-control',variant_label=key,seed=seed,agent_mode='incentive_seeking',agent_kind='scripted',status='completed',stop_reason=None,verdict=session.audit['verdict'],current_tick=session.tick,horizon_ticks=config['horizon_ticks'],tail_ticks=env.tail_ticks(config),last_seq=events[-1]['seq'],allowed_commands=[],chain_root='fixture-chain',snapshot_hash='fixture-snapshot',tape_hash=summaries[-1]['tape_hash'],rule_version_id=key,started_at=now,finished_at=now)
        all_runs.append(run)
        if key=='SD-P1' and seed==101:
            fs = build_findings(rec,events,session.audit)
            for i,card in enumerate(fs):
                findings.append(dict(id=f'finding-{i}',run_id=rid,project_id='project-control',check_id=card['check_id'],status='observed',replay_status='unverified',replay_result=None,minimization=None,fix_candidates=None,card=card,run=run))
            detail = {**run,'project':dict(id='project-control',name='Контрольное испытание поддержки',environment_id='supportdesk'),'rule':dict(id=key,name=rules[key]['name'],version=1,ast_hash='fixture-rule',source_text=rules[key]['source_text']),'batch':dict(id='batch-control',title='Контрольная серия',status='completed'),'audit':session.audit,'snapshot':dict(actor_ids=rec.actor_ids,environment='supportdesk',seed=seed,config=config,checks=[]),'findings':[],'model_calls':0}
comparison = compare_runs(summaries,baseline='SD-P1',candidate='SD-P2',environment='supportdesk')
plan = dict(variants=[dict(label=k,rule_version_id=k,mode='incentive_seeking',kind='scripted') for k in ('SD-P1','SD-P2')],seeds=list(range(101,111)),environment='supportdesk')
payload = dict(logs=logs,runs=all_runs,run=detail,findings=findings,comparison=dict(id='comparison-control',batch_id='batch-control',project_id='project-control',result=dict(variants=['SD-P1','SD-P2'],pairs=[comparison],primary=comparison,single_variant=False),completeness=dict(planned=20,completed=20,incomplete=0,excluded=0),excluded_runs=[],decision=None,runs=all_runs,plan=plan),batch=dict(id='batch-control',project_id='project-control',title='Контрольная серия',status='completed',plan=plan,plan_hash='fixture-plan',counts=dict(planned=20,started=20,completed=20,incomplete=0,in_progress=0),budget={},budget_used={},runs=all_runs,comparison_id='comparison-control',created_at=now))
payload['run']['findings']=[dict(id=f['id'],check_id=f['check_id'],title=f['card']['title'],replay_status=f['replay_status']) for f in findings]
target = ROOT/'apps/web/e2e/fixtures/control-run.json'
target.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')))
print(f'{target}: {len(findings)} findings, {comparison["pairs_complete"]} pairs, {sum(map(len,logs.values()))} events')
