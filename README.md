# Cloudfront Bot

Telegram-бот для создания и управления **AWS CloudFront** и доменами в **Cloudflare**, с поддержкой нескольких аккаунтов.

## Возможности

- 👥 **Аккаунты**: добавить любое количество AWS-аккаунтов (по Access Key / Secret Key), переключаться между ними, удалять.
  Ключи проверяются через AWS STS и хранятся в базе **в зашифрованном виде**; сообщение с секретом бот сразу удаляет из чата.
- ☁️ **Создать CloudFront**: название → домен сервера → (при желании «✏️ Изменить настройки») → «Создать». Бот присылает `xxxx.cloudfront.net`, а когда дистрибуция развернётся — пишет отдельно.
- ⚙️ **Настройки**: схема по умолчанию для новых CloudFront — Origin protocol, Cache policy, Origin request policy, Viewer protocol, HTTP-версии (вкл. HTTP/3), методы, IPv6, Price class. Сохраняется для каждого пользователя.
- ✏️ Настройки **уже созданного** CloudFront можно поменять из его карточки в «📋 Мои CloudFront».
- 📋 **Мои CloudFront**: список дистрибуций активного аккаунта, статус, включение/выключение, удаление.
- 🟠 **Cloudflare**: несколько аккаунтов Cloudflare (API Token или Global API Key); домены — добавить (сразу несколько), удалить, статус и NS; DNS-записи A/AAAA/CNAME/TXT/MX/NS — добавить, изменить, удалить, прокси 🟠/⚪, TTL; SSL-режим, Always HTTPS, Under Attack, Development mode, очистка кэша.
- 👑 **Пользователи** (только главный админ): выдать доступ по Telegram ID, забрать доступ. Когда незнакомый человек пишет боту, админу приходит запрос с кнопкой «✅ Дать доступ». У каждого пользователя свои AWS-аккаунты и настройки.

## Установка на сервер одной командой

На чистом VPS (Ubuntu 22.04+ / Debian 12+ / Alma / Rocky), от root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/k9032431-cmd/Cloudfront_Bot/HEAD/install.sh)
```

Скрипт спросит токен бота и ваш Telegram ID, затем сам: установит Python и зависимости,
скачает бота в `/opt/cloudfront-bot`, сгенерирует ключ шифрования, создаст сервис systemd
(автозапуск после перезагрузки и перезапуск при падении) и запустит бота.

Без вопросов: `BOT_TOKEN=123:ABC ADMIN_IDS=111111111 bash <(curl -fsSL …/install.sh)`

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
Потом `cfbot config` → впишите в `ADMIN_IDS`.

### Доступ пользователей

- **Главный админ** — Telegram ID в `ADMIN_IDS` в `.env` (можно несколько через запятую). Старое имя `ALLOWED_USERS` тоже работает.
- Остальным доступ выдаёт админ прямо в боте: **👑 Пользователи → ➕ Дать доступ** → отправить ID (можно несколько через запятую).
- Или проще: человек пишет боту `/start` → видит свой ID, а админу приходит запрос с кнопками **✅ Дать доступ / ❌ Отклонить**.
- Забрать доступ: **👑 Пользователи** → пользователь → **🚫 Забрать доступ**. Его AWS-аккаунты сохраняются и вернутся, если снова дать доступ.

### Локальный запуск (для разработки)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # заполните BOT_TOKEN и ADMIN_IDS
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
- `ADMIN_ONLY = True` в модуле — кнопка видна и работает только у админов.

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
      "cloudfront:ListDistributions",
      "cloudfront:TagResource"
    ],
    "Resource": "*"
  }]
}
```

   (или просто `CloudFrontFullAccess`).
3. Пользователь → **Security credentials** → **Create access key** → скопируйте *Access Key ID* и *Secret Access Key* и добавьте их в бота.

## Cloudflare

**🟠 Cloudflare → 👤 Аккаунты Cloudflare → ➕ Добавить** → название → API Token (или Global API Key, затем email).

Создать API Token: dash.cloudflare.com → **My Profile → API Tokens → Create Token → Create Custom Token**:

| Раздел | Право |
|---|---|
| Zone → Zone | Edit |
| Zone → DNS | Edit |
| Zone → Zone Settings | Edit |
| Zone → Cache Purge | Purge |
| Account → Account Settings | Read |

Zone Resources: **All zones**, Account Resources: **All accounts**.
Право *Account Settings: Read* не обязательно: без него бот при добавлении первого домена попросит Account ID
(32 символа из адресной строки `dash.cloudflare.com/<ID>/home`). (Global API Key — My Profile → API Tokens → Global API Key; даёт полный доступ.)

Что можно делать:
- **Домены**: список, добавить (можно несколько сразу — бот покажет NS для регистратора), проверить NS, удалить.
- **DNS**: A, AAAA, CNAME, TXT, MX, NS — добавить, изменить значение, включить/выключить прокси 🟠, TTL, удалить.
  Удобно для CloudFront: CNAME `cdn` → `xxxx.cloudfront.net`.
- **Настройки домена**: SSL/TLS (Off/Flexible/Full/Full strict), Always Use HTTPS, Under Attack, Development mode, очистка кэша.

## Настройки CloudFront

Настройки можно менять в трёх местах:

1. **⚙️ Настройки** — шаблон для всех новых CloudFront (сохраняется сразу, «♻️ Сбросить» — вернуть схему ниже).
2. **Перед созданием** — «✏️ Изменить настройки» на экране подтверждения (только для этой дистрибуции).
3. **После создания** — «✏️ Настройки» в карточке дистрибуции → «💾 Применить» (обновляется в AWS, 5–15 мин).

Схема по умолчанию (как в инструкции):

| Шаг в консоли | Значение |
|---|---|
| Distribution name | название, которое вы вводите (тег `Name` + комментарий) |
| Origin type → Other → Custom origin | ваш домен (IP CloudFront не принимает) |
| Protocol | **HTTP only** |
| Cache policy | **CachingDisabled** |
| Origin request policy | **AllViewer** |
| Viewer protocol policy | Redirect HTTP to HTTPS |
| HTTP versions | **HTTP/2 + HTTP/3** |
| Allowed methods | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| IPv6 / Price class | включён / все локации |

> Тарифный план «Free» из консоли через API выбрать нельзя — дистрибуция создаётся с обычной оплатой по факту
> (pay-as-you-go), на которую действует бесплатный лимит AWS: 1 ТБ трафика и 10 млн запросов в месяц.

Поменять схему по умолчанию или добавить новую настройку — `bot/cf_settings.py` (`DEFAULTS`, `SETTINGS`).

## Структура

```
install.sh                — установка/обновление на сервер
scripts/cfbot             — команда управления
main.py                   — запуск бота, подключение модулей
bot/config.py             — настройки из .env
bot/storage.py            — SQLite + шифрование ключей
bot/aws_service.py        — работа с AWS (STS, CloudFront)
bot/cf_settings.py        — настройки CloudFront: схема по умолчанию и варианты
bot/cloudflare/api.py     — клиент Cloudflare API
bot/cloudflare/store.py   — аккаунты Cloudflare (зашифрованы)
bot/registry.py           — автозагрузка модулей
bot/ui.py                 — главное меню и общие кнопки
bot/middleware.py         — доступ (админы + выданный доступ), запросы доступа, сброс диалога
bot/filters.py            — фильтр IsAdmin
bot/modules/core.py       — /start, /help, /cancel
bot/modules/accounts.py   — 👥 Аккаунты
bot/modules/admin.py      — 👑 Пользователи (только админ)
bot/modules/cloudflare.py — 🟠 Cloudflare: аккаунты, домены, DNS, настройки
bot/modules/cloudfront.py — ☁️ Создать / 📋 Мои CloudFront / ⚙️ Настройки
bot/modules/_template.py  — шаблон нового модуля
```
