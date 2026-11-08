"""Создание и управление CloudFront-дистрибуциями активного аккаунта."""
import asyncio
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import aws_service as aws
from ..aws_service import DistributionInfo
from ..storage import Account, Storage
from ..ui import cancel_menu, esc, main_menu

BTN_CREATE = "☁️ Создать CloudFront"
BTN_LIST = "📋 Мои CloudFront"

ORDER = 10
MENU = [BTN_CREATE, BTN_LIST]
COMMANDS = [("create", "Создать CloudFront"), ("list", "Мои CloudFront")]
HELP = (
    "<b>☁️ Создать CloudFront</b> — укажите название и домен вашего сервера — бот создаст дистрибуцию "
    "(Origin: HTTP only, CachingDisabled, AllViewer) и пришлёт адрес <code>xxxx.cloudfront.net</code>. "
    "Когда она развернётся, бот напишет отдельно.\n"
    "⚠️ Origin должен быть доменом (не IP) — так требует CloudFront.\n\n"
    "<b>📋 Мои CloudFront</b> — список, статус, включение/выключение, удаление."
)

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

router = Router(name="cloudfront")


class DistCb(CallbackData, prefix="dist"):
    action: str  # open | enable | disable | delete | delete_yes | refresh | back
    id: str | None = None


class CreateCb(CallbackData, prefix="create"):
    step: str  # confirm | cancel
    value: str | None = None


class CreateDist(StatesGroup):
    name = State()
    origin = State()
    confirm = State()


# ---------- Клавиатуры ----------

def _choice_kb(options: list[tuple[str, CreateCb]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for text, cb in options:
        kb.button(text=text, callback_data=cb)
    kb.button(text="❌ Отмена", callback_data=CreateCb(step="cancel"))
    kb.adjust(1)
    return kb.as_markup()


def confirm_create_kb() -> InlineKeyboardMarkup:
    return _choice_kb([("🚀 Создать", CreateCb(step="confirm"))])


def distributions_kb(items: list[DistributionInfo]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in items:
        icon = "⏳" if d.status != "Deployed" else ("🟢" if d.enabled else "⚪️")
        kb.button(text=f"{icon} {d.domain} → {d.origin}"[:64], callback_data=DistCb(action="open", id=d.id))
    kb.adjust(1)
    return kb.as_markup()


def distribution_card_kb(d: DistributionInfo) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data=DistCb(action="refresh", id=d.id))
    if d.enabled:
        kb.button(text="⏸ Выключить", callback_data=DistCb(action="disable", id=d.id))
    else:
        kb.button(text="▶️ Включить", callback_data=DistCb(action="enable", id=d.id))
        kb.button(text="🗑 Удалить", callback_data=DistCb(action="delete", id=d.id))
    kb.button(text="⬅️ К списку", callback_data=DistCb(action="back"))
    kb.adjust(1)
    return kb.as_markup()


def confirm_delete_kb(dist_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data=DistCb(action="delete_yes", id=dist_id))
    kb.button(text="Нет", callback_data=DistCb(action="open", id=dist_id))
    return kb.as_markup()


# ---------- Создание ----------

NAME_RE = re.compile(r"^[\w\-. ]{1,128}$")
WATCH_INTERVAL = 30          # как часто проверять статус (сек)
WATCH_TIMEOUT = 40 * 60      # сколько максимум ждать развёртывания (сек)
_watchers: set[asyncio.Task] = set()


@router.message(Command("create"))
@router.message(F.text == BTN_CREATE)
async def create_start(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    active = storage.get_active(message.from_user.id)
    if not active:
        await message.answer("Сначала добавьте AWS-аккаунт в «👥 Аккаунты».")
        return
    await state.set_state(CreateDist.name)
    await message.answer(
        f"Аккаунт: <b>{esc(active.name)}</b>\n\n"
        "Шаг 1/2. Введите <b>название</b> дистрибуции (Distribution name), например <code>my-server-1</code>:",
        reply_markup=cancel_menu(),
    )


@router.message(CreateDist.name, F.text)
async def create_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not NAME_RE.match(name):
        await message.answer("Название: до 128 символов — буквы, цифры, пробел, <code>- _ .</code>. Попробуйте ещё раз:")
        return
    await state.update_data(name=name)
    await state.set_state(CreateDist.origin)
    await message.answer(
        "Шаг 2/2. Отправьте <b>домен вашего сервера</b> (Custom origin), например <code>example.com</code>:"
    )


@router.message(CreateDist.origin, F.text)
async def create_origin(message: Message, state: FSMContext, storage: Storage):
    domain = message.text.strip().lower()
    domain = re.sub(r"^https?://", "", domain).split("/")[0].split(":")[0]
    if IP_RE.match(domain):
        await message.answer("CloudFront не принимает IP-адрес как origin. Привяжите домен к IP (A-запись) и отправьте домен:")
        return
    if not DOMAIN_RE.match(domain):
        await message.answer("Некорректный домен. Пример: <code>example.com</code>. Попробуйте ещё раз:")
        return
    await state.update_data(origin=domain)
    await state.set_state(CreateDist.confirm)
    data = await state.get_data()
    active = storage.get_active(message.from_user.id)
    await message.answer(
        "<b>Проверьте параметры:</b>\n\n"
        f"Аккаунт: <b>{esc(active.name if active else '-')}</b>\n"
        f"Название: <b>{esc(data['name'])}</b>\n"
        f"Origin (Other → Custom origin): <code>{domain}</code>\n"
        "Protocol: <code>HTTP only</code>\n"
        "Cache policy: <code>CachingDisabled</code>\n"
        "Origin request policy: <code>AllViewer</code>\n"
        "Остальное — по умолчанию.",
        reply_markup=confirm_create_kb(),
    )


@router.callback_query(CreateCb.filter(F.step == "cancel"))
async def create_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Создание отменено.")
    await cb.message.answer("Главное меню", reply_markup=main_menu())
    await cb.answer()


def _result_text(d: DistributionInfo, name: str, header: str) -> str:
    return (
        f"{header}\n\n"
        f"Название: <b>{esc(name)}</b>\n"
        f"Адрес: <code>{d.domain}</code>\n"
        f"Origin: <code>{d.origin}</code>\n"
        f"ID: <code>{d.id}</code>\n"
        f"ARN: <code>{d.arn}</code>\n"
        f"Статус: <b>{d.status}</b>"
    )


async def _watch_deploy(bot: Bot, chat_id: int, account: Account, dist_id: str, name: str) -> None:
    """Ждёт, пока дистрибуция развернётся (Deployed), и присылает сообщение."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WATCH_TIMEOUT
    while loop.time() < deadline:
        await asyncio.sleep(WATCH_INTERVAL)
        try:
            d = await aws.get_distribution(account, dist_id)
        except aws.AwsError:
            continue
        if d.status == "Deployed":
            await bot.send_message(
                chat_id,
                _result_text(d, name, "🎉 <b>CloudFront развёрнут и готов к работе!</b>"),
                reply_markup=distribution_card_kb(d),
            )
            return
    await bot.send_message(chat_id, f"⏳ Дистрибуция <code>{dist_id}</code> всё ещё разворачивается. "
                                    "Проверьте позже в «📋 Мои CloudFront».")


@router.callback_query(CreateDist.confirm, CreateCb.filter(F.step == "confirm"))
async def create_confirm(cb: CallbackQuery, state: FSMContext, storage: Storage):
    data = await state.get_data()
    active = storage.get_active(cb.from_user.id)
    if not active:
        await cb.answer("Нет активного аккаунта", show_alert=True)
        return
    await state.clear()
    await cb.message.edit_text("⏳ Создаю CloudFront…")
    await cb.answer()
    try:
        d = await aws.create_distribution(active, data["name"], data["origin"])
    except aws.AwsError as e:
        await cb.message.edit_text(f"❌ Ошибка AWS:\n<code>{esc(e)}</code>")
        await cb.message.answer("Главное меню", reply_markup=main_menu())
        return
    await cb.message.edit_text(
        _result_text(d, data["name"], "✅ <b>CloudFront создан!</b>")
        + "\n\nРазвёртывание занимает ~5–15 минут — я напишу, когда будет готово.",
        reply_markup=distribution_card_kb(d),
    )
    await cb.message.answer("Главное меню", reply_markup=main_menu())
    task = asyncio.create_task(_watch_deploy(cb.bot, cb.message.chat.id, active, d.id, data["name"]))
    _watchers.add(task)
    task.add_done_callback(_watchers.discard)


# ---------- Список и управление ----------

async def _render_list(user_id: int, storage: Storage):
    active = storage.get_active(user_id)
    if not active:
        return "Сначала добавьте AWS-аккаунт в «👥 Аккаунты».", None
    items = await aws.list_distributions(active)
    if not items:
        return f"Аккаунт <b>{esc(active.name)}</b>: дистрибуций нет.", None
    return (
        f"Аккаунт <b>{esc(active.name)}</b>: {len(items)} дистрибуций\n🟢 включена · ⚪️ выключена · ⏳ разворачивается",
        distributions_kb(items),
    )


@router.message(Command("list"))
@router.message(F.text == BTN_LIST)
async def list_dists(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    try:
        text, markup = await _render_list(message.from_user.id, storage)
    except aws.AwsError as e:
        await message.answer(f"❌ Ошибка AWS:\n<code>{esc(e)}</code>")
        return
    await message.answer(text, reply_markup=markup)


async def _show_dist(cb: CallbackQuery, storage: Storage, dist_id: str):
    active = storage.get_active(cb.from_user.id)
    d = await aws.get_distribution(active, dist_id)
    await cb.message.edit_text(
        f"<b>{d.domain}</b>\n\n"
        f"ID: <code>{d.id}</code>\n"
        f"Origin: <code>{d.origin}</code>\n"
        f"ARN: <code>{d.arn}</code>\n"
        f"Включена: {'да 🟢' if d.enabled else 'нет ⚪️'}\n"
        f"Статус: {d.status}\n"
        f"Комментарий: {esc(d.comment) or '-'}",
        reply_markup=distribution_card_kb(d),
    )


@router.callback_query(DistCb.filter())
async def dist_action(cb: CallbackQuery, callback_data: DistCb, storage: Storage):
    active = storage.get_active(cb.from_user.id)
    if not active:
        await cb.answer("Нет активного аккаунта", show_alert=True)
        return
    action, dist_id = callback_data.action, callback_data.id
    try:
        if action == "back":
            text, markup = await _render_list(cb.from_user.id, storage)
            await cb.message.edit_text(text, reply_markup=markup)
        elif action in ("open", "refresh"):
            await _show_dist(cb, storage, dist_id)
        elif action in ("enable", "disable"):
            await aws.set_enabled(active, dist_id, action == "enable")
            await cb.answer("Готово, изменения применяются (5–15 мин)")
            await _show_dist(cb, storage, dist_id)
            return
        elif action == "delete":
            await cb.message.edit_text(
                f"Удалить дистрибуцию <code>{dist_id}</code> из AWS? Это необратимо.",
                reply_markup=confirm_delete_kb(dist_id),
            )
        elif action == "delete_yes":
            await aws.delete_distribution(active, dist_id)
            await cb.answer("Удалено")
            text, markup = await _render_list(cb.from_user.id, storage)
            await cb.message.edit_text(text, reply_markup=markup)
            return
        await cb.answer()
    except aws.AwsError as e:
        await cb.answer(str(e)[:190], show_alert=True)
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            await cb.answer("Без изменений")
        else:
            raise
