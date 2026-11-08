from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .aws_service import DistributionInfo
from .storage import Account

BTN_CREATE = "☁️ Создать CloudFront"
BTN_LIST = "📋 Мои CloudFront"
BTN_ACCOUNTS = "👥 Аккаунты"
BTN_HELP = "ℹ️ Помощь"
BTN_CANCEL = "❌ Отмена"


class AccCb(CallbackData, prefix="acc"):
    action: str  # open | select | delete | delete_yes | add | back
    id: int = 0


class DistCb(CallbackData, prefix="dist"):
    action: str  # open | enable | disable | delete | delete_yes | refresh | back
    id: str = ""


class CreateCb(CallbackData, prefix="create"):
    step: str  # proto | cache | confirm | cancel
    value: str = ""


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CREATE), KeyboardButton(text=BTN_LIST)],
            [KeyboardButton(text=BTN_ACCOUNTS), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


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


def confirm_delete_account_kb(acc_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data=AccCb(action="delete_yes", id=acc_id))
    kb.button(text="Нет", callback_data=AccCb(action="open", id=acc_id))
    return kb.as_markup()


def protocol_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="HTTP only (порт 80)", callback_data=CreateCb(step="proto", value="http-only"))
    kb.button(text="HTTPS only (порт 443)", callback_data=CreateCb(step="proto", value="https-only"))
    kb.button(text="Match viewer", callback_data=CreateCb(step="proto", value="match-viewer"))
    kb.button(text="❌ Отмена", callback_data=CreateCb(step="cancel"))
    kb.adjust(1)
    return kb.as_markup()


def caching_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Без кэширования (CachingDisabled)", callback_data=CreateCb(step="cache", value="off"))
    kb.button(text="С кэшированием (CachingOptimized)", callback_data=CreateCb(step="cache", value="on"))
    kb.button(text="❌ Отмена", callback_data=CreateCb(step="cancel"))
    kb.adjust(1)
    return kb.as_markup()


def confirm_create_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Создать", callback_data=CreateCb(step="confirm"))
    kb.button(text="❌ Отмена", callback_data=CreateCb(step="cancel"))
    return kb.as_markup()


def distributions_kb(items: list[DistributionInfo]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in items:
        icon = "🟢" if d.enabled else "⚪️"
        if d.status != "Deployed":
            icon = "⏳"
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


def confirm_delete_dist_kb(dist_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data=DistCb(action="delete_yes", id=dist_id))
    kb.button(text="Нет", callback_data=DistCb(action="open", id=dist_id))
    return kb.as_markup()
