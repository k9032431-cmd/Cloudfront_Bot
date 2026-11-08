# Cloudfront Bot

Telegram-бот для создания и управления **AWS CloudFront** с поддержкой **нескольких AWS-аккаунтов**.

## Возможности

- 👥 **Аккаунты**: добавить любое количество AWS-аккаунтов (по Access Key / Secret Key), переключаться между ними, удалять.
  Ключи проверяются через AWS STS и хранятся в базе **в зашифрованном виде**; сообщение с секретом бот сразу удаляет из чата.
- ☁️ **Создать CloudFront**: указываете домен сервера (origin) → выбираете протокол (HTTP / HTTPS / Match viewer) и кэширование → бот создаёт дистрибуцию и присылает `xxxx.cloudfront.net`.
- 📋 **Мои CloudFront**: список дистрибуций активного аккаунта, статус, включение/выключение, удаление.
- 🔒 Доступ только для Telegram ID из `ALLOWED_USERS`.

## Запуск

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # заполните BOT_TOKEN и ALLOWED_USERS
python main.py
```

Не знаете свой Telegram ID? Запустите бота с пустым `ALLOWED_USERS` и напишите ему `/start` — он покажет ID.

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
main.py               — запуск бота
bot/config.py         — настройки из .env
bot/storage.py        — SQLite + шифрование ключей
bot/aws_service.py    — работа с AWS (STS, CloudFront)
bot/handlers.py       — меню и диалоги
bot/keyboards.py      — кнопки
bot/middleware.py     — ограничение доступа
```
