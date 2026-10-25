import type { RunEvent } from "@/lib/types";

import type { AgentStatus } from "./projection";

export const EVENT_LABELS: Record<string, string> = {
  "run.initialized": "Мир подготовлен",
  "run.paused": "Запуск на паузе",
  "run.completed": "Запуск завершен",
  "run.canceled": "Запуск остановлен",
  "run.failed": "Ошибка выполнения",
  "run.budget_exhausted": "Бюджет исчерпан",
  "run.invariant_violated": "Нарушен инвариант среды",
  "run.events_committed": "События зафиксированы",
  "tick.completed": "Тик завершен",
  "model_call.started": "Запрос к модели",
  "model_call.completed": "Ответ модели получен",
  "model_call.failed": "Вызов модели не удался",
  "action.proposed": "Предложено действие",
  "action.rejected": "Действие отклонено",
  "action.committed": "Действие выполнено",
  "reward.pending": "Награда ожидает подтверждения",
  "reward.settled": "Награда начислена",
  "reward.reversed": "Награда возвращена",
  "reward.rejected": "Начисление отклонено",
  "check.failed": "Нарушение",
  "audit.completed": "Аудит завершен",
  "issue.arrived": "Новое обращение",
  "issue.claimed": "Обращение закреплено",
  "issue.inspected": "Обращение осмотрено",
  "issue.work_done": "Работа над обращением",
  "issue.work_failed": "Квант работы без прогресса",
  "issue.problem_solved": "Проблема фактически решена",
  "issue.closed": "Обращение закрыто",
  "issue.confirmation_completed": "Проверка клиента",
  "issue.reopened": "Обращение возвращено в работу",
  "issue.split": "Обращение разделено",
  "issue.complexity_reported": "Заявлена сложность",
  "issue.escalated": "Эскалация во вторую линию",
  "issue.escalation_returned": "Возврат из второй линии",
  "issue.overdue": "Срок обращения истек",
  "task.arrived": "Новая задача",
  "task.taken": "Задача взята",
  "task.work_done": "Работа над задачей",
  "task.declared_done": "Задача отмечена готовой",
  "task.acceptance_requested": "Запрошена приемка",
  "task.accepted": "Задача принята",
  "task.rejected": "Приемка не пройдена",
  "task.defect_introduced": "Внесен дефект",
  "task.fixed": "Дефект исправлен",
  "task.split": "Задача разделена",
  "task.handed_off": "Задача передана",
  "task.overdue": "Срок задачи истек",
  "resource.allocated": "Ресурс выдан",
  "resource.regenerated": "Запас восстановился",
  "resource.depleted": "Запас исчерпан",
};

export const ACTION_LABELS: Record<string, string> = {
  wait: "пропуск хода",
  inspect_issue: "осмотр обращения",
  claim_issue: "закрепление обращения",
  work_issue: "работа над обращением",
  close_issue: "закрытие обращения",
  reopen_issue: "повторное открытие",
  split_issue: "разделение обращения",
  report_complexity: "заявление сложности",
  escalate_issue: "эскалация",
  take_task: "взятие задачи",
  work_task: "работа над задачей",
  declare_done: "отметка «готово»",
  split_task: "разделение задачи",
  request_acceptance: "запрос приемки",
  fix_task: "исправление дефекта",
  handoff_task: "передача задачи",
  request_resource: "запрос ресурса",
  send_message: "сообщение",
};

export const AGENT_STATUS: Record<AgentStatus, string> = {
  ready: "Ожидает ход",
  choosing: "Выбирает действие",
  submitted: "Отправил решение",
  proposed: "Действие на проверке",
  rejected: "Действие отклонено",
  acted: "Выполнил действие",
  error: "Ошибка вызова",
  idle: "Ожидание",
};

export function eventLabel(event: RunEvent): string {
  return EVENT_LABELS[event.type] ?? event.type;
}

export function actionLabel(type: string | null | undefined): string {
  if (!type) return "";
  return ACTION_LABELS[type] ?? type;
}

/** Short human detail for one event, built from its payload only. */
export function eventDetail(event: RunEvent): string {
  const p = event.payload;
  const points = (v: unknown) => (typeof v === "number" ? `${v / 1_000_000} очк.` : "");
  switch (event.type) {
    case "action.proposed":
    case "action.committed":
      return actionLabel(String(p.action_type ?? ""));
    case "action.rejected":
      return `${actionLabel(String(p.action_type ?? ""))}: ${String(p.message ?? p.code ?? "")}`;
    case "reward.pending":
    case "reward.settled":
    case "reward.reversed":
      return `${points(p.reward_microunits)}${p.reason ? `, ${String(p.reason)}` : ""}`;
    case "check.failed":
      return String(p.title ?? p.check_id ?? "");
    case "issue.confirmation_completed":
      return String(p.confirmation_status ?? "");
    case "issue.work_done":
    case "task.work_done":
      return typeof p.completed_effort_units === "number" ? `выполнено ${p.completed_effort_units} квант.` : "";
    case "resource.allocated":
      return `${String(p.allocated ?? 0)} ед., запас ${String(p.stock_after ?? "")}`;
    case "resource.regenerated":
      return `запас ${String(p.stock_after ?? "")}`;
    case "issue.split":
    case "task.split":
      return `${((p.child_ids as unknown[]) ?? []).length} части`;
    case "model_call.failed":
      return String(p.error_kind ?? "");
    default:
      return "";
  }
}

export function itemNumber(id: string): string {
  const match = id.match(/(\d+)(?:_(\d+))*$/);
  if (!match) return id;
  return id.replace(/^(issue|task)_/, "").replace(/_/g, ".");
}

export function actorName(id: string | null | undefined, order: string[]): string {
  if (!id) return "";
  const index = order.indexOf(id);
  return index >= 0 ? `Участник ${index + 1}` : id;
}
