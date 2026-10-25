# Chobra

Проверка правил награды в симуляции: участники выбирают действия, движок отдельно считает премию и реальный результат, аудит сохраняет найденные нарушения.

**Сайт:** https://s2.loloblako.online
**Telegram:** https://t.me/chobraAI

## Начать пользоваться

1. Откройте сайт и отсканируйте QR-код.
2. В @chobraAI нажмите «Старт», сверьте код и подтвердите вход.
3. Создайте проект SupportDesk, откройте «Проверить правила» и выберите два правила.
4. Нажмите «Проверить правила». Бесплатный режим использует сценарных участников.
5. Откройте сравнение, отдельный запуск, нарушение и отчёт.

В боте `/demo` запускает готовый пример, `/status` показывает ход последних проверок, `/projects` — ваши проекты.

- [Подробная инструкция](docs/guides/USER_GUIDE_RU.md)
- [Как устроен проект простыми словами](docs/guides/HOW_IT_WORKS_RU.md)
- [Техническое задание](docs/spec/Chobra_Full_Technical_Specification.md)
- [Проверки и состояние поставки](docs/guides/RELEASE_CHECKS.md)

## Что используется

Next.js / React / TypeScript; Python / FastAPI / SQLAlchemy; PostgreSQL с изоляцией рабочих пространств; очередь заданий PostgreSQL; отдельный worker; Telegram Bot API; Docker. PDF формируется Chromium.

Среды: SupportDesk, TaskBoard, ResourceCommons. Профили: кооперативный, поиск награды, поиск лазеек. Участники могут принимать решения программной стратегией либо через адаптер Anthropic. Действующий ключ и доступность модели проверяются отдельно; демонстрация не вызывает платный ИИ.

## Локальный запуск

Нужны Python 3.12+, Node.js 22+ и npm. Команды выполняются из корня репозитория.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
(cd infra/localdb && npm ci)
(cd apps/web && npm ci)
cp .env.example .env.local
bash scripts/dev-api.sh
```

В другом терминале:

```bash
cd apps/web
npm run dev
```

Откройте http://localhost:3100. В локальном режиме доступна раскрываемая форма тестового входа. `dev-api.sh` поднимает локальную базу, применяет миграции и запускает встроенный worker. Локальный PostgreSQL слушает только 127.0.0.1:54329.

Для Telegram заполните `CHOBRA_TELEGRAM_BOT_TOKEN` в игнорируемом `.env.local`. Запускайте только один poller данного бота; не запускайте одновременно локальную и серверную копии с одним токеном. Рабочая серверная копия уже обслуживает @chobraAI.

```bash
set -a
source .env.local
set +a
source scripts/env.sh
.venv/bin/python -m chobra_api.telegram_bot
```

QR открывает Telegram, поэтому подтверждение входа на компьютере работает и без публичного адреса локальной машины. Кнопки перехода из бота на сайт требуют доступного HTTPS-адреса.

## Проверки

```bash
source scripts/env.sh
.venv/bin/python -m pytest
(cd apps/web && npm run typecheck && npm run build)
```

API-тесты пересоздают только базу с именем, оканчивающимся на `_test`; рабочую базу использовать нельзя.

Браузерные тесты требуют запущенные сайт, API и worker. При необходимости установите браузер через `npx playwright install chromium` или задайте `CHOBRA_CHROME` абсолютным путём.

```bash
cd apps/web
CHOBRA_E2E_REAL=1 npm run e2e
```

Часть браузерных проверок использует фиксированные ответы для пограничных состояний; отдельный `real-flow.spec.ts` проходит создание серии, аудит, сравнение и скачивание отчёта через настоящий локальный API.

## Размещение

Файлы находятся в `infra/compose.production.yml`, `infra/Dockerfile.api` и `infra/Dockerfile.web`. Секреты передаются через `.env.deploy`, который не должен попадать в Git или образ. Production использует `CHOBRA_AUTH_MODE=telegram`, защищённые cookie и HTTPS. Не публикуйте вход разработки.

На существующем сервере с Nginx сайт опубликован на loopback-порту 3101; Nginx завершает HTTPS и перенаправляет запросы к web. Службы обновляются так:

```bash
docker compose --env-file .env.deploy \
  -f infra/compose.production.yml -f infra/compose.host-port.yml \
  up -d --build --wait api worker bot web
```

Перед обновлением делайте резервную копию исходников, `.env.deploy`, PostgreSQL и хранилища отчётов. Для самостоятельного размещения без существующего прокси в compose также предусмотрен Caddy; не запускайте его на портах уже работающего Nginx.

## Границы выводов

Найденная лазейка относится к заданному виртуальному миру. Отсутствие находок не доказывает отсутствие всех возможных нарушений и не предсказывает поведение конкретных людей. ИИ выбирает действие; код проверяет последствия.
