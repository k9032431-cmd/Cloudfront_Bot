"""Автозагрузка модулей (добавок) бота из папки bot/modules/.

Чтобы добавить новую функцию — создайте файл bot/modules/<имя>.py
(можно скопировать bot/modules/_template.py). Файлы, начинающиеся с "_",
не загружаются. Модуль можно выключить через DISABLED_MODULES в .env.

Что модуль может объявить:
    router   : aiogram.Router              — обязательно, обработчики модуля
    MENU     : list[str]                    — кнопки модуля в главном меню
    ORDER    : int                          — порядок (меньше = раньше), по умолчанию 100
    COMMANDS : list[tuple[str, str]]        — команды для меню Telegram: ("cmd", "описание")
    HELP     : str                          — текст для /help
    setup    : callable(dp, storage, config) — необязательная инициализация (свои таблицы и т.п.)
"""
import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from types import ModuleType

from aiogram import Router

from . import modules as modules_pkg

log = logging.getLogger(__name__)


@dataclass
class LoadedModule:
    name: str
    module: ModuleType
    router: Router
    order: int = 100
    menu: list[str] = field(default_factory=list)
    commands: list[tuple[str, str]] = field(default_factory=list)
    help: str = ""


# Заполняется в load_modules(); используется для построения меню и /help
MODULES: list[LoadedModule] = []


def load_modules(disabled: set[str]) -> list[LoadedModule]:
    MODULES.clear()
    for info in pkgutil.iter_modules(modules_pkg.__path__):
        name = info.name
        if name.startswith("_") or name in disabled:
            continue
        mod = importlib.import_module(f"{modules_pkg.__name__}.{name}")
        router = getattr(mod, "router", None)
        if not isinstance(router, Router):
            log.warning("Модуль %s пропущен: нет router", name)
            continue
        MODULES.append(LoadedModule(
            name=name,
            module=mod,
            router=router,
            order=getattr(mod, "ORDER", 100),
            menu=list(getattr(mod, "MENU", [])),
            commands=list(getattr(mod, "COMMANDS", [])),
            help=getattr(mod, "HELP", ""),
        ))
    MODULES.sort(key=lambda m: (m.order, m.name))
    log.info("Загружены модули: %s", ", ".join(m.name for m in MODULES) or "-")
    return MODULES


def menu_buttons() -> list[str]:
    return [btn for m in MODULES for btn in m.menu]
