"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import QRCode from "qrcode";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Notice } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { Me } from "@/lib/types";

type Challenge = { id: string; url: string; code: string; expires_at: string };

function LoginForm() {
  const config = useQuery({queryKey:["auth-config"],queryFn:()=>api<{mode:string;telegram_enabled:boolean;telegram_username:string;oidc_configured:boolean}>("/auth/config"),retry:1});
  const router=useRouter(); const params=useSearchParams(); const cache=useQueryClient();
  const [challenge,setChallenge]=useState<Challenge|null>(null); const [qr,setQr]=useState("");
  const [error,setError]=useState<string|null>(null); const [expired,setExpired]=useState(false); const [busy,setBusy]=useState(false);
  const [name,setName]=useState("");const [email,setEmail]=useState(""); const started=useRef(false);
  const finish=(me:Me)=>{cache.setQueryData(["me"],me);const next=params.get("next");router.replace(next?.startsWith("/")&&!next.startsWith("//")?next:me.workspaces.length?`/w/${me.last_workspace_id??me.workspaces[0]!.id}/projects`:"/onboarding");};
  const refresh=async()=>{setBusy(true);setError(null);setExpired(false);setChallenge(null);setQr("");try{const c=await api<Challenge>("/auth/telegram/challenge",{body:{}});setQr(await QRCode.toDataURL(c.url,{width:240,margin:2,errorCorrectionLevel:"M",color:{dark:"#070511",light:"#ffffff"}}));setChallenge(c);}catch(e){setError(errorMessage(e));}finally{setBusy(false);}};
  useEffect(()=>{if(config.data?.telegram_enabled&&!started.current){started.current=true;void refresh();}},[config.data?.telegram_enabled]); // One challenge per mount, including Strict Mode.
  useEffect(()=>{
    if(!challenge)return;
    let stopped=false; let timer:ReturnType<typeof setTimeout>; let failures=0;
    const poll=async()=>{
      if(Date.now()>Date.parse(challenge.expires_at)){setExpired(true);return;}
      try{
        const s=await api<{status:string}>(`/auth/telegram/challenge/${challenge.id}`);failures=0;
        if(stopped)return;
        if(s.status==="approved"){setBusy(true);const me=await api<Me>(`/auth/telegram/challenge/${challenge.id}/consume`,{body:{}});if(!stopped)finish(me);return;}
        if(s.status==="expired"||s.status==="consumed"){setExpired(true);return;}
      }catch(e){if(stopped)return;if(e instanceof ApiError&&[404,410].includes(e.status)){setExpired(true);return;}if(++failures>=3)setError("Нет связи с сервером. Проверяем подключение…");}
      if(!stopped)timer=setTimeout(poll,1500);
    };
    timer=setTimeout(poll,1500);return()=>{stopped=true;clearTimeout(timer);};
  },[challenge]);
  const devLogin=async(e:FormEvent)=>{e.preventDefault();setBusy(true);setError(null);try{finish(await api<Me>("/auth/dev-login",{body:{display_name:name,email}}));}catch(err){setError(errorMessage(err));setBusy(false);}};
  return <main className="entry"><section className="entry-content">
    <Link href="/" className="brand"><Image src="/brand/chobra-mark-transparent.png" alt="" width={40} height={38}/><span>Chobra</span></Link>
    <h1>Войдите через Telegram</h1>
    <p className="lead">Наведите камеру телефона на код или нажмите кнопку.</p>
    {config.isLoading?<p role="status">Подключаемся к серверу…</p>:null}
    {config.error?<Notice tone="danger">Сервер недоступен. <button className="text-button" onClick={()=>void config.refetch()}>Повторить</button></Notice>:null}
    {config.data?.telegram_enabled?<div className="telegram-entry">
      <div className="qr-box">{qr&&!expired?<img src={qr} width={224} height={224} alt="QR-код для входа через Telegram"/>:<span>{expired?"Код истёк":"Готовим QR-код…"}</span>}</div>
      <div className="stack">{challenge&&!expired?<><p className="t-secondary">Сверьте код: <strong className="login-code">{challenge.code}</strong></p><a className="btn btn-primary" href={challenge.url} target="_blank" rel="noopener noreferrer">Открыть Telegram</a><p className="t-caption" role="status">После подтверждения сайт откроется сам.</p></>:null}{expired?<Button onClick={()=>void refresh()} busy={busy}>Получить новый код</Button>:null}</div>
    </div>:null}
    {error?<Notice tone="danger">{error}</Notice>:null}
    {config.data?.mode==="dev"?<details className="advanced"><summary>Локальный вход для разработки</summary><form className="stack" onSubmit={devLogin}><label className="field">Имя<input className="input" required value={name} onChange={e=>setName(e.target.value)}/></label><label className="field">Почта<input className="input" required type="email" value={email} onChange={e=>setEmail(e.target.value)}/></label><Button type="submit" busy={busy}>Войти в тестовый аккаунт</Button></form></details>:null}
    {config.data?.oidc_configured?<a className="btn" href="/api/v1/auth/oidc/start">Войти через организацию</a>:null}
    {config.data&&!config.data.telegram_enabled&&!config.data.oidc_configured&&config.data.mode!=="dev"?<Notice tone="danger">Вход ещё не настроен администратором.</Notice>:null}
    
  </section></main>;
}
export default function LoginPage(){return <Suspense><LoginForm/></Suspense>;}
