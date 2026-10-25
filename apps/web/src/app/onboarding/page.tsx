"use client";
import { Suspense, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/queries";
import { Button, Loading, Notice } from "@/components/ui";

function Setup(){
 const me=useMe();const router=useRouter();const cache=useQueryClient();
 const [name,setName]=useState("Мои проекты");const [env,setEnv]=useState("supportdesk");const [workspace,setWorkspace]=useState("");const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 const options=[{id:"supportdesk",title:"Поддержка клиентов",body:"Платим за закрытые обращения. Решат ли участники проблемы клиентов?"},{id:"taskboard",title:"Работа команды",body:"Платим за выполненные задачи. Будет ли результат полезным?"},{id:"resourcecommons",title:"Общий ресурс",body:"Награждаем за использование. Не закончится ли общий запас?"}];
 const submit=async(e:FormEvent)=>{e.preventDefault();setBusy(true);setError("");try{let id=workspace;if(!id){const w=await api<{id:string}>("/workspaces",{body:{name}});id=w.id;setWorkspace(id);}const p=await api<{id:string}>("/projects",{body:{workspace_id:id,name:options.find(o=>o.id===env)!.title,environment_id:env,is_demo:true}});await cache.invalidateQueries({queryKey:["me"]});router.push(`/p/${p.id}/experiments/new`);}catch(err){setError(errorMessage(err));setBusy(false);}};
 if(me.isLoading)return <Loading/>;
 return <main className="entry"><section className="entry-content"><Link href="/" className="brand">Chobra</Link><h1>Начните с примера.</h1><p className="lead">Выберите ситуацию. Мы подготовим участников, задачи и три правила — останется нажать «Проверить».</p><form onSubmit={submit} className="stack-24"><label className="field" style={{marginTop:24}}>Название пространства<input className="input" value={name} required maxLength={120} onChange={e=>setName(e.target.value)}/></label><fieldset className="rule-choices"><legend className="sr-only">Ситуация</legend>{options.map(o=><label className="rule-choice" key={o.id}><input type="radio" name="environment" checked={env===o.id} onChange={()=>setEnv(o.id)}/><span><strong>{o.title}</strong><span className="t-secondary">{o.body}</span></span></label>)}</fieldset>{error?<Notice tone="danger">{error}</Notice>:null}<Button type="submit" variant="primary" busy={busy}>Создать пример</Button><p className="t-caption">Пример работает без ключа ИИ и не тратит деньги.</p></form></section></main>;
}
export default function Onboarding(){return <Suspense><Setup/></Suspense>;}
