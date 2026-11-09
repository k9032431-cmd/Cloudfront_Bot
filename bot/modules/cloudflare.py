"""🟠 Cloudflare — аккаунты, домены (зоны), DNS-записи и основные настройки домена."""
import ipaddress
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..cloudflare.api import CfError
from ..cloudflare.store import CfAccount, CloudflareStore
from ..ui import cancel_menu, esc, main_menu

BTN_CF = "🟠 Cloudflare"

ORDER = 20
MENU = [BTN_CF]
COMMANDS = [("cloudflare", "Cloudflare: домены и DNS")]
HELP = (
    "<b>🟠 Cloudflare</b> — добавьте аккаунт Cloudflare (API Token или Global API Key) и управляйте "
    "доменами: добавить/удалить домен, DNS-записи (A, AAAA, CNAME, TXT, MX, NS), прокси 🟠/⚪, TTL, "
    "SSL-режим, Always HTTPS, Under Attack, Development mode, очистка кэша."
)

router = Router(name="cloudflare")


def setup(dp, storage, config) -> None:
    dp["cf_store"] = CloudflareStore(storage)


# ---------- Callback data ----------
# В кнопку Telegram помещается только 64 байта, поэтому действия — короткие,
# зона — полный ID (32 символа), запись — первые 12 символов ID.

class CfAccCb(CallbackData, prefix="cfa"):
    a: str                      # list | open | select | del | del_y | add
    id: int | None = None


class CfCb(CallbackData, prefix="cf"):
    a: str
    z: str | None = None        # zone id
    r: str | None = None        # record id prefix / имя настройки
    v: str | None = None        # значение / номер страницы


class AddCfAccount(StatesGroup):
    name = State()
    secret = State()
    email = State()


class AddZone(StatesGroup):
    domain = State()


class AddRecord(StatesGroup):
    name = State()
    content = State()
    priority = State()
    proxied = State()


class EditRecord(StatesGroup):
    content = State()


REC_TYPES = ["A", "AAAA", "CNAME", "TXT", "MX", "NS"]
PROXIABLE = {"A", "AAAA", "CNAME"}
TTL_OPTIONS = [(1, "Auto"), (60, "1 мин"), (300, "5 мин"), (3600, "1 час"), (86400, "1 день")]
SSL_MODES = [("off", "Off"), ("flexible", "Flexible"), ("full", "Full"), ("strict", "Full (strict)")]
GLOBAL_KEY_RE = re.compile(r"^[0-9a-f]{37}$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$")
PER_PAGE = 20


# ---------- Утилиты ----------

async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


def _short_name(name: str, zone: str) -> str:
    if name == zone:
        return "@"
    return name[: -len(zone) - 1] if name.endswith("." + zone) else name


def _ttl_label(ttl: int) -> str:
    return dict(TTL_OPTIONS).get(ttl, f"{ttl} с")


def _onoff(v) -> str:
    return "вкл ✅" if v in ("on", True) else "выкл"


def _no_account_text() -> str:
    return "Сначала добавьте аккаунт Cloudflare: «👤 Аккаунты Cloudflare» → «➕ Добавить»."


# ---------- Главный экран ----------

def _home(cf_store: CloudflareStore, user_id: int):
    acc = cf_store.get_active(user_id)
    kb = InlineKeyboardBuilder()
    if acc:
        text = (f"🟠 <b>Cloudflare</b>\n\nАккаунт: <b>{esc(acc.name)}</b>"
                + (f" ({esc(acc.cf_account_name)})" if acc.cf_account_name else ""))
        kb.button(text="🌐 Мои домены", callback_data=CfCb(a="zones", v="1"))
        kb.button(text="➕ Добавить домен", callback_data=CfCb(a="zadd"))
    else:
        text = "🟠 <b>Cloudflare</b>\n\n" + _no_account_text()
    kb.button(text="👤 Аккаунты Cloudflare", callback_data=CfAccCb(a="list"))
    kb.adjust(1)
    return text, kb.as_markup()


@router.message(Command("cloudflare"))
@router.message(F.text == BTN_CF)
async def cf_menu(message: Message, state: FSMContext, cf_store: CloudflareStore):
    await state.clear()
    text, kb = _home(cf_store, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(CfCb.filter(F.a == "home"))
async def cf_home(cb: CallbackQuery, cf_store: CloudflareStore):
    text, kb = _home(cf_store, cb.from_user.id)
    await _edit(cb, text, kb)
    await cb.answer()


# ---------- Аккаунты Cloudflare ----------

def _accounts_view(cf_store: CloudflareStore, user_id: int):
    accounts = cf_store.list(user_id)
    active = cf_store.get_active(user_id)
    kb = InlineKeyboardBuilder()
    for a in accounts:
        mark = "✅ " if active and a.id == active.id else "▫️ "
        kb.button(text=f"{mark}{a.name}", callback_data=CfAccCb(a="open", id=a.id))
    kb.button(text="➕ Добавить аккаунт Cloudflare", callback_data=CfAccCb(a="add"))
    kb.button(text="⬅️ Назад", callback_data=CfCb(a="home"))
    kb.adjust(1)
    text = (f"👤 <b>Аккаунты Cloudflare</b> ({len(accounts)})\nНажмите на аккаунт, чтобы переключиться или удалить."
            if accounts else "👤 <b>Аккаунты Cloudflare</b>\n\nПока нет ни одного.")
    return text, kb.as_markup()


@router.callback_query(CfAccCb.filter())
async def cf_accounts(cb: CallbackQuery, callback_data: CfAccCb, state: FSMContext, cf_store: CloudflareStore):
    uid, a = cb.from_user.id, callback_data.a
    if a == "add":
        await state.set_state(AddCfAccount.name)
        await cb.message.answer("Введите название аккаунта Cloudflare (например: <i>Основной</i>):",
                                reply_markup=cancel_menu())
        await cb.answer()
        return
    if a in ("open", "select", "del", "del_y"):
        acc = cf_store.get(uid, callback_data.id)
        if not acc:
            await cb.answer("Аккаунт не найден", show_alert=True)
            return
        if a == "select":
            cf_store.set_active(uid, acc.id)
            await cb.answer(f"Активный: {acc.name}")
            text, kb = _home(cf_store, uid)
            await _edit(cb, text, kb)
            return
        if a == "del":
            kb = InlineKeyboardBuilder()
            kb.button(text="Да, удалить", callback_data=CfAccCb(a="del_y", id=acc.id))
            kb.button(text="Нет", callback_data=CfAccCb(a="open", id=acc.id))
            await _edit(cb, f"Удалить аккаунт <b>{esc(acc.name)}</b> из бота?\n(В Cloudflare ничего не удаляется.)",
                        kb.as_markup())
            await cb.answer()
            return
        if a == "del_y":
            cf_store.delete(uid, acc.id)
            await cb.answer("Удалено")
            text, kb = _accounts_view(cf_store, uid)
            await _edit(cb, text, kb)
            return
        active = cf_store.get_active(uid)
        is_active = bool(active and active.id == acc.id)
        kb = InlineKeyboardBuilder()
        if not is_active:
            kb.button(text="✅ Сделать активным", callback_data=CfAccCb(a="select", id=acc.id))
        kb.button(text="🗑 Удалить", callback_data=CfAccCb(a="del", id=acc.id))
        kb.button(text="⬅️ Назад", callback_data=CfAccCb(a="list"))
        kb.adjust(1)
        await _edit(cb, (
            f"<b>{esc(acc.name)}</b>{' ✅ (активный)' if is_active else ''}\n\n"
            f"Вход: {acc.auth_kind}" + (f" ({esc(acc.email)})" if acc.email else "") + "\n"
            f"Cloudflare account: {esc(acc.cf_account_name) or '-'} <code>{acc.cf_account_id or '-'}</code>"
        ), kb.as_markup())
        await cb.answer()
        return
    text, kb = _accounts_view(cf_store, uid)
    await _edit(cb, text, kb)
    await cb.answer()


@router.message(AddCfAccount.name, F.text)
async def cf_acc_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:64])
    await state.set_state(AddCfAccount.secret)
    await message.answer(
        "Отправьте <b>API Token</b> Cloudflare (рекомендуется) или <b>Global API Key</b>.\n"
        "Сообщение с ключом будет сразу удалено из чата.\n\n"
        "Как создать токен: dash.cloudflare.com → My Profile → API Tokens → Create Token → "
        "Create Custom Token. Права:\n"
        "• Zone → Zone → Edit\n• Zone → DNS → Edit\n• Zone → Zone Settings → Edit\n"
        "• Zone → Cache Purge → Purge\n• Account → Account Settings → Read\n"
        "Zone Resources: All zones. Account Resources: All accounts."
    )


@router.message(AddCfAccount.secret, F.text)
async def cf_acc_secret(message: Message, state: FSMContext, cf_store: CloudflareStore):
    secret = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass
    if GLOBAL_KEY_RE.match(secret):
        await state.update_data(secret=secret)
        await state.set_state(AddCfAccount.email)
        await message.answer("Это Global API Key. Теперь отправьте <b>email</b> аккаунта Cloudflare:")
        return
    await _save_cf_account(message, state, cf_store, secret, "")


@router.message(AddCfAccount.email, F.text)
async def cf_acc_email(message: Message, state: FSMContext, cf_store: CloudflareStore):
    email = message.text.strip()
    if "@" not in email:
        await message.answer("Это не похоже на email. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    await _save_cf_account(message, state, cf_store, data["secret"], email)


async def _save_cf_account(message: Message, state: FSMContext, cf_store: CloudflareStore, secret: str, email: str):
    data = await state.get_data()
    wait = await message.answer("⏳ Проверяю доступ к Cloudflare…")
    probe = CfAccount(0, message.from_user.id, data["name"], email, secret, "", "")
    try:
        cf_id, cf_name = await probe.api().verify()
    except CfError as e:
        await state.set_state(AddCfAccount.secret)
        await wait.edit_text(f"❌ Cloudflare не принял ключ:\n<code>{esc(e)}</code>\n\n"
                             "Отправьте ключ ещё раз или /cancel.")
        return
    cf_store.add(message.from_user.id, data["name"], email, secret, cf_id, cf_name)
    await state.clear()
    await wait.edit_text(f"✅ Аккаунт Cloudflare <b>{esc(data['name'])}</b> добавлен"
                         + (f" ({esc(cf_name)})" if cf_name else "") + ".")
    text, kb = _home(cf_store, message.from_user.id)
    await message.answer("Главное меню", reply_markup=main_menu())
    await message.answer(text, reply_markup=kb)


# ---------- Домены ----------

async def _zones_view(acc: CfAccount, page: int):
    p = await acc.api().list_zones(page=page, per_page=PER_PAGE)
    kb = InlineKeyboardBuilder()
    for z in p.items:
        icon = "🟢" if z["status"] == "active" else ("⏸" if z.get("paused") else "⏳")
        kb.button(text=f"{icon} {z['name']}", callback_data=CfCb(a="zone", z=z["id"]))
    nav = []
    if p.page > 1:
        nav.append(("⬅️", CfCb(a="zones", v=str(p.page - 1))))
    if p.page < p.total_pages:
        nav.append(("➡️", CfCb(a="zones", v=str(p.page + 1))))
    for t, c in nav:
        kb.button(text=t, callback_data=c)
    kb.button(text="➕ Добавить домен", callback_data=CfCb(a="zadd"))
    kb.button(text="⬅️ Назад", callback_data=CfCb(a="home"))
    kb.adjust(*([1] * len(p.items)), *([len(nav)] if nav else []), 1, 1)
    text = (f"🌐 <b>Домены</b> — {esc(acc.name)}\nВсего: {p.total}"
            + (f", страница {p.page}/{p.total_pages}" if p.total_pages > 1 else "")
            + "\n🟢 активен · ⏳ ожидает смены NS · ⏸ на паузе")
    if not p.items:
        text = f"🌐 <b>Домены</b> — {esc(acc.name)}\n\nДоменов пока нет."
    return text, kb.as_markup()


async def _zone_view(acc: CfAccount, zone_id: str):
    api = acc.api()
    z = await api.get_zone(zone_id)
    try:
        st = await api.get_settings(zone_id)
    except CfError:
        st = {}
    status = z["status"]
    lines = [
        f"🌐 <b>{z['name']}</b>\n",
        f"Статус: {'🟢 активен' if status == 'active' else '⏳ ' + status}",
        f"Тариф: {esc((z.get('plan') or {}).get('name', '-'))}",
        "NS Cloudflare: " + ", ".join(f"<code>{n}</code>" for n in z.get("name_servers") or []),
    ]
    if status != "active":
        lines.append(
            "\n⚠️ Чтобы домен заработал, у регистратора домена замените NS-серверы на указанные выше "
            "(старые: " + (", ".join(z.get("original_name_servers") or []) or "-") + ")."
        )
    if st:
        lines.append(
            f"\nSSL: <b>{dict(SSL_MODES).get(st.get('ssl'), st.get('ssl'))}</b> · "
            f"Always HTTPS: {_onoff(st.get('always_use_https'))}\n"
            f"Under Attack: {_onoff(st.get('security_level') == 'under_attack')} · "
            f"Dev mode: {_onoff(st.get('development_mode'))}"
        )
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 DNS-записи", callback_data=CfCb(a="recs", z=zone_id, v="1"))
    if st:
        kb.button(text=f"🔒 SSL: {dict(SSL_MODES).get(st.get('ssl'), '?')}", callback_data=CfCb(a="ssl", z=zone_id))
        kb.button(text=f"↪️ Always HTTPS: {_onoff(st.get('always_use_https'))}",
                  callback_data=CfCb(a="set", z=zone_id, r="https",
                                     v="off" if st.get("always_use_https") == "on" else "on"))
        attack = st.get("security_level") == "under_attack"
        kb.button(text=f"🛡 Under Attack: {_onoff(attack)}",
                  callback_data=CfCb(a="set", z=zone_id, r="attack", v="off" if attack else "on"))
        kb.button(text=f"🧪 Dev mode: {_onoff(st.get('development_mode'))}",
                  callback_data=CfCb(a="set", z=zone_id, r="dev",
                                     v="off" if st.get("development_mode") == "on" else "on"))
    kb.button(text="🧹 Очистить весь кэш", callback_data=CfCb(a="purge", z=zone_id))
    if status != "active":
        kb.button(text="🔄 Проверить NS сейчас", callback_data=CfCb(a="zcheck", z=zone_id))
    kb.button(text="🔃 Обновить", callback_data=CfCb(a="zone", z=zone_id))
    kb.button(text="🗑 Удалить домен", callback_data=CfCb(a="zdel", z=zone_id))
    kb.button(text="⬅️ К доменам", callback_data=CfCb(a="zones", v="1"))
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


SETTING_MAP = {  # короткое имя в кнопке → (настройка Cloudflare, значение для on, для off)
    "https": ("always_use_https", "on", "off"),
    "attack": ("security_level", "under_attack", "medium"),
    "dev": ("development_mode", "on", "off"),
}


# ---------- DNS-записи ----------

async def _records_view(acc: CfAccount, zone_id: str, page: int):
    p = await acc.api().list_records(zone_id, page=page, per_page=PER_PAGE)
    zone_name = p.items[0]["zone_name"] if p.items else (await acc.api().get_zone(zone_id))["name"]
    kb = InlineKeyboardBuilder()
    for r in p.items:
        cloud = "🟠" if r.get("proxied") else "⚪"
        kb.button(text=f"{cloud} {r['type']} {_short_name(r['name'], zone_name)} → {r['content']}"[:60],
                  callback_data=CfCb(a="rec", z=zone_id, r=r["id"][:12]))
    nav = []
    if p.page > 1:
        nav.append(("⬅️", CfCb(a="recs", z=zone_id, v=str(p.page - 1))))
    if p.page < p.total_pages:
        nav.append(("➡️", CfCb(a="recs", z=zone_id, v=str(p.page + 1))))
    for t, c in nav:
        kb.button(text=t, callback_data=c)
    kb.button(text="➕ Добавить запись", callback_data=CfCb(a="radd", z=zone_id))
    kb.button(text="⬅️ К домену", callback_data=CfCb(a="zone", z=zone_id))
    kb.adjust(*([1] * len(p.items)), *([len(nav)] if nav else []), 1, 1)
    text = (f"📝 <b>DNS — {zone_name}</b>\nЗаписей: {p.total}"
            + (f", страница {p.page}/{p.total_pages}" if p.total_pages > 1 else "")
            + "\n🟠 через Cloudflare (proxied) · ⚪ только DNS")
    return text, kb.as_markup()


def _record_view(rec: dict, zone_id: str):
    short = rec["id"][:12]
    lines = [
        f"📝 <b>{rec['type']}</b> запись — {rec['zone_name']}\n",
        f"Имя: <code>{rec['name']}</code>",
        f"Значение: <code>{esc(rec['content'])}</code>",
    ]
    if rec["type"] == "MX":
        lines.append(f"Приоритет: {rec.get('priority')}")
    if rec.get("proxiable"):
        lines.append(f"Прокси: {'🟠 Proxied' if rec.get('proxied') else '⚪ DNS only'}")
    lines.append(f"TTL: {_ttl_label(rec.get('ttl', 1))}")
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить значение", callback_data=CfCb(a="redit", z=zone_id, r=short))
    if rec.get("proxiable"):
        kb.button(text="⚪ Сделать DNS only" if rec.get("proxied") else "🟠 Включить прокси",
                  callback_data=CfCb(a="rprox", z=zone_id, r=short))
    if not rec.get("proxied"):
        kb.button(text=f"⏱ TTL: {_ttl_label(rec.get('ttl', 1))}", callback_data=CfCb(a="rttl", z=zone_id, r=short))
    kb.button(text="🗑 Удалить запись", callback_data=CfCb(a="rdel", z=zone_id, r=short))
    kb.button(text="⬅️ К записям", callback_data=CfCb(a="recs", z=zone_id, v="1"))
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


async def _get_record(acc: CfAccount, zone_id: str, prefix: str) -> dict:
    rec = await acc.api().find_record(zone_id, prefix)
    if not rec:
        raise CfError("Запись не найдена (возможно, уже удалена)")
    return rec


def _validate_content(rtype: str, content: str) -> str | None:
    """Возвращает текст ошибки или None."""
    try:
        if rtype == "A":
            ipaddress.IPv4Address(content)
        elif rtype == "AAAA":
            ipaddress.IPv6Address(content)
    except ValueError:
        return f"Для записи {rtype} нужен IP-адрес {'IPv4 (например 1.2.3.4)' if rtype == 'A' else 'IPv6'}."
    if rtype in ("CNAME", "MX", "NS") and not DOMAIN_RE.match(content.lower().rstrip(".")):
        return f"Для записи {rtype} нужен домен, например <code>target.example.com</code>."
    return None


# ---------- Обработчик всех кнопок cf:* ----------

@router.callback_query(CfCb.filter())
async def cf_action(cb: CallbackQuery, callback_data: CfCb, state: FSMContext, cf_store: CloudflareStore):
    a, z, r, v = callback_data.a, callback_data.z, callback_data.r, callback_data.v
    acc = cf_store.get_active(cb.from_user.id)
    if not acc:
        await cb.answer(_no_account_text(), show_alert=True)
        return
    api = acc.api()
    try:
        if a == "zones":
            text, kb = await _zones_view(acc, int(v or 1))
            await _edit(cb, text, kb)
        elif a == "zone":
            text, kb = await _zone_view(acc, z)
            await _edit(cb, text, kb)
        elif a == "zadd":
            await state.set_state(AddZone.domain)
            await cb.message.answer(
                "Отправьте домен, который нужно добавить в Cloudflare, например <code>example.com</code>.\n"
                "Можно несколько — через пробел или с новой строки.",
                reply_markup=cancel_menu(),
            )
        elif a == "zcheck":
            await api.activation_check(z)
            await cb.answer("Проверка запущена — статус обновится в течение нескольких минут", show_alert=True)
            return
        elif a == "zdel":
            zone = await api.get_zone(z)
            kb = InlineKeyboardBuilder()
            kb.button(text="Да, удалить домен из Cloudflare", callback_data=CfCb(a="zdel_y", z=z))
            kb.button(text="Нет", callback_data=CfCb(a="zone", z=z))
            kb.adjust(1)
            await _edit(cb, f"⚠️ Удалить домен <b>{zone['name']}</b> из Cloudflare вместе со всеми DNS-записями?\n"
                            "Это необратимо.", kb.as_markup())
        elif a == "zdel_y":
            await api.delete_zone(z)
            await cb.answer("Домен удалён")
            text, kb = await _zones_view(acc, 1)
            await _edit(cb, text, kb)
            return
        elif a == "purge":
            kb = InlineKeyboardBuilder()
            kb.button(text="Да, очистить", callback_data=CfCb(a="purge_y", z=z))
            kb.button(text="Нет", callback_data=CfCb(a="zone", z=z))
            await _edit(cb, "Очистить весь кэш Cloudflare для этого домена?", kb.as_markup())
        elif a == "purge_y":
            await api.purge_cache(z)
            await cb.answer("Кэш очищен ✅", show_alert=True)
            text, kb = await _zone_view(acc, z)
            await _edit(cb, text, kb)
            return
        elif a == "ssl":
            st = await api.get_settings(z)
            kb = InlineKeyboardBuilder()
            for value, label in SSL_MODES:
                mark = "✅ " if st.get("ssl") == value else ""
                kb.button(text=f"{mark}{label}", callback_data=CfCb(a="sslset", z=z, v=value))
            kb.button(text="⬅️ Назад", callback_data=CfCb(a="zone", z=z))
            kb.adjust(1)
            await _edit(cb, "🔒 <b>Режим SSL/TLS</b>\n\n"
                            "Off — без HTTPS\nFlexible — HTTPS до Cloudflare, до сервера HTTP\n"
                            "Full — HTTPS до сервера (любой сертификат)\n"
                            "Full (strict) — HTTPS до сервера с валидным сертификатом", kb.as_markup())
        elif a == "sslset":
            await api.set_setting(z, "ssl", v)
            await cb.answer(f"SSL: {dict(SSL_MODES)[v]}")
            text, kb = await _zone_view(acc, z)
            await _edit(cb, text, kb)
            return
        elif a == "set":
            name, on, off = SETTING_MAP[r]
            await api.set_setting(z, name, on if v == "on" else off)
            await cb.answer("Готово")
            text, kb = await _zone_view(acc, z)
            await _edit(cb, text, kb)
            return
        elif a == "recs":
            text, kb = await _records_view(acc, z, int(v or 1))
            await _edit(cb, text, kb)
        elif a == "rec":
            text, kb = _record_view(await _get_record(acc, z, r), z)
            await _edit(cb, text, kb)
        elif a == "radd":
            kb = InlineKeyboardBuilder()
            for t in REC_TYPES:
                kb.button(text=t, callback_data=CfCb(a="rtype", z=z, v=t))
            kb.button(text="⬅️ Назад", callback_data=CfCb(a="recs", z=z, v="1"))
            kb.adjust(3, 3, 1)
            await _edit(cb, "➕ <b>Новая DNS-запись</b>\nВыберите тип:", kb.as_markup())
        elif a == "rtype":
            zone = await api.get_zone(z)
            await state.set_state(AddRecord.name)
            await state.update_data(zone_id=z, zone_name=zone["name"], rtype=v)
            await cb.message.answer(
                f"Запись <b>{v}</b> в <b>{zone['name']}</b>\n\n"
                f"Введите <b>имя</b>: <code>@</code> — сам домен, <code>www</code> → www.{zone['name']}, "
                "или полное имя.",
                reply_markup=cancel_menu(),
            )
        elif a == "rprox":
            rec = await _get_record(acc, z, r)
            rec = await api.update_record(z, rec["id"], {"proxied": not rec.get("proxied")})
            await cb.answer("🟠 Прокси включён" if rec.get("proxied") else "⚪ Только DNS")
            text, kb = _record_view(rec, z)
            await _edit(cb, text, kb)
            return
        elif a == "rttl":
            rec = await _get_record(acc, z, r)
            kb = InlineKeyboardBuilder()
            for ttl, label in TTL_OPTIONS:
                mark = "✅ " if rec.get("ttl") == ttl else ""
                kb.button(text=f"{mark}{label}", callback_data=CfCb(a="rttlset", z=z, r=r, v=str(ttl)))
            kb.button(text="⬅️ Назад", callback_data=CfCb(a="rec", z=z, r=r))
            kb.adjust(1)
            await _edit(cb, "⏱ <b>TTL</b> записи:", kb.as_markup())
        elif a == "rttlset":
            rec = await _get_record(acc, z, r)
            rec = await api.update_record(z, rec["id"], {"ttl": int(v)})
            text, kb = _record_view(rec, z)
            await _edit(cb, text, kb)
        elif a == "redit":
            rec = await _get_record(acc, z, r)
            await state.set_state(EditRecord.content)
            await state.update_data(zone_id=z, record_id=rec["id"], rtype=rec["type"])
            await cb.message.answer(
                f"Текущее значение <code>{esc(rec['content'])}</code>\nОтправьте <b>новое значение</b>:",
                reply_markup=cancel_menu(),
            )
        elif a == "rdel":
            rec = await _get_record(acc, z, r)
            kb = InlineKeyboardBuilder()
            kb.button(text="Да, удалить", callback_data=CfCb(a="rdel_y", z=z, r=r))
            kb.button(text="Нет", callback_data=CfCb(a="rec", z=z, r=r))
            await _edit(cb, f"Удалить запись <b>{rec['type']}</b> <code>{rec['name']}</code> → "
                            f"<code>{esc(rec['content'])}</code>?", kb.as_markup())
        elif a == "rdel_y":
            rec = await _get_record(acc, z, r)
            await api.delete_record(z, rec["id"])
            await cb.answer("Запись удалена")
            text, kb = await _records_view(acc, z, 1)
            await _edit(cb, text, kb)
            return
        elif a == "rpx":  # выбор прокси при создании записи
            await _create_record(cb.message, state, cf_store, cb.from_user.id, proxied=(v == "on"))
        await cb.answer()
    except CfError as e:
        await cb.answer(f"Cloudflare: {e}"[:190], show_alert=True)


# ---------- Ввод текста: домены и записи ----------

@router.message(AddZone.domain, F.text)
async def zone_add(message: Message, state: FSMContext, cf_store: CloudflareStore):
    acc = cf_store.get_active(message.from_user.id)
    if not acc:
        await state.clear()
        await message.answer(_no_account_text(), reply_markup=main_menu())
        return
    domains = [re.sub(r"^https?://", "", d.strip().lower()).split("/")[0] for d in re.split(r"[\s,]+", message.text)]
    domains = [d for d in dict.fromkeys(domains) if d]
    bad = [d for d in domains if not DOMAIN_RE.match(d)]
    if bad or not domains:
        await message.answer("Некорректный домен: " + esc(", ".join(bad) or message.text) + "\nПопробуйте ещё раз:")
        return
    api = acc.api()
    if not acc.cf_account_id:
        try:
            cf_id, _ = await api.verify()
        except CfError:
            cf_id = ""
        if not cf_id:
            await message.answer("❌ Не удалось определить Cloudflare account ID. Добавьте токену право "
                                 "<b>Account → Account Settings → Read</b> и добавьте аккаунт заново.")
            return
        cf_store.update_cf_account_id(acc.id, cf_id)
        acc.cf_account_id = cf_id
    await state.clear()
    wait = await message.answer("⏳ Добавляю…")
    results, kb = [], InlineKeyboardBuilder()
    for d in domains:
        try:
            z = await api.create_zone(d, acc.cf_account_id)
            ns = "\n".join(f"   <code>{n}</code>" for n in z.get("name_servers") or [])
            results.append(f"✅ <b>{d}</b> добавлен. Пропишите у регистратора NS:\n{ns}")
            kb.button(text=f"🌐 {d}", callback_data=CfCb(a="zone", z=z["id"]))
        except CfError as e:
            results.append(f"❌ <b>{d}</b>: {esc(e)}")
    kb.button(text="🌐 Все домены", callback_data=CfCb(a="zones", v="1"))
    kb.adjust(1)
    await wait.edit_text("\n\n".join(results) + "\n\nCloudflare сам импортировал найденные DNS-записи. "
                         "Домен станет активным после смены NS (от нескольких минут до 24 ч).",
                         reply_markup=kb.as_markup())
    await message.answer("Главное меню", reply_markup=main_menu())


@router.message(AddRecord.name, F.text)
async def rec_name(message: Message, state: FSMContext):
    data = await state.get_data()
    name = message.text.strip().lower().rstrip(".")
    if name == "@":
        name = data["zone_name"]
    elif not name.endswith(data["zone_name"]):
        name = f"{name}.{data['zone_name']}"
    if not re.match(r"^[a-z0-9_*.-]+$", name):
        await message.answer("Имя может содержать латинские буквы, цифры, <code>- _ . *</code>. Попробуйте ещё раз:")
        return
    await state.update_data(name=name)
    await state.set_state(AddRecord.content)
    hints = {"A": "IPv4-адрес, например <code>1.2.3.4</code>", "AAAA": "IPv6-адрес",
             "CNAME": "домен, например <code>target.example.com</code> или <code>xxx.cloudfront.net</code>",
             "TXT": "текст", "MX": "почтовый сервер, например <code>mail.example.com</code>",
             "NS": "NS-сервер, например <code>ns1.example.com</code>"}
    await message.answer(f"Имя: <code>{name}</code>\nТеперь значение — {hints[data['rtype']]}:")


@router.message(AddRecord.content, F.text)
async def rec_content(message: Message, state: FSMContext, cf_store: CloudflareStore):
    data = await state.get_data()
    content = message.text.strip()
    if data["rtype"] in ("CNAME", "MX", "NS"):
        content = content.lower().rstrip(".")
    err = _validate_content(data["rtype"], content)
    if err:
        await message.answer(err + " Попробуйте ещё раз:")
        return
    await state.update_data(content=content)
    if data["rtype"] == "MX":
        await state.set_state(AddRecord.priority)
        await message.answer("Приоритет MX (число, обычно <code>10</code>):")
    elif data["rtype"] in PROXIABLE:
        await _ask_proxy(message, state)
    else:
        await _create_record(message, state, cf_store, message.from_user.id, proxied=False)


@router.message(AddRecord.priority, F.text)
async def rec_priority(message: Message, state: FSMContext, cf_store: CloudflareStore):
    if not message.text.strip().isdigit() or int(message.text) > 65535:
        await message.answer("Нужно число от 0 до 65535:")
        return
    await state.update_data(priority=int(message.text))
    await _create_record(message, state, cf_store, message.from_user.id, proxied=False)


async def _ask_proxy(message: Message, state: FSMContext):
    await state.set_state(AddRecord.proxied)
    data = await state.get_data()
    kb = InlineKeyboardBuilder()
    kb.button(text="🟠 Через Cloudflare (Proxied)", callback_data=CfCb(a="rpx", z=data["zone_id"], v="on"))
    kb.button(text="⚪ Только DNS", callback_data=CfCb(a="rpx", z=data["zone_id"], v="off"))
    kb.adjust(1)
    await message.answer("Прокси Cloudflare для этой записи?", reply_markup=kb.as_markup())


async def _create_record(message: Message, state: FSMContext, cf_store: CloudflareStore, user_id: int,
                         proxied: bool):
    data = await state.get_data()
    acc = cf_store.get_active(user_id)
    if not acc or "content" not in data:
        await state.clear()
        await message.answer("Это окно устарело — начните заново.", reply_markup=main_menu())
        return
    record = {"type": data["rtype"], "name": data["name"], "content": data["content"], "ttl": 1}
    if data["rtype"] in PROXIABLE:
        record["proxied"] = proxied
    if data["rtype"] == "MX":
        record["priority"] = data.get("priority", 10)
    await state.clear()
    try:
        rec = await acc.api().create_record(data["zone_id"], record)
    except CfError as e:
        await message.answer(f"❌ Cloudflare: <code>{esc(e)}</code>", reply_markup=main_menu())
        return
    await message.answer("✅ Запись создана", reply_markup=main_menu())
    text, kb = _record_view(rec, data["zone_id"])
    await message.answer(text, reply_markup=kb)


@router.message(EditRecord.content, F.text)
async def rec_edit_content(message: Message, state: FSMContext, cf_store: CloudflareStore):
    data = await state.get_data()
    content = message.text.strip()
    if data["rtype"] in ("CNAME", "MX", "NS"):
        content = content.lower().rstrip(".")
    err = _validate_content(data["rtype"], content)
    if err:
        await message.answer(err + " Попробуйте ещё раз:")
        return
    acc = cf_store.get_active(message.from_user.id)
    await state.clear()
    try:
        rec = await acc.api().update_record(data["zone_id"], data["record_id"], {"content": content})
    except CfError as e:
        await message.answer(f"❌ Cloudflare: <code>{esc(e)}</code>", reply_markup=main_menu())
        return
    await message.answer("✅ Значение изменено", reply_markup=main_menu())
    text, kb = _record_view(rec, data["zone_id"])
    await message.answer(text, reply_markup=kb)
