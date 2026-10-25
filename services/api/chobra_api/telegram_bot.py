"""Telegram assistant. Long polling runs once as a separate service; tokens never enter logs."""
from __future__ import annotations

import json
import logging
import ssl
import threading
from datetime import timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen

import certifi
from sqlalchemy import select, text

from .access import Ctx, load_roles
from .config import settings
from .db import SessionLocal, set_tenant
from .models import AgentProfile, AuthSession, BotCursor, ExperimentBatch, Membership, Project, RuleVersion, ScenarioVersion, TelegramLogin, User, Workspace
from .security import now, token_hash
from .services import create_batch, create_project, expand_plan

log = logging.getLogger("chobra.telegram")


def telegram_call(method: str, payload: dict | None = None, timeout: int = 40):
    request = Request(f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}",
                      data=json.dumps(payload or {}).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout, context=ssl.create_default_context(cafile=certifi.where())) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram API rejected request")
    return result["result"]


def account(db, person: dict) -> Ctx:
    subject = str(person["id"])
    # A deterministic Telegram identity never merges accounts by display name or email.
    user = db.scalar(select(User).where(User.oidc_issuer == "telegram", User.oidc_subject == subject))
    if user is None:
        name = " ".join(str(person.get(k, "")) for k in ("first_name", "last_name")).strip()[:120] or "Участник Chobra"
        user = User(oidc_issuer="telegram", oidc_subject=subject, display_name=name, email=None)
        db.add(user); db.flush()
    roles = load_roles(db, user)
    set_tenant(db, user.id, roles)
    if not roles:
        from .routers.core import DEFAULT_LIMITS, DEFAULT_RETENTION
        workspace = Workspace(name=f"Проекты: {user.display_name}"[:120], owner_id=user.id,
                              limits=dict(DEFAULT_LIMITS), retention_policy=dict(DEFAULT_RETENTION), model_settings={})
        db.add(workspace); db.flush()
        db.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
        roles[workspace.id] = "owner"
        set_tenant(db, user.id, roles)
        db.flush()
    return Ctx(db, user, AuthSession(user_id=user.id), roles)


def site_buttons(path="/"):
    # Telegram rejects localhost URLs. Development still supports scanning the t.me QR.
    if settings.public_url.startswith("https://"):
        return {"inline_keyboard": [[{"text": "Открыть Chobra", "url": settings.public_url.rstrip('/') + path}], [{"text": "Запустить бесплатный пример", "callback_data": "demo"}]]}
    return {"inline_keyboard": [[{"text": "Запустить бесплатный пример", "callback_data": "demo"}]]}


def send(chat_id, message, buttons=None):
    payload = {"chat_id": chat_id, "text": message, "link_preview_options": {"is_disabled": True}}
    if buttons:
        payload["reply_markup"] = buttons
    telegram_call("sendMessage", payload)


def demo(ctx):
    db = ctx.db
    projects = db.scalars(select(Project).where(Project.workspace_id.in_(ctx.workspace_ids), Project.owner_id == ctx.user.id,
                                              Project.is_demo.is_(True), Project.environment_id == "supportdesk", Project.archived_at.is_(None))).all()
    project = projects[0] if projects else create_project(db, workspace_id=ctx.workspace_ids[0], user_id=ctx.user.id,
                                                         name="Пример: премии поддержки", environment="supportdesk", is_demo=True)
    recent = db.scalar(select(ExperimentBatch).where(ExperimentBatch.project_id == project.id, ExperimentBatch.created_at > now() - timedelta(minutes=1)).order_by(ExperimentBatch.created_at.desc()).limit(1))
    if recent:
        return recent
    scenario = db.scalar(select(ScenarioVersion).where(ScenarioVersion.project_id == project.id, ScenarioVersion.status == "published").order_by(ScenarioVersion.version.desc()).limit(1))
    rules = db.scalars(select(RuleVersion).where(RuleVersion.project_id == project.id, RuleVersion.status == "published").order_by(RuleVersion.version)).all()
    profile = db.scalar(select(AgentProfile).where(AgentProfile.project_id == project.id, AgentProfile.kind == "scripted", AgentProfile.mode == "incentive_seeking"))
    body = {"scenario_version_id": str(scenario.id), "agent_profile_id": str(profile.id),
            "variants": [{"label": r.name, "rule_version_id": str(r.id)} for r in rules[:2]],
            "conditions": {"seeds": [101, 102, 103], "horizon_ticks": 30}}
    return create_batch(db, project, ctx.user.id, expand_plan(db, project, body), "Быстрая проверка из Telegram")


def process(update):
    callback = update.get("callback_query")
    message = update.get("message") or (callback or {}).get("message")
    person = (callback or {}).get("from") or (message or {}).get("from")
    if not message or not person or person.get("is_bot") or message.get("chat", {}).get("type") != "private":
        return
    chat_id = message["chat"]["id"]
    if chat_id != person["id"]:
        return
    command = callback.get("data", "") if callback else message.get("text", "").strip()
    if callback:
        telegram_call("answerCallbackQuery", {"callback_query_id": callback["id"]})
    if command.startswith("/start login_") or command.startswith(("approve:", "reject:")):
        start = command.split("login_", 1)[1] if command.startswith("/start") else command.split(":", 1)[1]
        with SessionLocal() as db:
            row = db.scalar(select(TelegramLogin).where(TelegramLogin.start_hash == token_hash(start)).with_for_update())
            if not row or row.status != "pending" or row.expires_at <= now():
                send(chat_id, "Этот QR-код уже использован или истёк. Обновите код на сайте."); return
            if command.startswith("/start"):
                send(chat_id, f"Вход в Chobra · {settings.public_url}\n\nКод на экране: {row.display_code}\n\nПодтвердите, только если вы сами открыли вход и код совпадает. QR действует 5 минут.",
                     {"inline_keyboard": [[{"text": "Подтвердить вход", "callback_data": f"approve:{start}"}], [{"text": "Отклонить", "callback_data": f"reject:{start}"}]]})
                return
            if command.startswith("reject:"):
                row.status = "expired"; db.commit(); send(chat_id, "Вход отклонён."); return
            ctx = account(db, person)
            row.user_id = ctx.user.id; row.status = "approved"; db.commit()
        send(chat_id, "Вход подтверждён. Вернитесь в браузер — он откроет ваш аккаунт автоматически.", site_buttons()); return
    with SessionLocal() as db:
        ctx = account(db, person)
        if command in ("/demo", "demo"):
            batch = demo(ctx); db.commit()
            send(chat_id, "Проверка запущена: 2 правила × 3 повтора. Сравниваем оплату закрытий с оплатой решённых проблем.\n\nЭто бесплатные сценарные участники, обращения к ИИ нет. Результат появится на сайте; /status покажет ход выполнения.", site_buttons(f"/experiments/{batch.id}")); return
        if command in ("/status", "/runs"):
            batches = db.scalars(select(ExperimentBatch).where(ExperimentBatch.workspace_id.in_(ctx.workspace_ids)).order_by(ExperimentBatch.created_at.desc()).limit(5)).all()
            labels = {"completed":"завершена", "running":"выполняется", "queued":"в очереди", "failed":"ошибка", "canceled":"остановлена"}
            # Project restrictions are checked just as for the website.
            visible = []
            for batch in batches:
                try: ctx.require_project(batch.project_id)
                except Exception: continue
                visible.append(batch)
            db.commit()
            send(chat_id, "Последние проверки:\n" + "\n".join(f"• {b.title}: {labels.get(b.status,b.status)}" for b in visible) if visible else "Проверок пока нет. Запустите /demo.", site_buttons(f"/experiments/{visible[0].id}" if visible else "/")); return
        if command == "/projects":
            rows = db.scalars(select(Project).where(Project.workspace_id.in_(ctx.workspace_ids), Project.archived_at.is_(None)).order_by(Project.created_at.desc()).limit(20)).all()
            names=[]
            for p in rows:
                try: ctx.require_project(p.id)
                except Exception: continue
                names.append(p.name)
            db.commit(); send(chat_id, "Ваши проекты:\n" + "\n".join(f"• {n}" for n in names) if names else "Проектов пока нет. /demo создаст первый пример.", site_buttons()); return
        db.commit()
    send(chat_id, "Chobra проверяет, не поощряет ли награда вредное поведение.\n\n/demo — бесплатный пример\n/status — последние проверки\n/projects — ваши проекты\n/login — открыть сайт и войти по QR\n/help — эта инструкция\n\nДля входа откройте сайт, отсканируйте QR-код и подтвердите совпадающий код здесь. Результаты относятся к симуляции, а не предсказывают поведение людей.", site_buttons())


def main():
    if not settings.telegram_bot_token:
        raise SystemExit("CHOBRA_TELEGRAM_BOT_TOKEN is required")
    logging.basicConfig(level=logging.INFO)
    # One poller across restarts/replicas. PostgreSQL releases the lock on connection loss.
    from .db import engine
    connection = engine.connect()
    if not connection.scalar(text("SELECT pg_try_advisory_lock(8917672112)")):
        connection.close()
        raise SystemExit("Telegram poller is already running")
    telegram_call("setMyCommands", {"commands": [{"command": c,"description":d} for c,d in [
        ("start","Начать"),("demo","Бесплатная проверка"),("status","Последние проверки"),("projects","Мои проекты"),("login","Войти на сайт"),("help","Как пользоваться")]]})
    log.info("Telegram bot started")
    while True:
        try:
            with SessionLocal() as db:
                cursor = db.get(BotCursor,"main")
                offset = cursor.update_id + 1 if cursor else 0
            updates = telegram_call("getUpdates", {"offset":offset,"timeout":25,"allowed_updates":["message","callback_query"]})
            for update in updates:
                process(update)
                with SessionLocal() as db:
                    cursor=db.get(BotCursor,"main")
                    if cursor: cursor.update_id=update["update_id"]
                    else: db.add(BotCursor(name="main",update_id=update["update_id"]))
                    db.commit()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            # URL and response bodies may contain a bot token or personal data.
            log.warning("Telegram update failed (%s)",type(exc).__name__)
            threading.Event().wait(3)
    connection.close()


if __name__ == "__main__":
    main()
