import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import load_config
from bot.handlers import router
from bot.middleware import AccessMiddleware
from bot.storage import Storage


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    if not config.allowed_users:
        logging.warning("ALLOWED_USERS пуст — бот никого не пустит. Напишите боту /start, чтобы узнать свой ID.")

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp["storage"] = Storage(config.db_path, config.encryption_key)

    access = AccessMiddleware(config.allowed_users)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="create", description="Создать CloudFront"),
        BotCommand(command="list", description="Мои CloudFront"),
        BotCommand(command="accounts", description="Аккаунты AWS"),
        BotCommand(command="cancel", description="Отменить действие"),
        BotCommand(command="help", description="Помощь"),
    ])
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
