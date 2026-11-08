from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class AccessMiddleware(BaseMiddleware):
    """Пускает только пользователей из ALLOWED_USERS."""

    def __init__(self, allowed: frozenset[int]):
        self.allowed = allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user and user.id in self.allowed:
            return await handler(event, data)
        text = f"⛔️ Доступ запрещён.\nВаш Telegram ID: <code>{user.id if user else '?'}</code>\nДобавьте его в ALLOWED_USERS в файле .env."
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещён", show_alert=True)
        return None


class MenuResetMiddleware(BaseMiddleware):
    """Нажатие кнопки главного меню прерывает любой незаконченный диалог.

    Благодаря этому модулям не нужно заботиться о том, что текст кнопки
    попадёт, например, в поле «название аккаунта».
    """

    async def __call__(self, handler, event, data):
        from .registry import menu_buttons
        from .ui import BTN_CANCEL

        if isinstance(event, Message) and event.text and (
            event.text in menu_buttons() or event.text == BTN_CANCEL or event.text.startswith("/")
        ):
            state = data.get("state")
            if state is not None and data.get("raw_state") is not None:
                await state.clear()
                data["raw_state"] = None
        return await handler(event, data)
