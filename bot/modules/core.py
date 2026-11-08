"""Базовые команды: /start, /help, /cancel."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..registry import MODULES
from ..storage import Storage
from ..ui import BTN_CANCEL, esc, main_menu

BTN_HELP = "ℹ️ Помощь"

ORDER = 1000  # кнопка «Помощь» — в конце меню
MENU = [BTN_HELP]
COMMANDS = [("start", "Главное меню"), ("cancel", "Отменить действие"), ("help", "Помощь")]
HELP = "/cancel — отменить текущее действие."

router = Router(name="core")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, storage: Storage):
    await state.clear()
    active = storage.get_active(message.from_user.id)
    acc_line = (
        f"Активный аккаунт: <b>{esc(active.name)}</b>" if active
        else "Аккаунтов пока нет — добавьте первый в «👥 Аккаунты»."
    )
    await message.answer(f"👋 Бот для создания AWS CloudFront.\n\n{acc_line}", reply_markup=main_menu())


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: Message):
    parts = [m.help.strip() for m in MODULES if m.help.strip()]
    await message.answer("<b>Как пользоваться ботом</b>\n\n" + "\n\n".join(parts), reply_markup=main_menu())


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu())
