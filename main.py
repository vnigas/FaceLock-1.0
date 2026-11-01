"""Точка входа FaceLock (Flet-интерфейс).

    python main.py              # обычный запуск в настольном окне
    python main.py --web        # запуск в браузере (если окно недоступно)
    flet run main.py            # запуск в режиме отладки Flet
    flet build windows main.py  # сборка приложения (windows/macos/linux/web)

Если чего-то не хватает в окружении, скрипт скажет об этом сразу, а не будет
молча висеть: диагностика — ``python check_env.py``.

Консольная версия без интерфейса — ``python backend/FaceLock.py``.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import flet as ft  # noqa: E402

from UI.app import main  # noqa: E402

INSTALL_HINT = 'python -m pip install "flet[all]==1.0.5"'

#: переменные, которые выставляет `flet run` / `flet build`: в этом случае
#: рантаймом управляет CLI, и проверять наличие flet_desktop не нужно
CLI_ENV_VARS = (
    "FLET_FORCE_WEB_SERVER",
    "FLET_SERVER_PORT",
    "FLET_SERVER_IP",
    "FLET_APP_STORAGE_DATA",
    "FLET_ASSETS_DIR",
)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # pragma: no cover
        return False


def _driven_by_flet_cli() -> bool:
    return any(os.environ.get(var) for var in CLI_ENV_VARS)


def run(web: bool = False, port: int | None = None) -> int:
    # запуск через `flet run` — Flet сам выберет окно или веб-сервер
    if _driven_by_flet_cli():
        ft.run(main)
        return 0

    if web:
        if not _module_available("flet_web"):
            print(
                "Не найден компонент Flet «flet_web», нужный для запуска в браузере.\n"
                f"Установите полный набор: {INSTALL_HINT}",
                file=sys.stderr,
            )
            return 1
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=port or 0)
        return 0

    if not _module_available("flet_desktop"):
        if _module_available("flet_web"):
            print(
                "Настольный рантайм Flet не установлен — открываю приложение в браузере.\n"
                f"Чтобы запускать в окне, установите: {INSTALL_HINT}",
                file=sys.stderr,
            )
            ft.run(main, view=ft.AppView.WEB_BROWSER, port=port or 0)
            return 0
        print(
            "Не найден компонент Flet «flet_desktop».\n"
            f"Установите полный набор пакетов: {INSTALL_HINT}",
            file=sys.stderr,
        )
        return 1

    ft.run(main)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FaceLock — защита экрана по лицу")
    parser.add_argument("--web", action="store_true", help="запустить в браузере вместо окна")
    parser.add_argument("--port", type=int, default=0, help="порт для режима --web")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    raise SystemExit(run(web=args.web, port=args.port or None))
