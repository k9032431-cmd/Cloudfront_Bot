"""👑 Пользователи — главный админ выдаёт и забирает доступ по Telegram ID."""
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import Config
from ..middleware import AccessCb, display_name
from ..storage import Storage
from ..ui import cancel_menu, esc, main_menu

BTN_USERS = "👑 Пользователи"

ADMIN_ONLY = True   # кнопка видна и работает только у главных админов (ADMIN_IDS)
ORDER = 900
MENU = [BTN_USERS]
COMMANDS = [("users", "Пользователи и доступ")]
HELP = (
    "<b>👑 Пользователи</b> (только для админа) — дать доступ по Telegram ID, забрать доступ. "
    "Когда незнакомый человек пишет боту, вам приходит запрос с кнопкой «✅ Дать доступ»."
)

router = Router(name="admin")


class UserCb(CallbackData, prefix="usr"):
    action: str              # open | revoke | revoke_yes | add | back
    id: int | None = None


class AddUser(StatesGroup):
    user_id = State()


# ---------- Вид ----------

def _users_view(storage: Storage, config: Config):
    users = storage.list_users()
    lines = ["<b>👑 Пользователи бота</b>\n", "<b>Админы</b> (из .env, ADMIN_IDS):"]
    lines += [f"• <code>{a}</code>" for a in sorted(config.admin_ids)] or ["• —"]
    lines.append(f"\n<b>С доступом</b>: {len(users)}")
    if not users:
        lines.append("пока никого — нажмите «➕ Дать доступ»")
    kb = InlineKeyboardBuilder()
    for u in users:
        kb.button(text=f"👤 {u['name'] or 'без имени'} · {u['user_id']}"[:64],
                  callback_data=UserCb(action="open", id=u["user_id"]))
    kb.button(text="➕ Дать доступ", callback_data=UserCb(action="add"))
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


def _user_card_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 Забрать доступ", callback_data=UserCb(action="revoke", id=user_id))
    kb.button(text="⬅️ Назад", callback_data=UserCb(action="back"))
    kb.adjust(1)
    return kb.as_markup()


async def _grant(bot: Bot, storage: Storage, config: Config, admin_id: int, user_id: int, name: str = "") -> str:
    if user_id in config.admin_ids:
        return f"<code>{user_id}</code> — это админ, у него уже есть доступ."
    if not storage.add_user(user_id, admin_id, name):
        return f"У пользователя <code>{user_id}</code> уже есть доступ."
    try:
        await bot.send_message(user_id, "✅ Вам открыли доступ к боту. Нажмите /start")
        note = "Пользователь получил уведомление."
    except Exception:
        note = "Уведомить не удалось (он ещё не писал боту) — пусть нажмёт /start."
    return f"✅ Доступ выдан: <code>{user_id}</code>\n{note}"


# ---------- Список и карточка ----------

@router.message(Command("users"))
@router.message(F.text == BTN_USERS)
async def users_menu(message: Message, state: FSMContext, storage: Storage, config: Config):
    await state.clear()
    text, kb = _users_view(storage, config)
    await message.answer(text, reply_markup=kb)


@router.callback_query(UserCb.filter(F.action == "back"))
async def users_back(cb: CallbackQuery, storage: Storage, config: Config):
    text, kb = _users_view(storage, config)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(UserCb.filter(F.action == "open"))
async def user_open(cb: CallbackQuery, callback_data: UserCb, storage: Storage):
    user = next((u for u in storage.list_users() if u["user_id"] == callback_data.id), None)
    if not user:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    accounts = len(storage.list_accounts(user["user_id"]))
    await cb.message.edit_text(
        f"👤 <b>{esc(user['name'] or 'без имени')}</b>\n\n"
        f"ID: <code>{user['user_id']}</code>\n"
        f"Доступ с: {user['added_at']} (UTC)\n"
        f"AWS-аккаунтов: {accounts}",
        reply_markup=_user_card_kb(user["user_id"]),
    )
    await cb.answer()


@router.callback_query(UserCb.filter(F.action == "revoke"))
async def user_revoke(cb: CallbackQuery, callback_data: UserCb):
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, забрать", callback_data=UserCb(action="revoke_yes", id=callback_data.id))
    kb.button(text="Нет", callback_data=UserCb(action="open", id=callback_data.id))
    await cb.message.edit_text(
        f"Забрать доступ у <code>{callback_data.id}</code>?\n"
        "Его AWS-аккаунты останутся в базе и вернутся, если снова дать доступ.",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.callback_query(UserCb.filter(F.action == "revoke_yes"))
async def user_revoke_yes(cb: CallbackQuery, callback_data: UserCb, storage: Storage, config: Config, bot: Bot):
    storage.remove_user(callback_data.id)
    try:
        await bot.send_message(callback_data.id, "⛔️ Ваш доступ к боту закрыт.")
    except Exception:
        pass
    await cb.answer("Доступ забран")
    text, kb = _users_view(storage, config)
    await cb.message.edit_text(text, reply_markup=kb)


# ---------- Выдача доступа по ID ----------

@router.callback_query(UserCb.filter(F.action == "add"))
async def user_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddUser.user_id)
    await cb.message.answer(
        "Отправьте <b>Telegram ID</b> пользователя (только цифры).\n"
        "Можно несколько через пробел или запятую.\n\n"
        "💡 Свой ID человек увидит, если напишет боту /start — "
        "а вам сразу придёт запрос с кнопкой «✅ Дать доступ».",
        reply_markup=cancel_menu(),
    )
    await cb.answer()


@router.message(AddUser.user_id, F.text)
async def user_add_id(message: Message, state: FSMContext, storage: Storage, config: Config, bot: Bot):
    parts = message.text.replace(",", " ").split()
    if not parts or not all(p.isdigit() and len(p) <= 15 for p in parts):
        await message.answer("Нужен числовой Telegram ID, например <code>123456789</code>. Попробуйте ещё раз:")
        return
    await state.clear()
    results = [await _grant(bot, storage, config, message.from_user.id, int(p)) for p in dict.fromkeys(parts)]
    await message.answer("\n\n".join(results), reply_markup=main_menu())
    text, kb = _users_view(storage, config)
    await message.answer(text, reply_markup=kb)


# ---------- Кнопки из запроса доступа ----------

@router.callback_query(AccessCb.filter(F.action == "grant"))
async def access_grant(cb: CallbackQuery, callback_data: AccessCb, storage: Storage, config: Config, bot: Bot):
    # Имя берём из текста запроса (строка «Пользователь: …»)
    name = ""
    for line in (cb.message.text or "").splitlines():
        if line.startswith("Пользователь:"):
            name = line.split(":", 1)[1].strip().strip("-").strip()
    result = await _grant(bot, storage, config, cb.from_user.id, callback_data.id, name)
    await cb.message.edit_text(f"{cb.message.html_text}\n\n{result}")
    await cb.answer()


@router.callback_query(AccessCb.filter(F.action == "deny"))
async def access_deny(cb: CallbackQuery, callback_data: AccessCb):
    await cb.message.edit_text(f"{cb.message.html_text}\n\n❌ Отклонено")
    await cb.answer()

