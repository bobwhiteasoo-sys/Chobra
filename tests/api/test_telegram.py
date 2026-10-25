"""Identity proof, browser binding, expiry and single use for Telegram QR login."""
from datetime import timedelta
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from chobra_api.app import create_app
from chobra_api.config import settings
from chobra_api.db import SessionLocal
from chobra_api.models import TelegramLogin
from chobra_api.security import now
from chobra_api import telegram_bot


@pytest.fixture
def tg(monkeypatch):
    monkeypatch.setitem(settings.__dict__, "telegram_bot_token", "test-only")
    sent=[]
    monkeypatch.setattr(telegram_bot,"telegram_call",lambda method,payload=None,**kw: sent.append((method,payload)) or True)
    return TestClient(create_app()), sent


def create(client):
    r=client.post('/api/v1/auth/telegram/challenge',json={})
    assert r.status_code==201,r.text
    c=r.json(); start=parse_qs(urlparse(c['url']).query)['start'][0].removeprefix('login_')
    return c,start


def update(command,person=700001):
    who={"id":person,"first_name":"Тест Telegram","is_bot":False}
    message={"chat":{"id":person,"type":"private"},"from":who,"text":command}
    if command.startswith(('approve:','reject:')):
        return {"callback_query":{"id":"test-callback","from":who,"message":message,"data":command}}
    return {"message":message}


def test_full_qr_flow_browser_binding_and_single_use(tg):
    browser,sent=tg;c,start=create(browser)
    base=f"/api/v1/auth/telegram/challenge/{c['id']}"
    stranger=TestClient(create_app())
    assert stranger.get(base).status_code==404
    assert stranger.post(base+'/consume',json={}).status_code==404
    assert browser.post(base+'/consume',json={}).status_code==409
    telegram_bot.process(update('/start login_'+start))
    assert c['code'] in sent[-1][1]['text']
    assert browser.get(base).json()['status']=='pending'
    telegram_bot.process(update('approve:'+start))
    assert browser.get(base).json()['status']=='approved'
    r=browser.post(base+'/consume',json={});assert r.status_code==200,r.text
    assert r.json()['display_name']=='Тест Telegram'
    assert len(r.json()['workspaces'])==1
    assert browser.get('/api/v1/me').status_code==200
    assert browser.post(base+'/consume',json={}).status_code==409
    assert 'HttpOnly' in r.headers.get('set-cookie','')


def test_expiry_refresh_origin_and_rejection(tg):
    browser,_=tg;c,start=create(browser)
    base=f"/api/v1/auth/telegram/challenge/{c['id']}"
    assert browser.post('/api/v1/auth/telegram/challenge',json={},headers={'Origin':'https://evil.example'}).status_code==403
    telegram_bot.process(update('reject:'+start))
    assert browser.get(base).status_code==410
    c,_=create(browser)
    with SessionLocal() as db:
        row=db.scalar(select(TelegramLogin).where(TelegramLogin.id==c['id']));row.expires_at=now()-timedelta(seconds=1);db.commit()
    assert browser.get(f"/api/v1/auth/telegram/challenge/{c['id']}").status_code==410


def test_refresh_invalidates_old_code(tg):
    browser,_=tg;c,start=create(browser);new,_=create(browser)
    telegram_bot.process(update('approve:'+start))
    assert browser.get(f"/api/v1/auth/telegram/challenge/{c['id']}").status_code==410
    assert browser.get(f"/api/v1/auth/telegram/challenge/{new['id']}").json()['status']=='pending'


def test_no_group_auth_no_public_approval_endpoint(tg):
    browser,_=tg;c,start=create(browser)
    u=update('approve:'+start);u['callback_query']['message']['chat']['type']='group'
    telegram_bot.process(u)
    assert browser.get(f"/api/v1/auth/telegram/challenge/{c['id']}").json()['status']=='pending'
    assert browser.post('/api/v1/auth/telegram/approve',json={'id':c['id'],'user_id':1}).status_code==404


def test_bot_demo_is_free_and_same_telegram_identity(tg):
    browser,sent=tg
    telegram_bot.process(update('/demo',person=700002))
    assert 'обращения к ИИ нет' in sent[-1][1]['text']
    telegram_bot.process(update('/status',person=700002))
    assert 'Быстрая проверка из Telegram' in sent[-1][1]['text']
    c,start=create(browser);telegram_bot.process(update('approve:'+start,person=700002))
    me=browser.post(f"/api/v1/auth/telegram/challenge/{c['id']}/consume",json={}).json()
    ws=me['workspaces'][0]['id']
    projects=browser.get('/api/v1/projects',params={'workspace_id':ws}).json()['items']
    assert any(p['name']=='Пример: премии поддержки' for p in projects)
