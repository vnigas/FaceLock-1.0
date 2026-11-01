"""Flet-приложение FaceLock.

Запуск (из корня проекта)::

    flet run main.py

Точка входа для сборки: ``main.py`` (``flet build windows main.py``).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import flet as ft

# чтобы приложение находило config.py и пакеты backend/UI даже при запуске
# из другого каталога (flet run UI/app.py, сборка, отладчик)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from UI import theme  # noqa: E402
from UI.screens.dashboard import DashboardScreen  # noqa: E402
from UI.screens.history import HistoryScreen  # noqa: E402
from UI.screens.register import RegisterScreen  # noqa: E402
from UI.screens.settings import SettingsScreen  # noqa: E402
from UI.screens.start import StartScreen  # noqa: E402
from UI.state import AppContext  # noqa: E402

logger = logging.getLogger(__name__)

#: реестр экранов: имя → класс
SCREENS: dict[str, type] = {
    "start": StartScreen,
    "dashboard": DashboardScreen,
    "register": RegisterScreen,
    "history": HistoryScreen,
    "settings": SettingsScreen,
}


def setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(config.LOG_PATH, encoding="utf-8"))
    except Exception:  # pragma: no cover
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def main(page: ft.Page) -> None:
    setup_logging()
    logger.info("FaceLock %s, каталог данных: %s", config.APP_VERSION, config.DATA_ROOT)

    page.title = f"{config.APP_NAME} {config.APP_VERSION}"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = theme.BG
    page.padding = 0
    page.theme = ft.Theme(color_scheme_seed=theme.ACCENT, use_material3=True)

    # оформление окна (в вебе просто игнорируется)
    try:
        page.window.width = 1120
        page.window.height = 780
        page.window.min_width = 900
        page.window.min_height = 640
        page.window.resizable = True
    except Exception:  # pragma: no cover
        logger.debug("Параметры окна недоступны", exc_info=True)

    initial = os.environ.get("FACELOCK_START_SCREEN", "start").strip().lower()
    ctx = AppContext(page, SCREENS, initial=initial)

    def on_close(event) -> None:  # аккуратно гасим потоки камеры и мониторинга
        ctx.shutdown()

    page.on_close = on_close
    ctx.start()


if __name__ == "__main__":
    ft.run(main)
