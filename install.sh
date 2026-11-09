#!/usr/bin/env bash
# Установка / обновление Cloudfront Bot на сервер (Ubuntu 22.04+/Debian 12+/CentOS/Alma/Rocky).
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/k9032431-cmd/Cloudfront_Bot/HEAD/install.sh)
#
# Без вопросов (всё через переменные):
#   BOT_TOKEN=123:ABC ADMIN_IDS=111111111 bash install.sh
#
# Переменные: REPO_URL, BRANCH, INSTALL_DIR, BOT_TOKEN, ADMIN_IDS
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/k9032431-cmd/Cloudfront_Bot.git}"
BRANCH="${BRANCH:-}"
INSTALL_DIR="${INSTALL_DIR:-/opt/cloudfront-bot}"
SERVICE="cloudfront-bot"
BOT_USER="cfbot"

c_green=$'\e[32m'; c_red=$'\e[31m'; c_yellow=$'\e[33m'; c_reset=$'\e[0m'
info() { echo "${c_green}==>${c_reset} $*"; }
warn() { echo "${c_yellow}!!${c_reset} $*"; }
die()  { echo "${c_red}ОШИБКА:${c_reset} $*" >&2; exit 1; }

ask() {  # ask "Вопрос" VAR — читает из терминала, даже если скрипт запущен через curl | bash
  local prompt="$1" __var="$2" reply=""
  if [[ -r /dev/tty ]]; then read -r -p "$prompt" reply </dev/tty || true; fi
  printf -v "$__var" '%s' "$reply"
}

[[ $EUID -eq 0 ]] || die "Запустите от root (sudo -i)."

# ---------- 1. Системные пакеты ----------
info "Устанавливаю системные пакеты…"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git python3 python3-venv python3-pip curl ca-certificates >/dev/null
elif command -v dnf >/dev/null; then
  dnf install -y -q git python3 python3-pip curl
elif command -v yum >/dev/null; then
  yum install -y -q git python3 python3-pip curl
else
  warn "Неизвестный пакетный менеджер — убедитесь, что установлены git и python3 (3.10+)."
fi

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Нужен Python 3.10+, а установлен $(python3 -V 2>&1). Используйте Ubuntu 22.04+ или Debian 12+."

# ---------- 2. Код ----------
if [[ -d "$INSTALL_DIR/.git" ]]; then
  info "Обновляю код в $INSTALL_DIR…"
  git -C "$INSTALL_DIR" pull --ff-only \
    || die "Не удалось обновить код. Проверьте: cd $INSTALL_DIR && git status"
else
  if [[ -e "$INSTALL_DIR" ]] && [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
    backup_dir="${INSTALL_DIR}.old-$(date +%Y%m%d-%H%M%S)"
    warn "Папка $INSTALL_DIR уже есть, но это не git-репозиторий — переношу её в $backup_dir"
    mv "$INSTALL_DIR" "$backup_dir"
  fi
  info "Скачиваю бота в $INSTALL_DIR…"
  git clone --depth 1 ${BRANCH:+-b "$BRANCH"} "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ---------- 3. Python-окружение ----------
info "Устанавливаю зависимости Python…"
[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# ---------- 4. Пользователь и папки ----------
id "$BOT_USER" >/dev/null 2>&1 || useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$BOT_USER"
mkdir -p data
chown -R "$BOT_USER:$BOT_USER" data
chmod 700 data

# ---------- 5. Настройки (.env) ----------
if [[ ! -f .env ]]; then
  info "Настройка бота"
  BOT_TOKEN="${BOT_TOKEN:-}"
  ADMIN_IDS="${ADMIN_IDS:-${ALLOWED_USERS:-}}"
  while [[ -z "$BOT_TOKEN" ]]; do ask "Токен бота от @BotFather: " BOT_TOKEN; done
  [[ -n "$ADMIN_IDS" ]] || ask "Telegram ID главного админа (ваш; Enter — узнать позже): " ADMIN_IDS
  ENC_KEY="$(.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  cp .env.example .env
  sed -i \
    -e "s|^BOT_TOKEN=.*|BOT_TOKEN=${BOT_TOKEN}|" \
    -e "s|^ADMIN_IDS=.*|ADMIN_IDS=${ADMIN_IDS// /}|" \
    -e "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${ENC_KEY}|" \
    .env
else
  info ".env уже существует — настройки не трогаю."
fi
chown "root:$BOT_USER" .env
chmod 640 .env

# ---------- 6. Команда управления ----------
chmod +x scripts/cfbot
ln -sf "$INSTALL_DIR/scripts/cfbot" /usr/local/bin/cfbot

# ---------- 7. Сервис systemd ----------
if ! command -v systemctl >/dev/null || [[ ! -d /run/systemd/system ]]; then
  warn "systemd не найден. Запуск вручную: cd $INSTALL_DIR && sudo -u $BOT_USER .venv/bin/python main.py"
  exit 0
fi

info "Создаю сервис $SERVICE…"
cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=Cloudfront Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
Group=$BOT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$INSTALL_DIR/data

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"
sleep 3

if systemctl is-active --quiet "$SERVICE"; then
  info "Готово! Бот запущен ✅"
else
  warn "Бот не запустился. Последние логи:"
  journalctl -u "$SERVICE" -n 30 --no-pager || true
  exit 1
fi

if grep -qE '^(ADMIN_IDS|ALLOWED_USERS)=[0-9]' .env; then :; else
  warn "Админ не задан: напишите боту /start, он покажет ваш ID, затем: cfbot config → ADMIN_IDS=ваш_ID"
fi

cat <<HELP

Управление ботом:
  cfbot status    — статус
  cfbot logs      — логи в реальном времени
  cfbot restart   — перезапуск
  cfbot update    — обновить бота из GitHub
  cfbot config    — изменить настройки (.env)
  cfbot modules   — список модулей
  cfbot backup    — резервная копия базы и настроек
  cfbot help      — все команды
HELP
