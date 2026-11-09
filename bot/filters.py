from aiogram.filters import Filter
from aiogram.types import TelegramObject


class IsAdmin(Filter):
    """Пропускает только главных админов (ADMIN_IDS). is_admin кладёт в data AccessMiddleware."""

    async def __call__(self, event: TelegramObject, is_admin: bool = False) -> bool:
        return is_admin
