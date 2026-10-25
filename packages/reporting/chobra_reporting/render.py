"""Markdown and HTML renderings of one report snapshot (spec section 19 "Экспорт").

Both are produced from the same stored snapshot, so the PDF (printed from the HTML) and the
Markdown always show the same values and the same incomplete runs.
"""
from __future__ import annotations

import html
from typing import Any

POINT = 1_000_000

LIMITATIONS = (
    "Испытание демонстрирует возможное поведение в заданной модели среды. Оно не устанавливает вероятность такого поведения у реальных "
    "сотрудников и не является психологической моделью человека. Отсутствие найденного нарушения означает только отсутствие нарушения "
    "в выполненных испытаниях при указанных условиях."
)


def _points(value: Any) -> str:
    if value is None:
        return "—"
    return f"{int(value) / POINT:g}"


def markdown(snapshot: dict[str, Any]) -> str:
    s = snapshot
    lines = [f"# Отчет Chobra: {s['project']['name']}", "", f"Сформирован {s['generated_at']} по серии `{s['batch']['id']}` (план `{s['batch']['plan_hash'][:16]}`).", ""]
    lines += ["## Вопрос исследования", "", s["project"]["research_question"] or "—", "", f"Желаемый результат: {s['project']['desired_outcome'] or '—'}", ""]
    env = s["environment"]
    lines += ["## Среда", "", f"{env['name']} {env['version']}. {env['description']}", "", "Доступные действия участников: " + ", ".join(f"`{a}`" for a in env["actions"]) + ".", ""]
    lines += ["## Варианты правил", ""]
    for v in s["variants"]:
        lines += [f"### {v['label']}", "", f"Описание: {v['source_text'] or '—'}", "", f"Единица учета: {v['unit_of_account']}. Хеш дерева `{v['rule_hash'][:16]}`.", ""]
        for w in v["warnings"]:
            lines.append(f"- Предупреждение: {w}")
        if v["warnings"]:
            lines.append("")
    c = s["conditions"]
    lines += ["## Условия", "", f"Seed: {', '.join(str(x) for x in c['seeds'])}. Основной горизонт {c['horizon_ticks']} тиков, период наблюдения {c['observation_tail_ticks']}. "
              f"Участников: {c['actor_count']}. Режим агентов: {', '.join(c['modes'])} ({c['agent_kind']}). Внешняя лента общая для вариантов: да.", ""]
    lines += ["## Число запусков", "", "| Вариант | Запланировано | Завершено | Неполных |", "| --- | ---: | ---: | ---: |"]
    for label, counts in s["counts"].items():
        lines.append(f"| {label} | {counts['planned']} | {counts['completed']} | {counts['incomplete']} |")
    lines.append("")
    comp = s.get("comparison")
    if comp and not comp.get("error"):
        lines += ["## Фактические результаты", "", f"Сравнение «{comp['candidate']}» с «{comp['baseline']}», полных пар: {comp['pairs_complete']}.", "",
                  "| Показатель | Средняя разность | Медиана | Диапазон | Bootstrap 95 % |", "| --- | ---: | ---: | --- | --- |"]
        for metric in comp["metrics"].values():
            rng = f"{metric['range'][0]} … {metric['range'][1]}" if metric["range"] else "—"
            ci = f"{metric['bootstrap_ci'][0]} … {metric['bootstrap_ci'][1]}" if metric["bootstrap_ci"] else "меньше 10 пар"
            lines.append(f"| {metric['title']} | {metric['mean_diff'] or '—'} | {metric['median_diff'] or '—'} | {rng} | {ci} |")
        lines.append("")
        if comp["tradeoffs"]:
            lines += ["### Компромиссы", ""] + [f"- {t}" for t in comp["tradeoffs"]] + [""]
    lines += ["## Нарушения", "", "| Вариант | Проверка | Нарушений / применимых | Интервал Уилсона 95 % | Неполных |", "| --- | --- | ---: | --- | ---: |"]
    for row in s["violations"]:
        wilson = f"{row['wilson'][0]} … {row['wilson'][1]}" if row["wilson"] else "—"
        lines.append(f"| {row['variant']} | {row['title']} | {row['failed']} / {row['applicable']} | {wilson} | {row['incomplete']} |")
    lines += ["", "Интервал характеризует выбранный генератор условий и конфигурацию агентов, а не долю людей в компании.", ""]
    lines += ["## Проверенные контрпримеры", ""]
    if not s["findings"]:
        lines += ["Контрпримеров в серии не найдено.", ""]
    for f in s["findings"]:
        lines += [f"### {f['title']} ({f['variant']}, seed {f['seed']})", "", f["explanation"], "", f"Воспроизведение: {f['replay_status']}. Доказательства: события {', '.join(str(x) for x in f['evidence_seqs'])}.", ""]
    if s["incomplete_runs"]:
        lines += ["## Неполные испытания", ""] + [f"- {r['variant']}, seed {r['seed']}: {r['status']} ({r['stop_reason'] or 'без причины'})" for r in s["incomplete_runs"]] + [""]
    lines += ["## Ограничения", "", LIMITATIONS, ""]
    return "\n".join(lines)


def html_document(snapshot: dict[str, Any]) -> str:
    body = []
    in_table = False
    for line in markdown(snapshot).splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= {"-", ":", " "}:
                continue
            if not in_table:
                body.append("<table>")
                in_table = True
                body.append("<tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cells) + "</tr>")
            else:
                body.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if line.startswith("### "):
            body.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("- "):
            body.append(f"<p class='li'>• {html.escape(line[2:])}</p>")
        elif line:
            body.append(f"<p>{html.escape(line).replace('`', '')}</p>")
    if in_table:
        body.append("</table>")
    style = """
      @page { size: A4; margin: 16mm 14mm; }
      body { font-family: Inter, -apple-system, 'Segoe UI', Roboto, sans-serif; color: #17120A; font-size: 11pt; line-height: 1.45; }
      h1 { font-size: 20pt; margin: 0 0 6pt; } h1::before { content: ''; display: inline-block; width: 10pt; height: 10pt; background: #FFD447; border-radius: 3pt; margin-right: 8pt; }
      h2 { font-size: 14pt; margin: 16pt 0 6pt; border-bottom: 1px solid #E4DFEA; padding-bottom: 3pt; } h3 { font-size: 12pt; margin: 10pt 0 4pt; }
      table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-variant-numeric: tabular-nums; }
      th, td { border-bottom: 1px solid #E4DFEA; padding: 4pt 6pt; text-align: left; font-size: 9.5pt; } th { color: #51495F; font-weight: 600; }
      p { margin: 4pt 0; } p.li { margin-left: 8pt; }
    """
    return f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>Отчет Chobra</title><style>{style}</style></head><body>{''.join(body)}</body></html>"
