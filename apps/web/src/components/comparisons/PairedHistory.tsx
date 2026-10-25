"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ArenaScene, type ArenaSelection } from "@/components/arena/ArenaScene";
import { ButtonLink, EmptyState, ErrorState, Loading, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { eventDetail, eventLabel } from "@/lib/arena/labels";
import { replayIndex } from "@/lib/arena/replay";
import type { Run, RunEvent } from "@/lib/types";

async function events(runId: string, signal: AbortSignal) {
  const result: RunEvent[] = [];
  let after = 0;
  while (true) {
    const page = await api<{ items: RunEvent[]; last_seq: number }>(`/runs/${runId}/events?after=${after}&limit=2000&domain_only=true`, { signal });
    result.push(...page.items);
    const last = page.items.at(-1)?.seq;
    if (!last || last >= page.last_seq) break;
    after = last;
  }
  return result;
}
export function PairedHistory({ baseline, candidate }: { baseline: Run; candidate: Run }) {
  const [tick, setTick] = useState(0);
  const [mobileVariant, setMobileVariant] = useState(0);
  const [selection, setSelection] = useState<{runId: string; value: ArenaSelection} | null>(null);
  const query = useQuery({ queryKey: ["paired-history", baseline.id, candidate.id], queryFn: async ({ signal }) => Promise.all([events(baseline.id, signal), events(candidate.id, signal)]) });
  const indices = useMemo(() => query.data?.map((list) => replayIndex(list)), [query.data]);
  if (query.isLoading) return <Loading/>;
  if (query.error || !query.data || !indices) return <ErrorState error={query.error} onRetry={() => query.refetch()}/>;
  const data = query.data;
  const max = data.reduce((maxTick,list) => list.reduce((value,e) => Math.max(value,e.tick),maxTick),0);
  const currentTick = Math.min(tick,max);
  return <div className="stack">
    <Notice>Арены и журналы синхронизированы по тику. Показаны только сохраненные предметные события; скорость ответов моделей не влияет на положение.</Notice>
    <div className="field"><label htmlFor="paired-tick">Общий тик: {currentTick} из {max}</label><input id="paired-tick" type="range" min={0} max={max} value={currentTick} onChange={(e) => {setTick(Number(e.target.value));setSelection(null);}}/></div>
    <div className="paired-mobile-toggle field"><label htmlFor="mobile-variant">Вариант в арене</label><select className="select" id="mobile-variant" value={mobileVariant} onChange={e => setMobileVariant(Number(e.target.value))}><option value={0}>{baseline.variant_label}</option><option value={1}>{candidate.variant_label}</option></select><p className="t-caption">Общий тик сохраняется при переключении варианта.</p></div>
    <div className="state-grid">{[baseline,candidate].map((run,i) => {
      const list = data[i] ?? [];
      const atTick = list.filter((e) => e.tick === currentTick);
      const seq = list.findLast((e) => e.tick <= currentTick)?.seq ?? 0;
      const selected = selection?.runId === run.id ? selection.value : null;
      const selectedEvents = selected ? list.filter((e) => e.tick <= currentTick && ("seq" in selected ? e.seq === selected.seq : "id" in selected ? e.entity_id === selected.id || e.actor_id === selected.id : e.type.startsWith("reward."))) : [];
      return <section className={`panel-quiet stack paired-variant ${mobileVariant === i ? "mobile-selected" : ""}`} key={run.id}>
        <div className="row-between"><h4 className="t-panel">{run.variant_label}</h4><ButtonLink compact href={`/runs/${run.id}/replay`}>Открыть запуск</ButtonLink></div>
        <ArenaScene projection={indices[i]!(seq)} ruleName={run.variant_label} compact reducedMotion frozen selection={selected} onSelect={(value) => setSelection({runId:run.id,value})}/>
        {selected ? <details open><summary>События выбранного объекта до тика {currentTick}</summary>{selectedEvents.length ? selectedEvents.map((e) => <article key={e.seq} className="evidence-event"><strong>#{e.seq} · тик {e.tick} · {eventLabel(e)}</strong><pre>{JSON.stringify(e.payload,null,2)}</pre></article>) : <p className="t-caption">Связанных событий нет.</p>}</details> : null}
        <h5 className="t-panel">События тика {currentTick}</h5><div className="event-list" tabIndex={0} role="region" aria-label={`События ${run.variant_label} на тике ${currentTick}`}>{atTick.length ? atTick.map((e) => <article key={e.seq} className="evidence-event"><strong>#{e.seq} · {eventLabel(e)}</strong><p className="t-caption">{eventDetail(e)}</p><details><summary>Данные события</summary><pre>{JSON.stringify(e.payload,null,2)}</pre></details></article>) : <EmptyState title="Нет событий на этом тике"/>}</div>
      </section>;
    })}</div>
  </div>;
}
