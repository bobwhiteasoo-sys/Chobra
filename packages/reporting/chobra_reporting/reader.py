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
    from chobra_audit.catalog import available_checks
    labels={c['check_id']:c['title'] for c in available_checks(environment)}
    candidate_checks=pair.get('violations',{}).get(pair.get('candidate'),{})
    remaining=[labels.get(key,key) for key,row in candidate_checks.items() if row.get('failed',0)>0]
    applicable=any(row.get('applicable',0)>0 for row in candidate_checks.values())
    concern=('Остались нарушения: '+ '; '.join(remaining[:2])+'.' if remaining else
             'В применимых проверках нарушений не найдено. Это не гарантия отсутствия лазеек.' if applicable else
             'Проверок недостаточно, чтобы оценить оставшиеся нарушения.')
    if incomplete: concern=f'Не завершено запусков: {incomplete}. '+concern
    primary=metrics[0] if metrics else None
    conclusion='Данных пока недостаточно для вывода.'
    if pairs and primary:
        conclusion=('Новое правило дало больше пользы.' if primary['effect']=='better' else
                    'Новое правило дало меньше пользы.' if primary['effect']=='worse' else
                    'Основной результат не изменился.')
        if improved and worsened: conclusion='Есть улучшения, но есть и потери.'
        if pair.get('pairing',{}).get('tapes_match') is not True:
            conclusion='Сопоставимость условий не подтверждена.'
    if not pairs:
        concern='Нет завершённых сопоставимых запусков. Делать вывод о правиле рано.'
    next_step=('Доработайте оставшиеся нарушения и повторите проверку.' if remaining else
               'Проверьте правило на других исходных условиях.' if pairs else
               'Откройте запуски и проверьте, почему они не завершились.')
    short={
        'heading':'Краткая сводка Chobra',
        'context':f'Сопоставимых запусков: {pairs * (1 if pair.get("baseline")==pair.get("candidate") else 2)}',
        'conclusion':conclusion,
        'tested':f'«{pair.get("baseline","Первое правило")}» и «{pair.get("candidate","Второе правило")}»',
        'outcome':f'{primary["title"]}: {primary["baseline_text"]} → {primary["candidate_text"]}.' if primary else 'Полезный результат пока не рассчитан.',
        'concern':concern,
        'next_step':next_step,
    }
    return {'title':title,'description':'Сравните полезную работу и награду: высокая выплата сама по себе не означает хороший результат.','baseline':pair.get('baseline','Первое правило'),'candidate':pair.get('candidate','Второе правило'),'metrics':metrics,'pairs':pairs,'limits':limits,'next_step':next_step,'brief':short}


def telegram_report(summary, project_name):
    import html
    esc=lambda x:html.escape(str(x))
    brief=summary.get('brief')
    if brief:
        lines=[f'<b>{esc(brief["heading"])}</b>',esc(project_name),esc(brief['context']),'',
               f'<b>{esc(brief["conclusion"])}</b>','',
               '<b>Что проверили</b>',esc(brief['tested']),'',
               '<b>Что получилось</b>',esc(brief['outcome']),'',
               '<b>На что обратить внимание</b>',esc(brief['concern']),'',
               '<b>Следующий шаг</b>',esc(brief['next_step']),'',
               'Вывод относится к этой симуляции. Подробные цифры — на сайте.']
    else:
        lines=['<b>Краткая сводка Chobra</b>',esc(project_name),'',esc(summary['title']),'',esc(summary['next_step'])]
    return '\n'.join(lines)
