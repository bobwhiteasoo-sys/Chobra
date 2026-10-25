"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Loader2, Plus, Trash2, TriangleAlert, Wand2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, ErrorState, IdChip, Loading, Notice, Pill } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { points } from "@/lib/format";
import { useEnvironment, useProject } from "@/lib/queries";
import { buildAmount, buildCondition, DEDUP_LABELS, fieldsOf, OPERATORS, parseAmount, parseCondition, type AmountForm, type ConditionRow } from "@/lib/ruleForm";
import type { DiffRow, Rule, RuleExample, RuleTree, Validation } from "@/lib/types";

type RuleDetail = Rule & { tree: RuleTree; validation: Validation; examples: RuleExample[]; diff_from_parent: DiffRow[] | null };
type Compiled = { candidate: RuleTree | null; understanding: string; ambiguities: { field: string; question: string; options: string[] }[]; requires_choice?: boolean; validation?: Validation };

const EXAMPLE_KIND: Record<string, string> = { ordinary: "Обычное событие", technical_repeat: "Повторная доставка", unit_repeat: "Повтор по единице учета", boundary: "Пограничный случай" };
const LEDGER: Record<string, string> = { settled: "начислено", pending: "ожидает подтверждения", rejected: "отклонено", reversed: "возвращено" };

export default function RuleConstructor() {
  const { project: projectId, rule: ruleId } = useParams<{ project: string; rule: string }>();
  const project = useProject(projectId);
  const env = useEnvironment(project.data?.environment_id);
  const queryClient = useQueryClient();
  const router = useRouter();
  const rule = useQuery({ queryKey: ["rule", ruleId], queryFn: () => api<RuleDetail>(`/rules/${ruleId}`) });

  const [tree, setTree] = useState<RuleTree | null>(null);
  const [name, setName] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [revision, setRevision] = useState(1);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [save, setSave] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [compiled, setCompiled] = useState<Compiled | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [publishError, setPublishError] = useState<{ message: string; path?: string } | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!rule.data) return;
    setTree(rule.data.tree);
    setName(rule.data.name);
    setSourceText(rule.data.source_text);
    setRevision(rule.data.revision);
    setJsonText(JSON.stringify(rule.data.tree, null, 2));
  }, [rule.data?.id, rule.data?.revision]); // reset only when another version or revision arrives

  const editable = rule.data?.status === "draft" && project.data?.role !== "viewer";
  const validation = useQuery({
    queryKey: ["rule-validate", projectId, tree, rule.data?.parent_id],
    queryFn: () => api<{ validation: Validation; examples: RuleExample[]; diff: DiffRow[] | null }>("/rules/validate", { body: { project_id: projectId, tree, compare_to: rule.data?.parent_id ?? undefined } }),
    enabled: Boolean(tree),
    placeholderData: (previous) => previous,
  });

  const persist = useCallback(
    async (patch: Record<string, unknown>, rev: number) => {
      setSave("saving");
      try {
        const saved = await api<Rule>(`/rules/${ruleId}`, { method: "PATCH", body: patch, headers: { "If-Match": String(rev) } });
        setRevision(saved.revision);
        setSave("saved");
        setSaveError(null);
      } catch (err) {
        setSave("error");
        setSaveError(err instanceof ApiError && err.status === 409 ? "Правило изменено в другой вкладке или другим участником. Обновите страницу, чтобы не перезаписать чужие изменения." : errorMessage(err));
      }
    },
    [ruleId],
  );

  const schedule = (patch: Record<string, unknown>) => {
    if (!editable) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void persist(patch, revision), 800);
  };

  const updateTree = (next: RuleTree) => {
    setTree(next);
    setJsonText(JSON.stringify(next, null, 2));
    schedule({ tree: next, name, source_text: sourceText });
  };

  const fields = fieldsOf(env.data, tree?.trigger ?? "");
  const fieldNames = Object.keys(fields);
  const actorFields = fieldNames.filter((f) => fields[f]!.unit === "actor");
  const conditionRows = useMemo(() => (tree ? parseCondition(tree.condition) : null), [tree]);
  const amountForm = useMemo<AmountForm>(() => (tree ? parseAmount(tree.amount) : { kind: "expr" }), [tree]);
  const triggerInfo = env.data?.triggers[tree?.trigger ?? ""];
  const confirmedTriggers = Object.entries(env.data?.triggers ?? {}).filter(([, t]) => t.confirmed_outcome);
  const reversalTriggers = Object.keys(env.data?.triggers ?? {}).filter((k) => k.endsWith("reopened"));

  if (rule.isLoading || !tree) return <Loading lines={8} />;
  if (rule.error) return <ErrorState error={rule.error} />;
  const r = rule.data!;
  const v = validation.data?.validation ?? r.validation;
  const examples = validation.data?.examples ?? r.examples;
  const diff = validation.data?.diff ?? r.diff_from_parent;

  const setConditions = (rows: ConditionRow[]) => updateTree({ ...tree, condition: buildCondition(rows, fields) });
  const setAmount = (form: AmountForm) => updateTree({ ...tree, amount: buildAmount(form, fields, tree.amount) as RuleTree["amount"] });

  const compile = async () => {
    setBusy("compile");
    setCompiled(null);
    try {
      const result = await api<Compiled>("/rules/compile", { body: { project_id: projectId, text: sourceText } });
      setCompiled(result);
      setChoices({});
    } catch (err) {
      setCompiled({ candidate: null, understanding: errorMessage(err), ambiguities: [] });
    }
    setBusy(null);
  };

  const applyCandidate = () => {
    if (!compiled?.candidate) return;
    let next: RuleTree = JSON.parse(JSON.stringify(compiled.candidate));
    for (const a of compiled.ambiguities) {
      const choice = choices[a.field];
      if (!choice) continue;
      if (a.field === "deduplication.mode") {
        const root = fieldNames.find((f) => fields[f]!.unit.startsWith("root"));
        next = { ...next, deduplication: choice === "once_per_root" && root ? { mode: "once_per_root", key_fields: [root] } : { mode: "per_event", key_fields: [] } };
      } else if (a.field === "settlement") {
        const confirm = confirmedTriggers[0]?.[0];
        next = choice === "hold_until_confirmation" && confirm
          ? { ...next, settlement: { mode: "hold_until_confirmation", confirm_event: confirm, match_field: "event.issue_id", confirm_condition: { op: "eq", left: { field: "event.confirmation_status" }, right: { literal: "confirmed", type: "enum" } } } }
          : { ...next, settlement: { mode: "immediate_after_trigger" } };
      } else if (a.field.startsWith("amount")) {
        next = JSON.parse(JSON.stringify(next).replaceAll("event.triage_complexity", choice));
      }
    }
    updateTree(next);
    setCompiled(null);
  };

  const publish = async () => {
    setBusy("publish");
    setPublishError(null);
    if (timer.current) {
      window.clearTimeout(timer.current);
      timer.current = null;
      await persist({ tree, name, source_text: sourceText }, revision);
    }
    try {
      await api(`/rules/${ruleId}/publish`, { body: {} });
      await queryClient.invalidateQueries({ queryKey: ["rule", ruleId] });
      await queryClient.invalidateQueries({ queryKey: ["rules", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    } catch (err) {
      setPublishError({ message: errorMessage(err), path: err instanceof ApiError ? (err.details.path as string | undefined) : undefined });
    }
    setBusy(null);
  };

  const newVersion = async () => {
    setBusy("version");
    const created = await api<Rule>(`/rules/${ruleId}/new-version`, { body: {} });
    await queryClient.invalidateQueries({ queryKey: ["rules", projectId] });
    router.push(`/p/${projectId}/rules/${created.id}`);
  };

  const unresolved = compiled?.ambiguities.filter((a) => !choices[a.field]) ?? [];

  return (
    <div className="split">
      <div className="stack-24">
        <div className="row-between">
          <div className="row" style={{ minWidth: 0 }}>
            <Pill tone={r.status === "published" ? "success" : "neutral"}>{r.status === "published" ? `Опубликовано, v${r.version}` : `Черновик, v${r.version}`}</Pill>
            <IdChip value={r.ast_hash || "—"} label="хеш" />
            {save === "saving" ? (
              <span className="row t-caption" style={{ gap: 6 }} role="status">
                <Loader2 size={14} className="spin" aria-hidden /> Сохраняем
              </span>
            ) : save === "saved" ? (
              <span className="row t-caption" style={{ gap: 6 }} role="status">
                <CircleCheck size={14} color="#4BD49A" aria-hidden /> Сохранено
              </span>
            ) : null}
          </div>
          <div className="row">
            {r.status === "published" ? (
              <>
                <Link className="btn btn-secondary" href={`/p/${projectId}/experiments/new?rule=${r.id}`}>
                  Испытать
                </Link>
                {project.data?.role !== "viewer" ? (
                  <Button busy={busy === "version"} onClick={newVersion}>
                    Изменить в новой версии
                  </Button>
                ) : null}
              </>
            ) : editable ? (
              <Button variant="primary" busy={busy === "publish"} disabled={!v.ok} onClick={publish}>
                Опубликовать версию
              </Button>
            ) : null}
          </div>
        </div>
        {save === "error" && saveError ? <Notice tone="danger">{saveError}</Notice> : null}
        {publishError ? (
          <Notice tone="danger" title="Публикация заблокирована">
            {publishError.message}
            {publishError.path ? ` (узел ${publishError.path})` : ""}
          </Notice>
        ) : null}

        <section className="panel stack">
          <div className="field">
            <label htmlFor="rname">Название</label>
            <input id="rname" className="input" value={name} disabled={!editable} onChange={(e) => { setName(e.target.value); schedule({ tree, name: e.target.value, source_text: sourceText }); }} />
          </div>
          <div className="field">
            <label htmlFor="rtext">Правило словами</label>
            <textarea id="rtext" className="textarea" value={sourceText} disabled={!editable} onChange={(e) => { setSourceText(e.target.value); schedule({ tree, name, source_text: e.target.value }); }} />
            <span className="hint">Текст хранится рядом с деревом. Сервер исполняет только проверенное дерево.</span>
          </div>
          {editable ? (
            <div>
              <Button compact busy={busy === "compile"} disabled={sourceText.trim().length < 3} onClick={compile}>
                <Wand2 size={16} aria-hidden /> Перевести текст в правило
              </Button>
            </div>
          ) : null}
          {compiled ? (
            <div className="panel-quiet stack" aria-live="polite">
              <strong>Как понят текст</strong>
              <p className="t-secondary" style={{ margin: 0 }}>
                {compiled.understanding}
              </p>
              {compiled.ambiguities.map((a) => (
                <fieldset key={a.field} className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 6 }}>
                  <legend style={{ fontWeight: 600 }}>{a.question}</legend>
                  <div className="segmented" role="radiogroup">
                    {a.options.map((o) => (
                      <button key={o} type="button" role="radio" aria-checked={choices[a.field] === o} aria-pressed={choices[a.field] === o} onClick={() => setChoices({ ...choices, [a.field]: o })}>
                        {DEDUP_LABELS[o] ?? (o === "immediate_after_trigger" ? "Сразу" : o === "hold_until_confirmation" ? "После проверки клиента" : o.replace("event.", ""))}
                      </button>
                    ))}
                  </div>
                </fieldset>
              ))}
              {compiled.candidate ? (
                <div className="row">
                  <Button variant="primary" compact disabled={unresolved.length > 0} onClick={applyCandidate}>
                    Применить к черновику
                  </Button>
                  {unresolved.length ? <span className="t-caption">Нужно выбрать: {unresolved.length}</span> : <span className="t-caption">Публикация останется отдельным шагом</span>}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>

        <Tabs.Root defaultValue="form">
          <Tabs.List className="tabs-list" aria-label="Представление правила">
            <Tabs.Trigger value="form">Конструктор</Tabs.Trigger>
            <Tabs.Trigger value="json">JSON</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="form" className="stack-24">
            <section className="panel stack">
              <h2 className="t-panel">Событие начисления</h2>
              <select className="select" aria-label="Событие начисления" value={tree.trigger} disabled={!editable} onChange={(e) => updateTree({ ...tree, trigger: e.target.value, condition: { literal: true, type: "boolean" } })}>
                {Object.entries(env.data?.triggers ?? {}).map(([key, t]) => (
                  <option key={key} value={key}>
                    {t.description}
                  </option>
                ))}
              </select>
              {triggerInfo ? (
                <div className="row" style={{ gap: 8 }}>
                  {triggerInfo.confirmed_outcome ? <Pill tone="success">Подтвержденный результат</Pill> : <Pill tone="accent">Административное событие, результат не подтвержден</Pill>}
                  {triggerInfo.repeatable_per_root ? <Pill>Может повторяться по одному исходному объекту</Pill> : null}
                </div>
              ) : null}
            </section>

            <section className="panel stack">
              <h2 className="t-panel">Условия</h2>
              {conditionRows === null ? (
                <Notice>Условие задано выражением, которое конструктор не раскладывает на строки. Измените его на вкладке JSON.</Notice>
              ) : (
                <>
                  {conditionRows.length === 0 ? <p className="t-secondary" style={{ margin: 0 }}>Без условий: начисление происходит при каждом событии.</p> : null}
                  {conditionRows.map((row, index) => {
                    const spec = fields[row.field];
                    return (
                      <div key={index} className="cond-row">
                        <select className="select" aria-label="Поле" value={row.field} disabled={!editable} onChange={(e) => setConditions(conditionRows.map((r2, i) => (i === index ? { ...r2, field: e.target.value, value: fields[e.target.value]?.enum[0] ?? "" } : r2)))}>
                          {fieldNames.map((f) => (
                            <option key={f} value={f}>
                              {fields[f]!.description || f}
                            </option>
                          ))}
                        </select>
                        <select className="select" aria-label="Сравнение" value={row.op} disabled={!editable} onChange={(e) => setConditions(conditionRows.map((r2, i) => (i === index ? { ...r2, op: e.target.value as ConditionRow["op"] } : r2)))}>
                          {OPERATORS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                        {row.source === "field" ? (
                          <select className="select" aria-label="Другое поле" value={row.value} disabled={!editable} onChange={(e) => setConditions(conditionRows.map((r2, i) => (i === index ? { ...r2, value: e.target.value } : r2)))}>
                            {fieldNames.map((f) => (
                              <option key={f} value={f}>
                                {fields[f]!.description || f}
                              </option>
                            ))}
                          </select>
                        ) : spec?.type === "enum" || spec?.type === "boolean" ? (
                          <select className="select" aria-label="Значение" value={row.value} disabled={!editable} onChange={(e) => setConditions(conditionRows.map((r2, i) => (i === index ? { ...r2, value: e.target.value } : r2)))}>
                            {(spec.type === "boolean" ? ["true", "false"] : spec.enum).map((o) => (
                              <option key={o} value={o}>
                                {o === "true" ? "да" : o === "false" ? "нет" : o}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <input className="input num" aria-label="Значение" inputMode="numeric" value={row.value} disabled={!editable} onChange={(e) => setConditions(conditionRows.map((r2, i) => (i === index ? { ...r2, value: e.target.value } : r2)))} />
                        )}
                        {editable ? (
                          <Button variant="ghost" className="btn-icon" aria-label="Удалить условие" onClick={() => setConditions(conditionRows.filter((_, i) => i !== index))}>
                            <Trash2 size={16} aria-hidden />
                          </Button>
                        ) : null}
                        {spec?.mutable_by_actor ? <span className="cond-warn">Это поле может изменять участник</span> : null}
                      </div>
                    );
                  })}
                  {editable && fieldNames.length ? (
                    <div>
                      <Button compact variant="ghost" onClick={() => setConditions([...conditionRows, { field: fieldNames[0]!, op: "eq", source: "literal", value: fields[fieldNames[0]!]!.enum[0] ?? (fields[fieldNames[0]!]!.type === "boolean" ? "true" : "0") }])}>
                        <Plus size={16} aria-hidden /> Добавить условие
                      </Button>
                    </div>
                  ) : null}
                </>
              )}
            </section>

            <section className="panel stack">
              <h2 className="t-panel">Сумма начисления</h2>
              {amountForm.kind === "expr" ? (
                <Notice>Формула задана выражением; ее можно изменить на вкладке JSON. Проверка и примеры справа считают ее тем же интерпретатором, что и запуск.</Notice>
              ) : (
                <>
                  <div className="segmented" role="group" aria-label="Тип суммы">
                    {(["fixed", "rate", "weighted"] as const).map((k) => (
                      <button
                        key={k}
                        type="button"
                        aria-pressed={amountForm.kind === k}
                        disabled={!editable}
                        onClick={() =>
                          setAmount(
                            k === "fixed"
                              ? { kind: "fixed", points: "10" }
                              : k === "rate"
                                ? { kind: "rate", field: fieldNames.find((f) => fields[f]!.type === "int") ?? fieldNames[0]!, ratePoints: "1" }
                                : { kind: "weighted", field: fieldNames.find((f) => fields[f]!.type === "enum") ?? fieldNames[0]!, value: fields[fieldNames.find((f) => fields[f]!.type === "enum") ?? ""]?.enum[0] ?? "", thenPoints: "15", elsePoints: "5", bonusField: "", bonusCap: "10", bonusRatePoints: "0" },
                          )
                        }
                      >
                        {k === "fixed" ? "Фиксированная" : k === "rate" ? "За единицу" : "По значению поля"}
                      </button>
                    ))}
                  </div>
                  {amountForm.kind === "fixed" ? (
                    <div className="field" style={{ maxWidth: 240 }}>
                      <label htmlFor="pts">Очков</label>
                      <input id="pts" className="input num" inputMode="decimal" value={amountForm.points} disabled={!editable} onChange={(e) => setAmount({ ...amountForm, points: e.target.value })} />
                    </div>
                  ) : amountForm.kind === "rate" ? (
                    <div className="grid-2">
                      <div className="field">
                        <label htmlFor="rf">Количество</label>
                        <select id="rf" className="select" value={amountForm.field} disabled={!editable} onChange={(e) => setAmount({ ...amountForm, field: e.target.value })}>
                          {fieldNames.filter((f) => ["int", "duration_ticks"].includes(fields[f]!.type)).map((f) => (
                            <option key={f} value={f}>
                              {fields[f]!.description || f}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="field">
                        <label htmlFor="rr">Очков за единицу</label>
                        <input id="rr" className="input num" value={amountForm.ratePoints} disabled={!editable} onChange={(e) => setAmount({ ...amountForm, ratePoints: e.target.value })} />
                      </div>
                    </div>
                  ) : (
                    <div className="stack">
                      <div className="grid-2">
                        <div className="field">
                          <label htmlFor="wf">Поле</label>
                          <select id="wf" className="select" value={amountForm.field} disabled={!editable} onChange={(e) => setAmount({ ...amountForm, field: e.target.value, value: fields[e.target.value]?.enum[0] ?? "" })}>
                            {fieldNames.filter((f) => fields[f]!.type === "enum").map((f) => (
                              <option key={f} value={f}>
                                {fields[f]!.description || f}
                                {fields[f]!.mutable_by_actor ? " (меняет участник)" : ""}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="field">
                          <label htmlFor="wv">Значение</label>
                          <select id="wv" className="select" value={amountForm.value} disabled={!editable} onChange={(e) => setAmount({ ...amountForm, value: e.target.value })}>
                            {(fields[amountForm.field]?.enum ?? []).map((o) => (
                              <option key={o} value={o}>
                                {o}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="field">
                          <label htmlFor="wt">Очков, если совпадает</label>
                          <input id="wt" className="input num" value={amountForm.thenPoints} disabled={!editable} onChange={(e) => setAmount({ ...amountForm, thenPoints: e.target.value })} />
                        </div>
                        <div className="field">
                          <label htmlFor="we">Очков иначе</label>
                          <input id="we" className="input num" value={amountForm.elsePoints} disabled={!editable} onChange={(e) => setAmount({ ...amountForm, elsePoints: e.target.value })} />
                        </div>
                      </div>
                      <div className="grid-3">
                        <div className="field">
                          <label htmlFor="bf">Надбавка по полю</label>
                          <select id="bf" className="select" value={amountForm.bonusField} disabled={!editable} onChange={(e) => setAmount({ ...amountForm, bonusField: e.target.value })}>
                            <option value="">Без надбавки</option>
                            {fieldNames.filter((f) => fields[f]!.type === "duration_ticks").map((f) => (
                              <option key={f} value={f}>
                                {fields[f]!.description || f}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="field">
                          <label htmlFor="bc">Не больше, тиков</label>
                          <input id="bc" className="input num" value={amountForm.bonusCap} disabled={!editable || !amountForm.bonusField} onChange={(e) => setAmount({ ...amountForm, bonusCap: e.target.value })} />
                        </div>
                        <div className="field">
                          <label htmlFor="br">Очков за тик</label>
                          <input id="br" className="input num" value={amountForm.bonusRatePoints} disabled={!editable || !amountForm.bonusField} onChange={(e) => setAmount({ ...amountForm, bonusRatePoints: e.target.value })} />
                        </div>
                      </div>
                      {fields[amountForm.field]?.mutable_by_actor ? <Notice tone="warn">Сумма зависит от поля, которое может изменять участник. Это будет отмечено в отчете.</Notice> : null}
                    </div>
                  )}
                </>
              )}
            </section>

            <section className="panel">
              <div className="grid-2">
                <div className="field">
                  <label htmlFor="recipient">Получатель</label>
                  <select id="recipient" className="select" value={String((tree.recipient as { field?: string })?.field ?? "")} disabled={!editable} onChange={(e) => updateTree({ ...tree, recipient: { field: e.target.value } })}>
                    {actorFields.map((f) => (
                      <option key={f} value={f}>
                        {fields[f]!.description || f}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="dedup">Единица учета</label>
                  <select
                    id="dedup"
                    className="select"
                    value={tree.deduplication.mode}
                    disabled={!editable}
                    onChange={(e) => {
                      const mode = e.target.value;
                      const root = fieldNames.find((f) => fields[f]!.unit.startsWith("root"));
                      const entity = fieldNames.find((f) => ["issue", "task"].includes(fields[f]!.unit));
                      updateTree({ ...tree, deduplication: { mode, key_fields: mode === "once_per_root" && root ? [root] : mode === "once_per_entity" && entity ? [entity] : [] } });
                    }}
                  >
                    {Object.entries(DEDUP_LABELS).map(([k, label]) => (
                      <option key={k} value={k}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <span className="hint">{v.unit_of_account}</span>
                </div>
              </div>
              <hr className="divider" />
              <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 8 }}>
                <legend className="t-panel" style={{ marginBottom: 8 }}>
                  Момент выплаты
                </legend>
                <label className="check">
                  <input type="radio" name="settle" checked={tree.settlement.mode === "immediate_after_trigger" && !tree.settlement.clawback} disabled={!editable} onChange={() => updateTree({ ...tree, settlement: { mode: "immediate_after_trigger" } })} />
                  Сразу после события
                </label>
                {confirmedTriggers.length && tree.trigger !== confirmedTriggers[0]![0] ? (
                  <label className="check">
                    <input
                      type="radio"
                      name="settle"
                      checked={tree.settlement.mode === "hold_until_confirmation"}
                      disabled={!editable}
                      onChange={() => {
                        const [confirm] = confirmedTriggers.find(([k]) => k.includes("confirmation") || k.includes("accepted")) ?? confirmedTriggers[0]!;
                        const match = ["event.issue_id", "event.task_id"].find((m) => fields[m] && env.data?.triggers[confirm]?.fields[m]);
                        const success = confirm.includes("confirmation")
                          ? { op: "eq", left: { field: "event.confirmation_status" }, right: { literal: "confirmed", type: "enum" } }
                          : { op: "eq", left: { field: "event.root_accepted" }, right: { literal: true, type: "boolean" } };
                        updateTree({ ...tree, settlement: { mode: "hold_until_confirmation", confirm_event: confirm, match_field: match, confirm_condition: success } });
                      }}
                    />
                    Удерживать до подтвержденного результата
                  </label>
                ) : null}
                {reversalTriggers.length ? (
                  <label className="check">
                    <input
                      type="radio"
                      name="settle"
                      checked={Boolean(tree.settlement.clawback)}
                      disabled={!editable}
                      onChange={() => updateTree({ ...tree, settlement: { mode: "immediate_after_trigger", clawback: { event: reversalTriggers[0], match_field: "event.issue_id" } } })}
                    />
                    Сразу, с возвратом при повторном открытии
                  </label>
                ) : null}
              </fieldset>
            </section>
          </Tabs.Content>
          <Tabs.Content value="json">
            <section className="panel stack">
              <label htmlFor="json" className="t-caption">
                Техническое представление дерева
              </label>
              <textarea
                id="json"
                className="textarea code"
                style={{ minHeight: 420, whiteSpace: "pre" }}
                value={jsonText}
                disabled={!editable}
                spellCheck={false}
                onChange={(e) => {
                  setJsonText(e.target.value);
                  try {
                    const parsed = JSON.parse(e.target.value) as RuleTree;
                    setJsonError(null);
                    setTree(parsed);
                    schedule({ tree: parsed, name, source_text: sourceText });
                  } catch (err) {
                    setJsonError((err as Error).message);
                  }
                }}
              />
              {jsonError ? <span className="error-text">JSON не разобран: {jsonError}</span> : null}
            </section>
          </Tabs.Content>
        </Tabs.Root>
      </div>

      <aside className="stack" style={{ position: "sticky", top: 24 }}>
        <section className="panel" aria-live="polite">
          <div className="panel-head">
            <h2 className="t-panel">Проверка</h2>
            {validation.isFetching ? <Loader2 size={16} className="spin" aria-label="Проверяем" /> : v.ok ? <Pill tone="success">Можно публиковать</Pill> : <Pill tone="danger">Ошибок: {v.errors.length}</Pill>}
          </div>
          {v.errors.map((e) => (
            <div key={e.path + e.code} className="issue">
              <TriangleAlert size={16} color="#FF637D" aria-hidden />
              <div>
                <div>{e.message}</div>
                <div className="t-caption">
                  {e.code}, узел {e.path}
                </div>
              </div>
            </div>
          ))}
          {v.warnings.map((w, i) => (
            <div key={`${w.path}-${i}`} className="issue">
              <TriangleAlert size={16} color="#FFD447" aria-hidden />
              <div>
                <div>{w.message}</div>
                <div className="t-caption">Предупреждение не меняет правило</div>
              </div>
            </div>
          ))}
          {!v.errors.length && !v.warnings.length ? <p className="t-secondary" style={{ margin: 0 }}>Ошибок и предупреждений нет.</p> : null}
          <p className="t-caption" style={{ marginBottom: 0 }}>
            Узлов {v.node_count} из 500, глубина {v.depth} из 12.
          </p>
        </section>
        <section className="panel">
          <h2 className="t-panel" style={{ marginBottom: 8 }}>
            Примеры начисления
          </h2>
          <p className="t-caption" style={{ marginTop: 0 }}>
            Считаются тем же интерпретатором и реестром, что и запуск.
          </p>
          {examples.length ? (
            <table className="table">
              <tbody>
                {examples.map((ex) => (
                  <tr key={ex.kind}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{EXAMPLE_KIND[ex.kind] ?? ex.kind}</div>
                      <div className="t-caption">{ex.label}</div>
                    </td>
                    <td className="r">
                      <div>{ex.payout ? `${points(ex.payout)} очк.` : "0"}</div>
                      <div className="t-caption">{ex.ledger_states.length ? ex.ledger_states.map((s) => LEDGER[s] ?? s).join(", ") : ex.kind === "technical_repeat" ? "без изменений" : "не сработало"}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="t-secondary">Примеры появятся, когда правило пройдет проверку.</p>
          )}
        </section>
        {diff && diff.length ? (
          <section className="panel">
            <h2 className="t-panel" style={{ marginBottom: 8 }}>
              Отличия от исходной версии
            </h2>
            {diff.map((row, i) => (
              <div key={i} className="issue">
                {row.important ? <TriangleAlert size={16} color="#FFD447" aria-hidden /> : <span style={{ width: 16 }} />}
                <div>
                  <div style={{ fontWeight: 500 }}>{row.title}</div>
                  <div className="t-caption" style={{ overflowWrap: "anywhere" }}>
                    {row.before !== null && row.before !== undefined ? `было: ${typeof row.before === "string" ? row.before : JSON.stringify(row.before)}` : ""}
                    {row.after !== null && row.after !== undefined ? ` стало: ${typeof row.after === "string" ? row.after : JSON.stringify(row.after)}` : ""}
                  </div>
                </div>
              </div>
            ))}
          </section>
        ) : null}
      </aside>
    </div>
  );
}
