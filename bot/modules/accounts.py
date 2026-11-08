"""Управление AWS-аккаунтами: добавление, переключение, удаление."""
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import aws_service as aws
from ..storage import Account, Storage
from ..ui import cancel_menu, esc, main_menu

BTN_ACCOUNTS = "👥 Аккаунты"

ORDER = 30
MENU = [BTN_ACCOUNTS]
COMMANDS = [("accounts", "Аккаунты AWS")]
HELP = (
    "<b>👥 Аккаунты</b> — добавьте AWS-аккаунт (название, Access Key ID, Secret Access Key). "
    "Можно добавить сколько угодно и переключаться между ними — активный отмечен ✅. "
    "Ключи хранятся в зашифрованном виде."
)

ACCESS_KEY_RE = re.compile(r"^(AKIA|ASIA)[A-Z0-9]{16}$")

router = Router(name="accounts")


class AccCb(CallbackData, prefix="acc"):
    action: str  # open | select | delete | delete_yes | add | back
    id: int = 0


class AddAccount(StatesGroup):
    name = State()
    access_key = State()
    secret = State()


# ---------- Клавиатуры ----------

def accounts_kb(accounts: list[Account], active_id: int | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for acc in accounts:
        mark = "✅ " if acc.id == active_id else "▫️ "
        kb.button(text=f"{mark}{acc.name}", callback_data=AccCb(action="open", id=acc.id))
    kb.button(text="➕ Добавить аккаунт", callback_data=AccCb(action="add"))
    kb.adjust(1)
    return kb.as_markup()


def account_card_kb(acc: Account, is_active: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if not is_active:
        kb.button(text="✅ Сделать активным", callback_data=AccCb(action="select", id=acc.id))
    kb.button(text="🗑 Удалить", callback_data=AccCb(action="delete", id=acc.id))
    kb.button(text="⬅️ Назад", callback_data=AccCb(action="back"))
    kb.adjust(1)
    return kb.as_markup()


def confirm_delete_kb(acc_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data=AccCb(action="delete_yes", id=acc_id))
    kb.button(text="Нет", callback_data=AccCb(action="open", id=acc_id))
    return kb.as_markup()


def _accounts_view(storage: Storage, user_id: int):
    accounts = storage.list_accounts(user_id)
    active = storage.get_active(user_id)
    if accounts:
        text = (
            f"<b>Ваши AWS-аккаунты</b> ({len(accounts)})\n"
            f"Активный: ✅ <b>{esc(active.name) if active else '-'}</b>\n\n"
            "Нажмите на аккаунт, чтобы переключиться или удалить."
        )
    else:
        text = "У вас пока нет аккаунтов. Нажмите «➕ Добавить аккаунт»."
    return text, accounts_kb(accounts, active.id if active else None)


# ---------- Обработчики ----------

@router.message(Command("accounts"))
@router.message(F.text == BTN_ACCOUNTS)
async def show_accounts(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    text, markup = _accounts_view(storage, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(AccCb.filter(F.action == "back"))
async def acc_back(cb: CallbackQuery, storage: Storage):
    text, markup = _accounts_view(storage, cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(AccCb.filter(F.action == "open"))
async def acc_open(cb: CallbackQuery, callback_data: AccCb, storage: Storage):
    acc = storage.get_account(cb.from_user.id, callback_data.id)
    if not acc:
        await cb.answer("Аккаунт не найден", show_alert=True)
        return
    active = storage.get_active(cb.from_user.id)
    is_active = bool(active and active.id == acc.id)
    await cb.message.edit_text(
        f"<b>{esc(acc.name)}</b>{' ✅ (активный)' if is_active else ''}\n\n"
        f"AWS Account ID: <code>{acc.aws_account_id}</code>\n"
        f"Access Key: <code>{acc.masked_key}</code>",
        reply_markup=account_card_kb(acc, is_active),
    )
    await cb.answer()


@router.callback_query(AccCb.filter(F.action == "select"))
async def acc_select(cb: CallbackQuery, callback_data: AccCb, storage: Storage):
    acc = storage.get_account(cb.from_user.id, callback_data.id)
    if not acc:
        await cb.answer("Аккаунт не найден", show_alert=True)
        return
    storage.set_active(cb.from_user.id, acc.id)
    await cb.answer(f"Активный аккаунт: {acc.name}")
    text, markup = _accounts_view(storage, cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(AccCb.filter(F.action == "delete"))
async def acc_delete(cb: CallbackQuery, callback_data: AccCb, storage: Storage):
    acc = storage.get_account(cb.from_user.id, callback_data.id)
    if not acc:
        await cb.answer("Аккаунт не найден", show_alert=True)
        return
    await cb.message.edit_text(
        f"Удалить аккаунт <b>{esc(acc.name)}</b> из бота?\n(В AWS ничего не удаляется.)",
        reply_markup=confirm_delete_kb(acc.id),
    )
    await cb.answer()


@router.callback_query(AccCb.filter(F.action == "delete_yes"))
async def acc_delete_yes(cb: CallbackQuery, callback_data: AccCb, storage: Storage):
    storage.delete_account(cb.from_user.id, callback_data.id)
    await cb.answer("Удалено")
    text, markup = _accounts_view(storage, cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(AccCb.filter(F.action == "add"))
async def acc_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddAccount.name)
    await cb.message.answer("Введите название аккаунта (например: <i>Аккаунт 1</i>):", reply_markup=cancel_menu())
    await cb.answer()


@router.message(AddAccount.name, F.text)
async def acc_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:64])
    await state.set_state(AddAccount.access_key)
    await message.answer("Отправьте <b>Access Key ID</b> (начинается с <code>AKIA…</code>):")


@router.message(AddAccount.access_key, F.text)
async def acc_add_key(message: Message, state: FSMContext):
    key = message.text.strip()
    if not ACCESS_KEY_RE.match(key):
        await message.answer("Это не похоже на Access Key ID (20 символов, начинается с AKIA). Попробуйте ещё раз:")
        return
    await state.update_data(access_key=key)
    await state.set_state(AddAccount.secret)
    await message.answer("Теперь отправьте <b>Secret Access Key</b>.\nСообщение с ключом будет сразу удалено из чата.")


@router.message(AddAccount.secret, F.text)
async def acc_add_secret(message: Message, state: FSMContext, storage: Storage):
    secret = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    wait = await message.answer("⏳ Проверяю ключи в AWS…")
    try:
        aws_account_id = await aws.verify_credentials(data["access_key"], secret)
    except aws.AwsError as e:
        await wait.edit_text(
            f"❌ Ключи не подошли:\n<code>{esc(e)}</code>\n\nОтправьте Secret Access Key ещё раз или /cancel."
        )
        return
    storage.add_account(message.from_user.id, data["name"], data["access_key"], secret, "us-east-1", aws_account_id)
    await state.clear()
    await wait.edit_text(f"✅ Аккаунт <b>{esc(data['name'])}</b> добавлен (AWS ID <code>{aws_account_id}</code>).")
    active = storage.get_active(message.from_user.id)
    await message.answer(f"Активный аккаунт: <b>{esc(active.name)}</b>", reply_markup=main_menu())
