"""Базовый класс экрана.

Экран — это объект с методом :meth:`Screen.build`, который возвращает готовый
контрол, и методом :meth:`Screen.tick`, который вызывается приложением примерно
8 раз в секунду. В ``tick`` экран сам обновляет значения своих контролов —
``page.update()`` вызывает уже ``AppContext``.
"""

from __future__ import annotations

import logging
import time

import flet as ft

from backend import database

logger = logging.getLogger(__name__)


class Screen:
    #: нужен ли доступ к камере, пока экран открыт
    wants_camera = False
    #: заголовок для журнала
    name = "screen"

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.page = ctx.page
        self._last_preview = 0.0

    # -------------------------------------------------------------- жизненный цикл
    def build(self) -> ft.Control:  # pragma: no cover - переопределяется
        raise NotImplementedError

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass

    def tick(self) -> None:
        pass

    # ------------------------------------------------------------------ помощники
    def preview_uri(self, width: int = 360, quality: int = 68, interval: float = 0.12) -> str | None:
        """data-uri последнего кадра камеры (с ограничением частоты)."""
        now = time.monotonic()
        if now - self._last_preview < interval:
            return None
        self._last_preview = now
        try:
            frame = self.ctx.camera.get_frame(copy=False)
            if frame is None:
                return None
            return database.frame_to_data_uri(frame, width=width, quality=quality)
        except Exception:
            return None

    def safe(self, handler):
        """Оборачивает обработчик, чтобы исключение не ломало страницу."""

        def wrapper(event):
            try:
                return handler(event)
            except Exception as exc:  # pragma: no cover
                logger.exception("Ошибка обработчика")
                self.ctx.toast(f"Ошибка: {exc}", "#E5484D")
                return None

        return wrapper
