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
from .. import cf_settings
from ..aws_service import DistributionInfo
from ..storage import Account, Storage
from ..ui import cancel_menu, esc, main_menu

BTN_CREATE = "☁️ Создать CloudFront"
BTN_LIST = "📋 Мои CloudFront"
BTN_SETTINGS = "⚙️ Настройки"

ORDER = 10
MENU = [BTN_CREATE, BTN_LIST, BTN_SETTINGS]
COMMANDS = [("create", "Создать CloudFront"), ("list", "Мои CloudFront"), ("settings", "Настройки CloudFront")]
HELP = (
    "<b>☁️ Создать CloudFront</b> — укажите название и домен вашего сервера — бот создаст дистрибуцию "
    "и пришлёт адрес <code>xxxx.cloudfront.net</code>. Перед созданием настройки можно изменить "
    "(«✏️ Изменить настройки»). Когда она развернётся, бот напишет отдельно.\n"
    "<b>⚙️ Настройки</b> — схема по умолчанию для новых CloudFront "
    "(Protocol, Cache policy, Origin request policy, HTTP/3 и др.).\n"
    "⚠️ Origin должен быть доменом (не IP) — так требует CloudFront.\n\n"
    "<b>📋 Мои CloudFront</b> — список, статус, изменение настроек, включение/выключение, удаление."
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


class SetCb(CallbackData, prefix="cfs"):
    t: str                  # t — шаблон, d — перед созданием, e — существующая дистрибуция
    a: str                  # show | pick | set | reset | save | back
    k: str | None = None    # ключ настройки
    v: str | None = None    # значение


class EditDist(StatesGroup):
    editing = State()


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
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Создать", callback_data=CreateCb(step="confirm"))
    kb.button(text="✏️ Изменить настройки", callback_data=SetCb(t="d", a="show"))
    kb.button(text="❌ Отмена", callback_data=CreateCb(step="cancel"))
    kb.adjust(1)
    return kb.as_markup()


def settings_kb(target: str, values: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for st in cf_settings.SETTINGS:
        kb.button(text=f"{st.title}: {st.label(values[st.key])}", callback_data=SetCb(t=target, a="pick", k=st.key))
    if target == "t":
        kb.button(text="♻️ Сбросить к схеме по умолчанию", callback_data=SetCb(t=target, a="reset"))
    elif target == "d":
        kb.button(text="♻️ Взять из шаблона", callback_data=SetCb(t=target, a="reset"))
        kb.button(text="⬅️ Готово", callback_data=SetCb(t=target, a="back"))
    else:
        kb.button(text="💾 Применить", callback_data=SetCb(t=target, a="save"))
        kb.button(text="⬅️ Назад без изменений", callback_data=SetCb(t=target, a="back"))
    kb.adjust(1)
    return kb.as_markup()


def setting_options_kb(target: str, key: str, current: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in cf_settings.SETTINGS_BY_KEY[key].options:
        mark = "✅ " if value == current else ""
        kb.button(text=f"{mark}{label}", callback_data=SetCb(t=target, a="set", k=key, v=value))
    kb.button(text="⬅️ Назад", callback_data=SetCb(t=target, a="show"))
    kb.adjust(1)
    return kb.as_markup()


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
    kb.button(text="✏️ Настройки", callback_data=DistCb(action="settings", id=d.id))
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
    await state.update_data(origin=domain, settings=storage.get_settings(message.from_user.id))
    await state.set_state(CreateDist.confirm)
    await message.answer(await _confirm_text(state, storage, message.from_user.id), reply_markup=confirm_create_kb())


async def _confirm_text(state: FSMContext, storage: Storage, user_id: int) -> str:
    data = await state.get_data()
    active = storage.get_active(user_id)
    return (
        "<b>Проверьте параметры:</b>\n\n"
        f"Аккаунт: <b>{esc(active.name if active else '-')}</b>\n"
        f"Название: <b>{esc(data['name'])}</b>\n"
        f"Origin (Other → Custom origin): <code>{data['origin']}</code>\n"
        f"{cf_settings.summary(data['settings'])}"
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
        d = await aws.create_distribution(active, data["name"], data["origin"], data["settings"])
    except aws.AwsError as e:
        await cb.message.edit_text(f"❌ Ошибка AWS:\n<code>{esc(e)}</code>")
        await cb.message.answer("Главное меню", reply_markup=main_menu())
        return
    await cb.message.edit_text(
        _result_text(d, data["name"], "✅ <b>CloudFront создан!</b>")
        + "\n\n" + cf_settings.summary(data["settings"])
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
async def dist_action(cb: CallbackQuery, callback_data: DistCb, storage: Storage, state: FSMContext):
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
        elif action == "settings":
            values = await aws.get_settings(active, dist_id)
            await state.set_state(EditDist.editing)
            await state.update_data(edit_dist=dist_id, edit_settings=values)
            await _render_editor(cb, "e", values, state)
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


# ---------- Редактор настроек (шаблон / перед созданием / существующая) ----------

@router.message(Command("settings"))
@router.message(F.text == BTN_SETTINGS)
async def settings_menu(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    values = storage.get_settings(message.from_user.id)
    await message.answer(_editor_title("t", {}) + "\n\n" + cf_settings.summary(values),
                         reply_markup=settings_kb("t", values))


def _editor_title(target: str, data: dict) -> str:
    if target == "t":
        return ("⚙️ <b>Настройки по умолчанию</b> для новых CloudFront\n"
                "Изменения сохраняются сразу. Нажмите на пункт, чтобы изменить.")
    if target == "d":
        return f"✏️ <b>Настройки для «{esc(data.get('name', ''))}»</b>\nМеняются только для этой дистрибуции."
    return (f"✏️ <b>Настройки</b> <code>{data.get('edit_dist', '')}</code>\n"
            "Выберите изменения и нажмите «💾 Применить».")


async def _get_values(target: str, user_id: int, state: FSMContext, storage: Storage) -> dict | None:
    if target == "t":
        return storage.get_settings(user_id)
    data = await state.get_data()
    return data.get("settings" if target == "d" else "edit_settings")


async def _set_values(target: str, user_id: int, values: dict, state: FSMContext, storage: Storage) -> None:
    if target == "t":
        storage.save_settings(user_id, values)
    else:
        await state.update_data(**{"settings" if target == "d" else "edit_settings": values})


async def _render_editor(cb: CallbackQuery, target: str, values: dict, state: FSMContext) -> None:
    data = await state.get_data()
    await cb.message.edit_text(_editor_title(target, data) + "\n\n" + cf_settings.summary(values),
                               reply_markup=settings_kb(target, values))


@router.callback_query(SetCb.filter())
async def settings_action(cb: CallbackQuery, callback_data: SetCb, state: FSMContext, storage: Storage):
    t, a, uid = callback_data.t, callback_data.a, cb.from_user.id
    values = await _get_values(t, uid, state, storage)
    if values is None:
        await cb.answer("Это окно устарело — начните заново из меню", show_alert=True)
        return
    try:
        if a == "show":
            await _render_editor(cb, t, values, state)
        elif a == "pick":
            st = cf_settings.SETTINGS_BY_KEY[callback_data.k]
            await cb.message.edit_text(f"<b>{st.title}</b>\nВыберите значение:",
                                       reply_markup=setting_options_kb(t, st.key, values[st.key]))
        elif a == "set":
            values = cf_settings.normalize({**values, callback_data.k: callback_data.v})
            await _set_values(t, uid, values, state, storage)
            await _render_editor(cb, t, values, state)
        elif a == "reset":
            if t == "t":
                storage.save_settings(uid, None)
                values = storage.get_settings(uid)
            else:
                values = storage.get_settings(uid)
                await _set_values(t, uid, values, state, storage)
            await _render_editor(cb, t, values, state)
            await cb.answer("Сброшено")
            return
        elif a == "back" and t == "d":
            await cb.message.edit_text(await _confirm_text(state, storage, uid), reply_markup=confirm_create_kb())
        elif a in ("back", "save") and t == "e":
            data = await state.get_data()
            dist_id = data["edit_dist"]
            active = storage.get_active(uid)
            if a == "save":
                await cb.message.edit_text("⏳ Применяю настройки…")
                await aws.update_settings(active, dist_id, values)
                await cb.answer("Настройки применены, разворачивается 5–15 мин", show_alert=True)
            await state.clear()
            await _show_dist(cb, storage, dist_id)
            return
        await cb.answer()
    except aws.AwsError as e:
        await cb.answer(str(e)[:190], show_alert=True)
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            await cb.answer()
        else:
            raise
