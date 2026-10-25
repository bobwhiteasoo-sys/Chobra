from chobra_reporting.reader import overview, telegram_report


def test_readable_units_and_escaped_report():
    pair={'baseline':'<первое>','candidate':'Второе','pairs_complete':3,'improved':['resolved_rate'],'worsened':[],'counts':{},'metrics':{'resolved_rate':{'pair_values':[{'baseline':'0.0','candidate':'0.5'}]},'reward_total':{'pair_values':[{'baseline':'350000000','candidate':'10000000'}]}}}
    s=overview(pair)
    assert s['metrics'][0]['candidate_text']=='50%'
    assert s['metrics'][1]['baseline_text']=='350 очк.'
    assert '10 полных пар' in ' '.join(s['limits'])
    r=telegram_report(s,'<project>')
    assert '&lt;project&gt;' in r and '&lt;первое&gt;' in r


def test_missing_pair_is_not_safe():
    s=overview(None)
    assert not s['metrics'] and s['pairs']==0
    assert 'недостаточно' in s['title']
