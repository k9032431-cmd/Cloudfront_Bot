import html
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, TelegramObject, User
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .ui import current_is_admin

log = logging.getLogger(__name__)


class AccessCb(CallbackData, prefix="access"):
    """Кнопки «дать доступ / отклонить» в запросе, который приходит админу."""
    action: str  # grant | deny
    id: int


def display_name(user: User) -> str:
    name = " ".join(x for x in (user.first_name, user.last_name) if x)
    if user.username:
        name = f"{name} (@{user.username})" if name else f"@{user.username}"
    return name[:128]


class AccessMiddleware(BaseMiddleware):
    """Пускает главных админов (ADMIN_IDS из .env) и пользователей, которым админ дал доступ.

    Кладёт в data["is_admin"]. Незнакомым пользователям показывает их ID
    и отправляет админам запрос с кнопкой «✅ Дать доступ».
    """

    REQUEST_COOLDOWN = 600  # не чаще раза в 10 минут от одного пользователя

    def __init__(self, admin_ids: frozenset[int]):
        self.admin_ids = admin_ids
        self._last_request: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = getattr(event, "from_user", None)
        if user is None:
            return None
        storage = data["storage"]
        is_admin = user.id in self.admin_ids
        data["is_admin"] = is_admin
        current_is_admin.set(is_admin)

        if is_admin:
            return await handler(event, data)
        if storage.is_user(user.id):
            storage.update_user_name(user.id, display_name(user))
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещён", show_alert=True)
            return None
        if isinstance(event, Message):
            await event.answer(
                "⛔️ <b>Нет доступа.</b>\n"
                f"Ваш Telegram ID: <code>{user.id}</code>\n\n"
                + ("Запрос отправлен администратору — дождитесь подтверждения."
                   if self.admin_ids else "Администратор не настроен (ADMIN_IDS в .env).")
            )
            await self._notify_admins(data["bot"], user)
        return None

    async def _notify_admins(self, bot: Bot, user: User) -> None:
        now = time.monotonic()
        if now - self._last_request.get(user.id, -1e9) < self.REQUEST_COOLDOWN:
            return
        self._last_request[user.id] = now
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Дать доступ", callback_data=AccessCb(action="grant", id=user.id))
        kb.button(text="❌ Отклонить", callback_data=AccessCb(action="deny", id=user.id))
        for admin_id in self.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    "🔔 <b>Запрос доступа</b>\n\n"
                    f"Пользователь: {html.escape(display_name(user)) or '-'}\n"
                    f"ID: <code>{user.id}</code>",
                    reply_markup=kb.as_markup(),
                )
            except Exception as e:  # админ ещё не писал боту и т.п.
                log.warning("Не удалось уведомить админа %s: %s", admin_id, e)


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
