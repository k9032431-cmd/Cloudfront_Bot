import asyncio
import html
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, ErrorEvent

from bot.config import load_config
from bot.middleware import AccessMiddleware, MenuResetMiddleware
from bot.registry import load_modules
from bot.storage import Storage


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    if not config.admin_ids:
        logging.warning("ADMIN_IDS пуст — бот никого не пустит. Напишите боту /start, чтобы узнать свой ID.")

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    storage = Storage(config.db_path, config.encryption_key)
    dp["storage"] = storage
    dp["config"] = config

    access = AccessMiddleware(config.admin_ids)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.message.outer_middleware(MenuResetMiddleware())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        """Непредвиденная ошибка: пишем в лог и показываем пользователю, а не молчим."""
        logging.exception("Ошибка при обработке: %s", event.exception, exc_info=event.exception)
        text = f"⚠️ Ошибка: {type(event.exception).__name__}: {event.exception}"[:190]
        try:
            if event.update.callback_query:
                await event.update.callback_query.answer(text, show_alert=True)
            elif event.update.message:
                await event.update.message.answer(html.escape(text))
        except Exception:
            pass
        return True

    # Подключаем все модули из bot/modules/
    modules = load_modules(config.disabled_modules)
    commands: list[BotCommand] = []
    admin_commands: list[BotCommand] = []
    for m in modules:
        setup = getattr(m.module, "setup", None)
        if callable(setup):
            setup(dp, storage, config)
        dp.include_router(m.router)
        cmds = [BotCommand(command=c, description=d) for c, d in m.commands]
        admin_commands += cmds
        if not m.admin_only:
            commands += cmds

    await bot.set_my_commands(commands)
    for admin_id in config.admin_ids:  # админам — ещё и админские команды
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            logging.warning("Не удалось задать команды для админа %s: %s", admin_id, e)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
