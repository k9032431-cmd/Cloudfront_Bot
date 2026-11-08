"""Общие элементы интерфейса, доступные всем модулям."""
import html

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .registry import menu_buttons

BTN_CANCEL = "❌ Отмена"


def esc(s: str) -> str:
    return html.escape(str(s))


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню собирается из кнопок всех загруженных модулей (по 2 в ряд)."""
    buttons = [KeyboardButton(text=t) for t in menu_buttons()]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(keyboard=rows or [[KeyboardButton(text="/start")]], resize_keyboard=True)


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)
