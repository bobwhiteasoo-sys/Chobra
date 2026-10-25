"""Readable, factual summary of completed paired trials. Shared by web and Telegram."""
from decimal import Decimal, InvalidOperation

DISPLAY = {
    'supportdesk': [('resolved_rate','Решено проблем','percent','higher'),('false_closure_rate','Закрыто без решения','percent','lower'),('reward_total','Начислено награды','points','neutral')],
    'taskboard': [('accepted_roots','Принято задач','number','higher'),('defects','Найдено дефектов','number','lower'),('reward_total','Начислено награды','points','neutral')],
    'resourcecommons': [('final_stock','Ресурс в конце','number','higher'),('sustainable_ticks','Шагов с достаточным запасом','number','higher'),('reward_total','Начислено награды','points','neutral')],
}


def value(text, unit):
    try:
        n=Decimal(str(text))
        if not n.is_finite(): return None
        return float(n * 100 if unit=='percent' else n / 1_000_000 if unit=='points' else n)
    except (InvalidOperation,TypeError,ValueError): return None


def fmt(n, unit):
    if n is None: return 'Нет данных'
    return f'{n:,.1f}'.replace(',',' ').removesuffix('.0').replace('.',',') + ('%' if unit=='percent' else ' очк.' if unit=='points' else '')


def overview(pair, environment='supportdesk'):
    if not pair or pair.get('error'):
        return {'title':'Пока недостаточно данных для сравнения','description':'Дождитесь завершения сопоставимых запусков.','metrics':[], 'limits':['Ошибка или неполный запуск не подтверждает безопасность правила.'], 'next_step':'Откройте состояние запусков и проверьте причину остановки.', 'pairs':0}
    metrics=[]
    for key,title,unit,direction in DISPLAY.get(environment,DISPLAY['supportdesk']):
        source=pair.get('metrics',{}).get(key,{})
        rows=source.get('pair_values',[])
        usable=[(value(r.get('baseline'),unit),value(r.get('candidate'),unit)) for r in rows]
        usable=[(a,b) for a,b in usable if a is not None and b is not None]
        if not usable: continue
        a=sum(x for x,_ in usable)/len(usable); b=sum(y for _,y in usable)/len(usable)
        delta=b-a
        change=(f'{abs(delta):.1f}'.removesuffix('.0').replace('.',',')+(' п.п.' if unit=='percent' else ' очк.' if unit=='points' else ''))
        effect='same' if abs(delta)<.00001 else 'neutral' if direction=='neutral' else 'better' if (delta>0)==(direction=='higher') else 'worse'
        metrics.append({'key':key,'title':title,'unit':unit,'baseline':a,'candidate':b,'baseline_text':fmt(a,unit),'candidate_text':fmt(b,unit),'change': 'Без изменений' if abs(delta)<.00001 else f"На {change} {'больше' if delta>0 else 'меньше'}",'effect':effect,'pairs':len(usable)})
    improved=pair.get('improved',[]); worsened=pair.get('worsened',[])
    pairs=pair.get('pairs_complete',0)
    title='Разницы в полезном результате не найдено'
    if improved and worsened: title='Есть улучшения, но есть и потери'
    elif improved: title='Второе правило улучшило часть результатов'
    elif worsened: title='Второе правило ухудшило часть результатов'
    if not pairs: title='Пока недостаточно данных для сравнения'
    if pair.get('pairing',{}).get('tapes_match') is False: title='Условия различаются — вывод требует осторожности'
    limits=[f'Средние значения по {pairs} завершённым парам. Первое правило — исходное, второе — проверяемое.']
    incomplete=sum(c.get('incomplete',0) for c in pair.get('counts',{}).values())
    if incomplete: limits.append(f'Не завершено запусков: {incomplete}. Они не считаются успешной проверкой.')
    if pairs<10: limits.append('Это небольшая проверка. Для статистического интервала нужны минимум 10 полных пар.')
    limits.append('Вывод относится к этой симуляции, а не к поведению реальных людей.')
    return {'title':title,'description':'Сравните полезную работу и награду: высокая выплата сама по себе не означает хороший результат.','baseline':pair.get('baseline','Первое правило'),'candidate':pair.get('candidate','Второе правило'),'metrics':metrics,'pairs':pairs,'limits':limits,'next_step':'Проверьте новое правило на других исходных условиях. Посмотрите, какие нарушения остались.' if improved else 'Измените условие награды и повторите проверку. Начните с найденных нарушений.'}


def telegram_report(summary, project_name):
    import html
    esc=lambda x:html.escape(str(x))
    lines=[f'<b>Отчёт Chobra</b>',esc(project_name),'',f'<b>{esc(summary["title"])}</b>','']
    if summary.get('metrics'):
        lines.extend([f'<b>А</b> · {esc(summary["baseline"])}',f'<b>Б</b> · {esc(summary["candidate"])}',''])
        for m in summary['metrics']:
            lines.extend([f'<b>{esc(m["title"])}</b>',f'А: {esc(m["baseline_text"])} → Б: {esc(m["candidate_text"])}',esc(m['change']),''])
    lines.extend(['<b>Что делать дальше</b>',esc(summary['next_step']),'','<b>Как читать эти цифры</b>',*[esc(s) for s in summary['limits']]])
    return '\n'.join(lines)
