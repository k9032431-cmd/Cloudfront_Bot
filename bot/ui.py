"""Общие элементы интерфейса, доступные всем модулям."""
import html
from contextvars import ContextVar

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .registry import MODULES

BTN_CANCEL = "❌ Отмена"

# Выставляется AccessMiddleware для каждого входящего события
current_is_admin: ContextVar[bool] = ContextVar("current_is_admin", default=False)


def esc(s: str) -> str:
    return html.escape(str(s))


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню собирается из кнопок загруженных модулей (по 2 в ряд).
    Кнопки модулей с ADMIN_ONLY = True видят только админы."""
    is_admin = current_is_admin.get()
    buttons = [KeyboardButton(text=t) for m in MODULES if is_admin or not m.admin_only for t in m.menu]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(keyboard=rows or [[KeyboardButton(text="/start")]], resize_keyboard=True)


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)
