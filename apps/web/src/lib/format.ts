const POINT = 1_000_000;

export function points(microunits: number | null | undefined): string {
  if (microunits === null || microunits === undefined) return "—";
  const value = microunits / POINT;
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, "");
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function count(n: number, one: string, few: string, many: string): string {
  return `${n} ${plural(n, one, few, many)}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

export function ratioText(sample: { value: string | number | null; applicability: string; numerator: number | null; denominator: number | null; unit?: string } | undefined): string {
  if (!sample) return "—";
  if (sample.applicability === "not_applicable") return "Не применимо";
  if (sample.unit === "ratio" && sample.numerator !== null && sample.denominator !== null) {
    return `${Math.round((sample.numerator / sample.denominator) * 100)} % (${sample.numerator} из ${sample.denominator})`;
  }
  if (sample.unit === "reward_microunits" && typeof sample.value === "number") return `${points(sample.value)} очк.`;
  return sample.value === null ? "—" : String(sample.value);
}

export const ENV_LABELS: Record<string, string> = {
  supportdesk: "SupportDesk",
  taskboard: "TaskBoard",
  resourcecommons: "ResourceCommons",
};

export const MODE_LABELS: Record<string, string> = {
  cooperative: "Кооперативный",
  incentive_seeking: "Ищет награду",
  adversarial_search: "Поиск лазеек",
  recorded: "Записанные действия",
};

export const RUN_STATUS: Record<string, { label: string; tone: "neutral" | "accent" | "success" | "danger" | "info" }> = {
  draft: { label: "Черновик", tone: "neutral" },
  validating: { label: "Проверка", tone: "info" },
  queued: { label: "В очереди", tone: "neutral" },
  initializing: { label: "Подготовка мира", tone: "info" },
  running: { label: "Выполняется", tone: "accent" },
  pause_requested: { label: "Ставится на паузу", tone: "info" },
  paused: { label: "На паузе", tone: "neutral" },
  resume_requested: { label: "Продолжается", tone: "info" },
  cancel_requested: { label: "Останавливается", tone: "info" },
  canceled: { label: "Остановлен", tone: "neutral" },
  auditing: { label: "Аудит", tone: "info" },
  completed: { label: "Завершен", tone: "success" },
  completed_with_incomplete: { label: "Завершена, есть неполные", tone: "neutral" },
  failed: { label: "Ошибка выполнения", tone: "danger" },
  budget_exhausted: { label: "Бюджет исчерпан", tone: "danger" },
};

export const VERDICT: Record<string, { label: string; tone: "neutral" | "success" | "danger" }> = {
  observed_violation: { label: "Нарушение наблюдалось", tone: "danger" },
  no_violation_observed: { label: "Нарушений не наблюдалось", tone: "success" },
  inconclusive: { label: "Без вывода", tone: "neutral" },
};

export const CHECK_STATUS: Record<string, { label: string; tone: "neutral" | "success" | "danger" | "info" }> = {
  pass: { label: "Не нарушено", tone: "success" },
  fail: { label: "Нарушение", tone: "danger" },
  not_applicable: { label: "Не применимо", tone: "neutral" },
  inconclusive: { label: "Без вывода", tone: "info" },
};

export const REPLAY_STATUS: Record<string, string> = {
  not_checked: "Воспроизведение не проверялось",
  replay_verified: "Воспроизведение подтверждено",
  replay_failed: "Воспроизведение не совпало",
  replay_unavailable: "Воспроизведение недоступно",
};
