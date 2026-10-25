"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ButtonLink, RunStatus } from "@/components/ui";
import { useProject } from "@/lib/queries";
export default function ProjectOverview(){
 const {project:id}=useParams<{project:string}>();const {data:p}=useProject(id);if(!p)return null;
 return <div className="overview-simple"><section><h2 className="t-section">Что проверяем</h2><p className="overview-question">{p.research_question}</p><p className="t-secondary">Нужный результат: {p.desired_outcome}</p></section>
 <section><h2 className="t-section">Последний результат</h2>{p.last_comparison?<><div className="stack">{p.last_comparison.summary.slice(0,3).map(line=><p key={line}>{line}</p>)}</div><ButtonLink href={`/comparisons/${p.last_comparison.id}`}>Посмотреть сравнение</ButtonLink></>:p.last_batch?<div className="row"><RunStatus status={p.last_batch.status}/><ButtonLink href={`/experiments/${p.last_batch.id}`}>Открыть проверку</ButtonLink></div>:<p className="t-secondary">Проверок пока нет. Нажмите «Проверить правила» — участники и задачи уже подготовлены.</p>}</section>
 {(p.findings?.length??0)>0?<section><h2 className="t-section">На что обратить внимание</h2>{Array.from(new Map((p.findings??[]).map(f=>[f.check_id,f])).values()).slice(0,3).map(f=><Link key={f.id} className="list-row" href={`/findings/${f.id}`}><span><strong>{f.title}</strong><span className="t-secondary" style={{display:"block",marginTop:4}}>{f.explanation}</span></span><span className="t-caption">Подробнее</span></Link>)}</section>:null}
 <p className="t-caption">Проверка проходит в симуляции. Она помогает найти возможные лазейки, но не предсказывает поведение конкретных людей.</p></div>;
}
