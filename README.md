# Cloudfront Bot

Telegram-бот для создания и управления **AWS CloudFront** с поддержкой **нескольких AWS-аккаунтов**.

## Возможности

- 👥 **Аккаунты**: добавить любое количество AWS-аккаунтов (по Access Key / Secret Key), переключаться между ними, удалять.
  Ключи проверяются через AWS STS и хранятся в базе **в зашифрованном виде**; сообщение с секретом бот сразу удаляет из чата.
- ☁️ **Создать CloudFront**: указываете домен сервера (origin) → выбираете протокол (HTTP / HTTPS / Match viewer) и кэширование → бот создаёт дистрибуцию и присылает `xxxx.cloudfront.net`.
- 📋 **Мои CloudFront**: список дистрибуций активного аккаунта, статус, включение/выключение, удаление.
- 🔒 Доступ только для Telegram ID из `ALLOWED_USERS`.

## Установка на сервер одной командой

На чистом VPS (Ubuntu 22.04+ / Debian 12+ / Alma / Rocky), от root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/k9032431-cmd/Cloudfront_Bot/HEAD/install.sh)
```

Скрипт спросит токен бота и ваш Telegram ID, затем сам: установит Python и зависимости,
скачает бота в `/opt/cloudfront-bot`, сгенерирует ключ шифрования, создаст сервис systemd
(автозапуск после перезагрузки и перезапуск при падении) и запустит бота.

Без вопросов: `BOT_TOKEN=123:ABC ALLOWED_USERS=111111111 bash <(curl -fsSL …/install.sh)`

> Если репозиторий приватный — `curl` не скачает скрипт. Тогда:
> `git clone https://github.com/k9032431-cmd/Cloudfront_Bot.git /opt/cloudfront-bot && bash /opt/cloudfront-bot/install.sh`
> (git спросит логин и токен GitHub). Сделать репозиторий публичным тоже безопасно: ключи хранятся только на сервере.

Повторный запуск `install.sh` = обновление (настройки и база сохраняются).

### Управление — команда `cfbot`

| Команда | Что делает |
|---|---|
| `cfbot status` | статус бота |
| `cfbot logs` | логи в реальном времени |
| `cfbot restart` / `start` / `stop` | перезапуск / запуск / остановка |
| `cfbot update` | обновить бота из GitHub и перезапустить |
| `cfbot config` | отредактировать `.env` и перезапустить |
| `cfbot modules` | список модулей (добавок) |
| `cfbot new-module <имя>` | создать новый модуль из шаблона |
| `cfbot backup` | архив базы и настроек в `/root` |
| `cfbot uninstall` | удалить сервис |

Не знаете свой Telegram ID? Оставьте его пустым при установке и напишите боту `/start` — он покажет ID.
Потом `cfbot config` → впишите в `ALLOWED_USERS`.

### Локальный запуск (для разработки)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # заполните BOT_TOKEN и ALLOWED_USERS
python main.py
```

## Как добавить новую функцию (модуль)

Каждая функция бота — отдельный файл в `bot/modules/`. Бот сам находит модули при запуске:
кнопка появляется в главном меню, команда — в меню Telegram, описание — в «ℹ️ Помощь».

1. `cfbot new-module my_feature` (или скопируйте `bot/modules/_template.py` → `bot/modules/my_feature.py`)
2. В файле поменяйте кнопку (`MENU`), команды (`COMMANDS`), описание (`HELP`) и напишите обработчики.
3. `cfbot restart`

Минимальный модуль:

```python
from aiogram import F, Router
from aiogram.types import Message
from ..storage import Storage

MENU = ["🧩 Моя кнопка"]
HELP = "<b>🧩 Моя кнопка</b> — что она делает."
router = Router(name=__name__)

@router.message(F.text == "🧩 Моя кнопка")
async def handler(message: Message, storage: Storage):
    acc = storage.get_active(message.from_user.id)   # текущий AWS-аккаунт
    await message.answer(f"Аккаунт: {acc.name if acc else 'нет'}")
```

- Нажатие любой кнопки меню автоматически прерывает незаконченный диалог — об этом заботиться не нужно.
- Функции AWS — в `bot/aws_service.py` (там же удобно добавлять новые: Route 53, EC2 и т.д.).
- Выключить модуль без удаления: `DISABLED_MODULES=имя` в `.env`.
- Файлы, начинающиеся с `_`, не загружаются.

## Как получить ключи AWS

1. AWS Console → **IAM** → **Users** → **Create user**.
2. Прикрепите политику (минимально необходимая):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "cloudfront:CreateDistribution",
      "cloudfront:GetDistribution",
      "cloudfront:GetDistributionConfig",
      "cloudfront:UpdateDistribution",
      "cloudfront:DeleteDistribution",
      "cloudfront:ListDistributions"
    ],
    "Resource": "*"
  }]
}
```

   (или просто `CloudFrontFullAccess`).
3. Пользователь → **Security credentials** → **Create access key** → скопируйте *Access Key ID* и *Secret Access Key* и добавьте их в бота.

## Настройки создаваемой дистрибуции

| Параметр | Значение |
|---|---|
| Origin | ваш домен (IP не поддерживается CloudFront) |
| Protocol к origin | на выбор: `http-only` / `https-only` / `match-viewer` |
| Viewer protocol | `allow-all` (HTTP и HTTPS) |
| Методы | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| Cache policy | `CachingDisabled` или `CachingOptimized` |
| Origin request policy | `AllViewer` (все заголовки/куки/параметры передаются на сервер) |
| HTTP | HTTP/2 + HTTP/3, IPv6 включён |

Параметры легко поменять в `bot/aws_service.py` → `_create_distribution`.

## Структура

```
install.sh                — установка/обновление на сервер
scripts/cfbot             — команда управления
main.py                   — запуск бота, подключение модулей
bot/config.py             — настройки из .env
bot/storage.py            — SQLite + шифрование ключей
bot/aws_service.py        — работа с AWS (STS, CloudFront)
bot/registry.py           — автозагрузка модулей
bot/ui.py                 — главное меню и общие кнопки
bot/middleware.py         — доступ по ID, сброс диалога кнопками меню
bot/modules/core.py       — /start, /help, /cancel
bot/modules/accounts.py   — 👥 Аккаунты
bot/modules/cloudfront.py — ☁️ Создать / 📋 Мои CloudFront
bot/modules/_template.py  — шаблон нового модуля
```
