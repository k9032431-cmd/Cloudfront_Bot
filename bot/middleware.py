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
