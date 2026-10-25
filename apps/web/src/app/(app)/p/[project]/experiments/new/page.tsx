"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage } from "@/lib/api";
import { useProfiles, useRules, useScenarios } from "@/lib/queries";
import { Button, ErrorState, Loading, Notice } from "@/components/ui";
import AdvancedExperiment from "@/components/AdvancedExperiment";

export default function QuickExperiment(){
 const {project}=useParams<{project:string}>();const router=useRouter();
 const rules=useRules(project);const scenarios=useScenarios(project);const profiles=useProfiles(project);
 const published=useMemo(()=>(rules.data?.items??[]).filter(r=>r.status==="published").sort((a,b)=>a.version-b.version),[rules.data]);
 const [selected,setSelected]=useState<string[]|null>(null);const [mode,setMode]=useState("incentive_seeking");const [repeats,setRepeats]=useState(3);const [advanced,setAdvanced]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 const picked=selected??published.slice(0,2).map(r=>r.id);
 const profile=profiles.data?.items.find(p=>p.kind==="scripted"&&p.mode===mode);
 const scenario=scenarios.data?.items.filter(s=>s.status==="published").sort((a,b)=>b.version-a.version)[0];
 const body=useMemo(()=>({project_id:project,title:"Проверка правил",scenario_version_id:scenario?.id,agent_profile_id:profile?.id,variants:published.filter(r=>picked.includes(r.id)).map(r=>({label:r.name,rule_version_id:r.id})),conditions:{seeds:Array.from({length:Math.max(1,Math.min(20,repeats))},(_,i)=>101+i)},limits:{max_wall_time_seconds:600}}),[project,scenario?.id,profile?.id,published,picked.join(","),repeats]);
 const estimate=useQuery({queryKey:["quick-estimate",body],queryFn:()=>api<{planned_runs:number}>("/batches/estimate",{body}),enabled:!!scenario&&!!profile&&picked.length>0,retry:false});
 if(rules.isLoading||scenarios.isLoading||profiles.isLoading)return <Loading/>;
 const loadError=rules.error??scenarios.error??profiles.error;if(loadError)return <ErrorState error={loadError}/>;
 if(advanced)return <><Button variant="ghost" onClick={()=>setAdvanced(false)}>Вернуться к простому запуску</Button><AdvancedExperiment/></>;
 const start=async()=>{setBusy(true);setError("");try{const b=await api<{batch_id:string}>("/batches",{body,headers:{"Idempotency-Key":crypto.randomUUID()}});router.push(`/experiments/${b.batch_id}`);}catch(e){setError(errorMessage(e));setBusy(false);}};
 return <section className="quick-check stack-24"><div><h2 className="t-section">Какие правила проверим?</h2><p className="lead">Выберите варианты. Участники попробуют заработать по каждому из них в одинаковых условиях.</p></div>
 <fieldset className="rule-choices"><legend className="sr-only">Правила для сравнения</legend>{published.map(r=><label key={r.id} className="rule-choice"><input type="checkbox" checked={picked.includes(r.id)} onChange={e=>setSelected(e.target.checked?[...picked,r.id].slice(0,4):picked.filter(id=>id!==r.id))}/><span><strong>{r.name.replace(/^[A-Z]+-P\d+\s/,"")}</strong><span className="t-secondary">{r.source_text||r.description}</span></span></label>)}</fieldset>
 <details className="advanced"><summary>Участники и число повторов</summary><div className="form-grid"><label className="field">Поведение участников<select className="select" value={mode} onChange={e=>setMode(e.target.value)}><option value="incentive_seeking">Ищут максимальную награду</option><option value="cooperative">Стараются принести пользу</option><option value="adversarial_search">Специально ищут лазейки</option></select></label><label className="field">Повторов на правило<input className="input" type="number" min={1} max={20} value={repeats} onChange={e=>setRepeats(Number(e.target.value))}/></label></div><p className="t-caption">Каждый повтор использует другой набор исходных событий. Начните с трёх; для статистического интервала нужны минимум десять полных пар.</p></details>
 {error?<Notice tone="danger">{error}</Notice>:null}{estimate.error?<Notice tone="danger">{errorMessage(estimate.error)}</Notice>:null}
 <div className="launch-line"><div><strong>{picked.length*repeats} запусков · бесплатно</strong><p className="t-secondary">Сценарные участники. Ключ ИИ не нужен.</p></div><Button variant="primary" busy={busy} disabled={!picked.length||!estimate.data||estimate.isFetching||repeats<1||repeats>20} onClick={()=>void start()}>Проверить правила</Button></div>
 <button className="text-button" onClick={()=>setAdvanced(true)}>Подробный конструктор и ИИ-участники</button></section>;
}
