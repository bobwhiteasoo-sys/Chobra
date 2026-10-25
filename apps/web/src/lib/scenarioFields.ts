/** Editor metadata for scenario parameters (spec section 21 "Редактор сценария"). */
export type FieldKind = "int" | "ppm" | "bool" | "enum";
export type ScenarioField = {
  key: string;
  label: string;
  section: "Мир" | "Объекты" | "Действия" | "Наблюдения" | "Метрики" | "Ограничения";
  kind: FieldKind;
  unit?: string;
  min?: number;
  max?: number;
  options?: { value: string; label: string }[];
  hint: string;
  affects: string;
};

const SD: ScenarioField[] = [
  { key: "issue_count", label: "Число обращений", section: "Объекты", kind: "int", unit: "шт.", min: 0, max: 2000, hint: "Исходные клиентские проблемы во внешней ленте", affects: "внешняя лента, знаменатели метрик" },
  { key: "hard_share_ppm", label: "Доля сложных проблем", section: "Объекты", kind: "ppm", unit: "%", min: 0, max: 100, hint: "Истинная сложность, скрыта от участников", affects: "покрытие сложных проблем" },
  { key: "effort_easy", label: "Работа над простой проблемой", section: "Объекты", kind: "int", unit: "квантов", min: 1, max: 50, hint: "Сколько квантов работы нужно", affects: "время решения" },
  { key: "effort_hard", label: "Работа над сложной проблемой", section: "Объекты", kind: "int", unit: "квантов", min: 1, max: 50, hint: "Сколько квантов работы нужно", affects: "время решения, просрочка" },
  { key: "arrival_window_ticks", label: "Окно поступления", section: "Мир", kind: "int", unit: "тиков", min: 1, max: 240, hint: "Обращения поступают в течение первых N тиков", affects: "очередь, возраст обращений" },
  { key: "deadline_easy_ticks", label: "Срок простой проблемы", section: "Объекты", kind: "int", unit: "тиков", min: 1, max: 300, hint: "От поступления до срока", affects: "просрочка" },
  { key: "deadline_hard_ticks", label: "Срок сложной проблемы", section: "Объекты", kind: "int", unit: "тиков", min: 1, max: 300, hint: "От поступления до срока", affects: "просрочка" },
  { key: "actor_effort_per_tick", label: "Ресурс сотрудника", section: "Мир", kind: "int", unit: "квантов за тик", min: 1, max: 20, hint: "Сколько работы участник может сделать за тик", affects: "пропускная способность" },
  { key: "tick_label", label: "Длительность тика", section: "Мир", kind: "enum", options: [{ value: "1 час", label: "1 час" }, { value: "1 день", label: "1 день" }, { value: "15 минут", label: "15 минут" }], hint: "Только подпись; физика среды считает в тиках", affects: "отображение" },
  { key: "horizon_ticks", label: "Основной горизонт", section: "Мир", kind: "int", unit: "тиков", min: 1, max: 240, hint: "После него новые обращения и действия прекращаются", affects: "длительность запуска" },
  { key: "confirmation_delay_ticks", label: "Задержка проверки клиента", section: "Мир", kind: "int", unit: "тиков", min: 0, max: 60, hint: "Через сколько тиков клиент проверяет закрытие", affects: "подтвержденные решения, период наблюдения" },
  { key: "customer_response_ppm", label: "Клиент отвечает на проверку", section: "Мир", kind: "ppm", unit: "%", min: 0, max: 100, hint: "Остальные проверки получают статус unobserved", affects: "подтверждения" },
  { key: "work_error_ppm", label: "Вероятность ошибки кванта", section: "Мир", kind: "ppm", unit: "%", min: 0, max: 100, hint: "Квант не добавляет прогресс; решается сохраненным потоком случайности", affects: "переделка" },
  { key: "allow_close_unsolved", label: "Можно закрыть нерешенное обращение", section: "Действия", kind: "bool", hint: "Одинаково для всех сравниваемых правил", affects: "close_issue" },
  { key: "allow_split", label: "Разбиение обращений", section: "Действия", kind: "bool", hint: "Части сохраняют исходную проблему и объем работы", affects: "split_issue" },
  { key: "split_overhead_units", label: "Накладные расходы разбиения", section: "Действия", kind: "int", unit: "квантов", min: 1, max: 10, hint: "Добавляется к оставшейся работе", affects: "split_issue, переделка" },
  { key: "split_max_depth", label: "Глубина разбиения", section: "Действия", kind: "int", unit: "уровней", min: 1, max: 5, hint: "По умолчанию 2", affects: "split_issue" },
  { key: "split_max_children", label: "Частей у одного узла", section: "Действия", kind: "int", unit: "шт.", min: 2, max: 5, hint: "По умолчанию 5", affects: "split_issue" },
  { key: "allow_report_complexity", label: "Участник может заявить сложность", section: "Действия", kind: "bool", hint: "Истинная сложность не меняется", affects: "report_complexity, правила со сложностью" },
  { key: "allow_reopen", label: "Участник может переоткрыть обращение", section: "Действия", kind: "bool", hint: "Создает возможность повторных закрытий", affects: "reopen_issue" },
  { key: "escalation_enabled", label: "Эскалация во вторую линию", section: "Действия", kind: "bool", hint: "С задержкой и стоимостью", affects: "escalate_issue" },
  { key: "escalation_delay_ticks", label: "Задержка эскалации", section: "Действия", kind: "int", unit: "тиков", min: 0, max: 60, hint: "Сколько обращение проводит во второй линии", affects: "escalate_issue" },
  { key: "free_retry_on_reject", label: "Бесплатный повтор после отказа", section: "Действия", kind: "bool", hint: "Учитывается в сравнениях как условие", affects: "порядок тика" },
  { key: "complexity_visibility", label: "Участники видят сложность", section: "Наблюдения", kind: "enum", options: [{ value: "reported", label: "Только заявленную" }, { value: "true", label: "Истинную" }], hint: "Истинная иначе открывается через inspect_issue", affects: "наблюдение" },
  { key: "triage_error_ppm", label: "Ошибка внешней оценки сложности", section: "Наблюдения", kind: "ppm", unit: "%", min: 0, max: 100, hint: "Внешняя оценка ошибается с этой вероятностью", affects: "правила со сложностью из внешней оценки" },
  { key: "starvation_threshold_ticks", label: "Порог «сложная без внимания»", section: "Метрики", kind: "int", unit: "тиков", min: 1, max: 240, hint: "Для проверки hard_issue_starvation_v1", affects: "проверка" },
];

const TB: ScenarioField[] = [
  { key: "task_count", label: "Число задач", section: "Объекты", kind: "int", unit: "шт.", min: 0, max: 2000, hint: "Исходные задачи во внешней ленте", affects: "знаменатели метрик" },
  { key: "effort_min", label: "Минимальный объем задачи", section: "Объекты", kind: "int", unit: "квантов", min: 1, max: 50, hint: "", affects: "время выполнения" },
  { key: "effort_max", label: "Максимальный объем задачи", section: "Объекты", kind: "int", unit: "квантов", min: 1, max: 50, hint: "", affects: "время выполнения" },
  { key: "dependency_share_ppm", label: "Доля задач с зависимостями", section: "Объекты", kind: "ppm", unit: "%", min: 0, max: 100, hint: "", affects: "приемка" },
  { key: "high_importance_share_ppm", label: "Доля важных задач", section: "Объекты", kind: "ppm", unit: "%", min: 0, max: 100, hint: "", affects: "проверка вытеснения" },
  { key: "deadline_slack_ticks", label: "Запас до срока", section: "Объекты", kind: "int", unit: "тиков", min: 1, max: 240, hint: "", affects: "опоздание" },
  { key: "arrival_window_ticks", label: "Окно поступления", section: "Мир", kind: "int", unit: "тиков", min: 1, max: 240, hint: "", affects: "очередь" },
  { key: "actor_effort_per_tick", label: "Ресурс участника", section: "Мир", kind: "int", unit: "квантов за тик", min: 1, max: 20, hint: "", affects: "пропускная способность" },
  { key: "defect_ppm", label: "Вероятность дефекта на квант", section: "Мир", kind: "ppm", unit: "%", min: 0, max: 100, hint: "", affects: "дефекты, переделка" },
  { key: "dependency_mode", label: "Работа до готовности входов", section: "Действия", kind: "enum", options: [{ value: "forbid", label: "Запрещена" }, { value: "rework_risk", label: "Разрешена с риском переделки" }], hint: "Одинаково для вариантов сравнения", affects: "work_task, приемка" },
  { key: "rework_ppm", label: "Риск переделки", section: "Действия", kind: "ppm", unit: "%", min: 0, max: 100, hint: "Доля преждевременной работы, которую придется повторить", affects: "переделка" },
  { key: "allow_split", label: "Разбиение задач", section: "Действия", kind: "bool", hint: "", affects: "split_task" },
  { key: "split_overhead_units", label: "Накладные расходы разбиения", section: "Действия", kind: "int", unit: "квантов", min: 1, max: 10, hint: "", affects: "split_task" },
  { key: "wip_limit", label: "Лимит незавершенной работы", section: "Ограничения", kind: "int", unit: "задач", min: 1, max: 2000, hint: "Используется правилом TB-P3", affects: "правила" },
  { key: "horizon_ticks", label: "Основной горизонт", section: "Мир", kind: "int", unit: "тиков", min: 1, max: 240, hint: "", affects: "длительность запуска" },
  { key: "crowding_threshold_ticks", label: "Порог вытеснения", section: "Метрики", kind: "int", unit: "тиков", min: 1, max: 240, hint: "Для проверки tb_crowding_out_v1", affects: "проверка" },
];

const RC: ScenarioField[] = [
  { key: "capacity", label: "Емкость", section: "Мир", kind: "int", unit: "единиц", min: 1, max: 1000000, hint: "K в логистическом восстановлении", affects: "восстановление" },
  { key: "initial_stock", label: "Начальный запас", section: "Мир", kind: "int", unit: "единиц", min: 0, max: 1000000, hint: "Не больше емкости", affects: "запас" },
  { key: "regen_num", label: "Коэффициент восстановления, числитель", section: "Мир", kind: "int", min: 0, max: 100, hint: "r = числитель / знаменатель, считается в целых числах", affects: "восстановление" },
  { key: "regen_den", label: "Коэффициент восстановления, знаменатель", section: "Мир", kind: "int", min: 1, max: 100, hint: "", affects: "восстановление" },
  { key: "external_inflow", label: "Внешняя подпитка", section: "Мир", kind: "int", unit: "единиц за тик", min: 0, max: 1000000, hint: "По умолчанию выключена", affects: "запас" },
  { key: "max_request", label: "Максимальный запрос", section: "Действия", kind: "int", unit: "единиц", min: 0, max: 1000000, hint: "", affects: "request_resource" },
  { key: "quota", label: "Квота", section: "Ограничения", kind: "int", unit: "единиц", min: 0, max: 1000000, hint: "", affects: "правила, проверка квоты" },
  { key: "cap_mode", label: "Механизм ограничения", section: "Ограничения", kind: "enum", options: [{ value: "none", label: "Нет" }, { value: "request_cap", label: "Ограничение запроса" }, { value: "share_cap", label: "Ограничение полученной доли" }], hint: "Запрос выше предела отклоняется, а не урезается", affects: "распределение" },
  { key: "min_stock", label: "Минимальный запас", section: "Метрики", kind: "int", unit: "единиц", min: 0, max: 1000000, hint: "Для проверки rc_below_min_stock_v1", affects: "проверка" },
  { key: "messages_enabled", label: "Сообщения между участниками", section: "Действия", kind: "bool", hint: "Сообщение занимает ход и не дает полномочий", affects: "send_message" },
  { key: "horizon_ticks", label: "Основной горизонт", section: "Мир", kind: "int", unit: "тиков", min: 1, max: 240, hint: "", affects: "длительность запуска" },
];

export const SCENARIO_FIELDS: Record<string, ScenarioField[]> = { supportdesk: SD, taskboard: TB, resourcecommons: RC };
export const SECTIONS = ["Мир", "Объекты", "Действия", "Наблюдения", "Метрики", "Ограничения"] as const;
