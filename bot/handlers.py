import html
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from . import aws_service as aws
from . import keyboards as kb
from .storage import Storage

router = Router()

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$")
ACCESS_KEY_RE = re.compile(r"^(AKIA|ASIA)[A-Z0-9]{16}$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

HELP_TEXT = (
    "<b>Как пользоваться ботом</b>\n\n"
    "1. <b>👥 Аккаунты → ➕ Добавить аккаунт</b> — введите название, "
    "Access Key ID и Secret Access Key от IAM-пользователя AWS.\n"
    "   Бот проверит ключи и сохранит их в зашифрованном виде.\n"
    "2. Можно добавить сколько угодно аккаунтов и переключаться между ними "
    "(активный отмечен ✅).\n"
    "3. <b>☁️ Создать CloudFront</b> — укажите домен вашего сервера (origin), "
    "выберите протокол — бот создаст дистрибуцию и пришлёт адрес "
    "<code>xxxx.cloudfront.net</code>.\n"
    "4. <b>📋 Мои CloudFront</b> — список, статус, включение/выключение, удаление.\n\n"
    "⚠️ Origin должен быть доменом (не IP-адресом) — так требует CloudFront.\n"
    "/cancel — отменить текущее действие."
)


class AddAccount(StatesGroup):
    name = State()
    access_key = State()
    secret = State()


class CreateDist(StatesGroup):
    origin = State()
    protocol = State()
    caching = State()
    confirm = State()


def _esc(s: str) -> str:
    return html.escape(s)


# ---------- Общие ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    active = storage.get_active(message.from_user.id)
    acc_line = f"Активный аккаунт: <b>{_esc(active.name)}</b>" if active else "Аккаунтов пока нет — добавьте первый в «👥 Аккаунты»."
    await message.answer(f"👋 Бот для создания AWS CloudFront.\n\n{acc_line}", reply_markup=kb.main_menu())


@router.message(Command("help"))
@router.message(F.text == kb.BTN_HELP)
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, reply_markup=kb.main_menu())


@router.message(Command("cancel"))
@router.message(F.text == kb.BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=kb.main_menu())


# ---------- Аккаунты ----------

async def _accounts_text_kb(storage: Storage, user_id: int):
    accounts = storage.list_accounts(user_id)
    active = storage.get_active(user_id)
    if accounts:
        text = f"<b>Ваши AWS-аккаунты</b> ({len(accounts)})\nАктивный: ✅ <b>{_esc(active.name) if active else '-'}</b>\n\nНажмите на аккаунт, чтобы переключиться или удалить."
    else:
        text = "У вас пока нет аккаунтов. Нажмите «➕ Добавить аккаунт»."
    return text, kb.accounts_kb(accounts, active.id if active else None)


@router.message(Command("accounts"))
@router.message(F.text == kb.BTN_ACCOUNTS)
async def show_accounts(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    text, markup = await _accounts_text_kb(storage, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(kb.AccCb.filter(F.action == "back"))
async def acc_back(cb: CallbackQuery, storage: Storage):
    text, markup = await _accounts_text_kb(storage, cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(kb.AccCb.filter(F.action == "open"))
async def acc_open(cb: CallbackQuery, callback_data: kb.AccCb, storage: Storage):
    acc = storage.get_account(cb.from_user.id, callback_data.id)
    if not acc:
        await cb.answer("Аккаунт не найден", show_alert=True)
        return
    active = storage.get_active(cb.from_user.id)
    is_active = bool(active and active.id == acc.id)
    text = (
        f"<b>{_esc(acc.name)}</b>{' ✅ (активный)' if is_active else ''}\n\n"
        f"AWS Account ID: <code>{acc.aws_account_id}</code>\n"
        f"Access Key: <code>{acc.masked_key}</code>"
    )
    await cb.message.edit_text(text, reply_markup=kb.account_card_kb(acc, is_active))
    await cb.answer()


@router.callback_query(kb.AccCb.filter(F.action == "select"))
async def acc_select(cb: CallbackQuery, callback_data: kb.AccCb, storage: Storage):
    acc = storage.get_account(cb.from_user.id, callback_data.id)
    if not acc:
        await cb.answer("Аккаунт не найден", show_alert=True)
        return
    storage.set_active(cb.from_user.id, acc.id)
    await cb.answer(f"Активный аккаунт: {acc.name}")
    text, markup = await _accounts_text_kb(storage, cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(kb.AccCb.filter(F.action == "delete"))
async def acc_delete(cb: CallbackQuery, callback_data: kb.AccCb, storage: Storage):
    acc = storage.get_account(cb.from_user.id, callback_data.id)
    if not acc:
        await cb.answer("Аккаунт не найден", show_alert=True)
        return
    await cb.message.edit_text(
        f"Удалить аккаунт <b>{_esc(acc.name)}</b> из бота?\n(В AWS ничего не удаляется.)",
        reply_markup=kb.confirm_delete_account_kb(acc.id),
    )
    await cb.answer()


@router.callback_query(kb.AccCb.filter(F.action == "delete_yes"))
async def acc_delete_yes(cb: CallbackQuery, callback_data: kb.AccCb, storage: Storage):
    storage.delete_account(cb.from_user.id, callback_data.id)
    await cb.answer("Удалено")
    text, markup = await _accounts_text_kb(storage, cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(kb.AccCb.filter(F.action == "add"))
async def acc_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddAccount.name)
    await cb.message.answer("Введите название аккаунта (например: <i>Аккаунт 1</i>):", reply_markup=kb.cancel_menu())
    await cb.answer()


@router.message(AddAccount.name, F.text)
async def acc_add_name(message: Message, state: FSMContext):
    name = message.text.strip()[:64]
    await state.update_data(name=name)
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
        await wait.edit_text(f"❌ Ключи не подошли:\n<code>{_esc(str(e))}</code>\n\nОтправьте Secret Access Key ещё раз или /cancel.")
        return
    storage.add_account(message.from_user.id, data["name"], data["access_key"], secret, "us-east-1", aws_account_id)
    await state.clear()
    await wait.edit_text(f"✅ Аккаунт <b>{_esc(data['name'])}</b> добавлен (AWS ID <code>{aws_account_id}</code>).")
    active = storage.get_active(message.from_user.id)
    await message.answer(f"Активный аккаунт: <b>{_esc(active.name)}</b>", reply_markup=kb.main_menu())


# ---------- Создание CloudFront ----------

@router.message(Command("create"))
@router.message(F.text == kb.BTN_CREATE)
async def create_start(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    active = storage.get_active(message.from_user.id)
    if not active:
        await message.answer("Сначала добавьте AWS-аккаунт в «👥 Аккаунты».")
        return
    await state.set_state(CreateDist.origin)
    await message.answer(
        f"Аккаунт: <b>{_esc(active.name)}</b>\n\n"
        "Отправьте <b>домен вашего сервера</b> (origin), например <code>example.com</code> или <code>sub.example.com</code>:",
        reply_markup=kb.cancel_menu(),
    )


@router.message(CreateDist.origin, F.text)
async def create_origin(message: Message, state: FSMContext):
    domain = message.text.strip().lower()
    domain = re.sub(r"^https?://", "", domain).split("/")[0].split(":")[0]
    if IP_RE.match(domain):
        await message.answer("CloudFront не принимает IP-адрес как origin. Привяжите домен к IP (A-запись) и отправьте домен:")
        return
    if not DOMAIN_RE.match(domain):
        await message.answer("Некорректный домен. Пример: <code>example.com</code>. Попробуйте ещё раз:")
        return
    await state.update_data(origin=domain)
    await state.set_state(CreateDist.protocol)
    await message.answer(f"Origin: <code>{domain}</code>\n\nКак CloudFront будет подключаться к серверу?", reply_markup=kb.protocol_kb())


@router.callback_query(kb.CreateCb.filter(F.step == "cancel"))
async def create_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Создание отменено.")
    await cb.message.answer("Главное меню", reply_markup=kb.main_menu())
    await cb.answer()


@router.callback_query(CreateDist.protocol, kb.CreateCb.filter(F.step == "proto"))
async def create_proto(cb: CallbackQuery, callback_data: kb.CreateCb, state: FSMContext):
    await state.update_data(protocol=callback_data.value)
    await state.set_state(CreateDist.caching)
    await cb.message.edit_text("Кэширование:", reply_markup=kb.caching_kb())
    await cb.answer()


@router.callback_query(CreateDist.caching, kb.CreateCb.filter(F.step == "cache"))
async def create_cache(cb: CallbackQuery, callback_data: kb.CreateCb, state: FSMContext, storage: Storage):
    await state.update_data(caching=callback_data.value == "on")
    await state.set_state(CreateDist.confirm)
    data = await state.get_data()
    active = storage.get_active(cb.from_user.id)
    await cb.message.edit_text(
        "<b>Проверьте параметры:</b>\n\n"
        f"Аккаунт: <b>{_esc(active.name if active else '-')}</b>\n"
        f"Origin: <code>{data['origin']}</code>\n"
        f"Протокол к origin: <code>{data['protocol']}</code>\n"
        f"Кэширование: {'включено' if data['caching'] else 'выключено'}\n"
        "Методы: все (GET, POST, PUT, …), заголовки: все (AllViewer)",
        reply_markup=kb.confirm_create_kb(),
    )
    await cb.answer()


@router.callback_query(CreateDist.confirm, kb.CreateCb.filter(F.step == "confirm"))
async def create_confirm(cb: CallbackQuery, state: FSMContext, storage: Storage):
    data = await state.get_data()
    active = storage.get_active(cb.from_user.id)
    if not active:
        await cb.answer("Нет активного аккаунта", show_alert=True)
        return
    await cb.message.edit_text("⏳ Создаю CloudFront…")
    await cb.answer()
    try:
        d = await aws.create_distribution(active, data["origin"], data["protocol"], data["caching"])
    except aws.AwsError as e:
        await cb.message.edit_text(f"❌ Ошибка AWS:\n<code>{_esc(str(e))}</code>")
        await state.clear()
        await cb.message.answer("Главное меню", reply_markup=kb.main_menu())
        return
    await state.clear()
    await cb.message.edit_text(
        "✅ <b>CloudFront создан!</b>\n\n"
        f"Адрес: <code>{d.domain}</code>\n"
        f"ID: <code>{d.id}</code>\n"
        f"Origin: <code>{d.origin}</code>\n"
        f"Статус: {d.status}\n\n"
        "Развёртывание занимает ~5–15 минут. Статус можно проверить в «📋 Мои CloudFront».",
        reply_markup=kb.distribution_card_kb(d),
    )
    await cb.message.answer("Главное меню", reply_markup=kb.main_menu())


# ---------- Список и управление ----------

async def _render_list(user_id: int, storage: Storage):
    active = storage.get_active(user_id)
    if not active:
        return "Сначала добавьте AWS-аккаунт в «👥 Аккаунты».", None
    items = await aws.list_distributions(active)
    if not items:
        return f"Аккаунт <b>{_esc(active.name)}</b>: дистрибуций нет.", None
    return (
        f"Аккаунт <b>{_esc(active.name)}</b>: {len(items)} дистрибуций\n🟢 включена · ⚪️ выключена · ⏳ разворачивается",
        kb.distributions_kb(items),
    )


@router.message(Command("list"))
@router.message(F.text == kb.BTN_LIST)
async def list_dists(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    try:
        text, markup = await _render_list(message.from_user.id, storage)
    except aws.AwsError as e:
        await message.answer(f"❌ Ошибка AWS:\n<code>{_esc(str(e))}</code>")
        return
    await message.answer(text, reply_markup=markup)


async def _show_dist(cb: CallbackQuery, storage: Storage, dist_id: str):
    active = storage.get_active(cb.from_user.id)
    if not active:
        await cb.answer("Нет активного аккаунта", show_alert=True)
        return
    d = await aws.get_distribution(active, dist_id)
    text = (
        f"<b>{d.domain}</b>\n\n"
        f"ID: <code>{d.id}</code>\n"
        f"Origin: <code>{d.origin}</code>\n"
        f"Включена: {'да 🟢' if d.enabled else 'нет ⚪️'}\n"
        f"Статус: {d.status}\n"
        f"Комментарий: {_esc(d.comment) or '-'}"
    )
    await cb.message.edit_text(text, reply_markup=kb.distribution_card_kb(d))


@router.callback_query(kb.DistCb.filter())
async def dist_action(cb: CallbackQuery, callback_data: kb.DistCb, storage: Storage):
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
                reply_markup=kb.confirm_delete_dist_kb(dist_id),
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
    except Exception as e:  # например, "message is not modified"
        if "not modified" in str(e):
            await cb.answer("Без изменений")
        else:
            raise
