"""ШАБЛОН НОВОГО МОДУЛЯ (добавки).

Как добавить свою функцию:
  1. Скопируйте этот файл:  cp bot/modules/_template.py bot/modules/my_feature.py
     (имя без "_" в начале — иначе модуль не загрузится)
  2. Поменяйте кнопку, команды и обработчики ниже.
  3. Перезапустите бота:  cfbot restart
Кнопка сама появится в главном меню, команда — в меню Telegram, текст HELP — в /help.

Доступно в обработчиках через аргументы (подставляются автоматически):
  storage: Storage  — аккаунты (storage.get_active(user_id) — текущий AWS-аккаунт),
                      storage.db — sqlite-соединение для своих таблиц
  config:  Config   — настройки из .env
  state:   FSMContext — для пошаговых диалогов
Для работы с AWS используйте bot/aws_service.py (там же можно добавить свои функции).
"""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from ..storage import Storage
from ..ui import esc, main_menu

BTN = "🧩 Пример"

ORDER = 500                       # место в меню (меньше — левее/выше)
MENU = [BTN]                      # кнопки главного меню
COMMANDS = [("example", "Пример модуля")]
HELP = "<b>🧩 Пример</b> — показывает текущий аккаунт."

router = Router(name=__name__)


def setup(dp, storage: Storage, config) -> None:
    """Необязательно: вызывается один раз при запуске (например, создать свою таблицу)."""
    # storage.db.execute("CREATE TABLE IF NOT EXISTS my_table (...)")


@router.message(Command("example"))
@router.message(F.text == BTN)
async def example(message: Message, storage: Storage):
    acc = storage.get_active(message.from_user.id)
    await message.answer(
        f"Активный аккаунт: <b>{esc(acc.name) if acc else 'нет'}</b>",
        reply_markup=main_menu(),
    )
