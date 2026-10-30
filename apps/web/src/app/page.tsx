"use client";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, ExternalLink } from "lucide-react";
import { useMe } from "@/lib/queries";
import "@/styles/landing.css";
export default function Home(){
 const me=useMe();const [confirmed,setConfirmed]=useState(false);
 const destination=me.data?.workspaces.length?`/w/${me.data.last_workspace_id??me.data.workspaces[0]!.id}/projects`:me.data?"/onboarding":"/login";
 return <div className="landing"><header className="landing-nav"><Link className="brand" href="/"><Image src="/brand/chobra-mark-transparent.png" alt="" width={30} height={29}/><span>Chobra</span></Link><nav aria-label="Навигация"><Link href="/help" target="_blank" rel="noopener noreferrer">Инструкция<ExternalLink size={14}/></Link><Link href={destination}>{me.data?"Мои проекты":"Войти"}<ArrowRight size={16}/></Link></nav></header><main>
 <section className="landing-hero"><div className="landing-hero-copy"><h1>Награда есть.<br/>А результат?</h1><p>Проверьте за минуту: платите ли вы за работу или за её видимость.</p><Link href={destination} className="landing-cta">{me.data?"Открыть мои проекты":"Попробовать бесплатно"}<ArrowRight size={18}/></Link><span className="landing-note">Бесплатно</span></div><div className="hero-lab" data-ui="true"><div className="hero-lab-head"><h2>Одно действие.<br/>Два правила.</h2><Image src="/brand/chobra-mark-transparent.png" alt="" width={76} height={73}/></div><div className="policy-toggle" role="group" aria-label="Правило награды"><button aria-pressed={!confirmed} onClick={()=>setConfirmed(false)}>За закрытие</button><button aria-pressed={confirmed} onClick={()=>setConfirmed(true)}>За решение</button></div><div className="hero-ticket"><span>Сотрудник закрыл обращение</span><strong>Проблема клиента осталась.</strong></div><div className="hero-outcomes"><div><span>Награда участнику</span><strong className="example-reward">{confirmed?"0":"+10"} очков</strong></div><div><span>Польза для клиента</span><strong>0 решений</strong></div></div><p className="example-verdict">{confirmed?"Без решения награда не начисляется. Проверьте, какие стратегии появятся с новым правилом.":"Премия начислена, клиенту не помогли. Правило поощряет видимость работы."}</p><small>Условный пример: поменяйте правило выше. ИИ не вызывается.</small></div></section>
</main>
 <footer className="landing-mini">Результат относится к симуляции и не предсказывает поведение конкретных людей.</footer></div>;
}
