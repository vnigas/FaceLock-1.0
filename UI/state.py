"""Состояние приложения: общая камера, монитор, фоновые задачи и навигация.

Экраны не работают с потоками напрямую. Любая тяжёлая работа (загрузка
TensorFlow, построение базы) запускается через :meth:`AppContext.run_bg`, а
результат забирается из ``ctx.task`` в ``tick()`` нужного экрана, который
выполняется в событийном цикле Flet. Так UI обновляется только из одного
потока — это важно для стабильности Flet.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

import flet as ft

import config
from backend import database
from backend.camera import CameraError, CameraManager
from backend.monitor import FaceMonitor, MonitorEvent, MonitorError

logger = logging.getLogger(__name__)


class BackgroundTask:
    """Фоновая задача с прогрессом, которую отображает экран."""

    def __init__(self, message: str = "") -> None:
        self.message = message
        self.progress: float | None = None
        self.result: Any = None
        self.error: str | None = None
        self.running = True
        self.done = False

    def set_progress(self, value: float | None, message: str | None = None) -> None:
        self.progress = None if value is None else max(0.0, min(1.0, float(value)))
        if message:
            self.message = message


class AppContext:
    """Мостик между экранами, камерой, монитором и Flet-страницей."""

    POLL_INTERVAL = 0.12
    #: сколько секунд камера остаётся открытой, когда на экране её превью больше нет.
    #: Без этого задержка при переходе между меню закрывала и снова открывала
    #: устройство — индикатор камеры при этом мигал.
    CAMERA_GRACE = 45.0
    #: пауза перед повторной попыткой открыть камеру после ошибки
    CAMERA_RETRY = 10.0

    def __init__(self, page: ft.Page, registry: dict[str, type], initial: str = "start") -> None:
        self.page = page
        self.registry = registry
        self.initial_screen = initial if initial in registry else "start"
        self.camera = CameraManager()
        self.monitor = FaceMonitor(self.camera)
        self.recent: deque[MonitorEvent] = deque(maxlen=60)
        self.content = ft.Container(expand=True)
        self.current = None
        self.current_name = ""
        self.task: BackgroundTask | None = None
        self.auto_start_done = False
        self.camera_error: str | None = None
        self._camera_retry_at = 0.0
        self._camera_needed_at = 0.0
        self._camera_opening = False
        self._failures = 0
        self._closed = False

        self.file_picker: ft.FilePicker | None = None
        try:
            # в Flet 1.0 сервис сам регистрируется на текущей странице
            self.file_picker = ft.FilePicker()
        except Exception as exc:  # pragma: no cover
            logger.warning("FilePicker недоступен: %s", exc)

    # ------------------------------------------------------------------ запуск
    def start(self) -> None:
        self.page.add(self.content)
        self.page.run_task(self._loop)
        self.show(self.initial_screen)

    def show(self, name: str, **kwargs) -> None:
        factory = self.registry.get(name)
        if factory is None:
            raise KeyError(f"Неизвестный экран: {name}")
        if self.current is not None:
            try:
                self.current.on_hide()
            except Exception:  # pragma: no cover
                logger.exception("on_hide упал")
        screen = factory(self, **kwargs)
        self.current = screen
        self.current_name = name
        self.content.content = screen.build()
        try:
            screen.on_show()
        except Exception:  # pragma: no cover
            logger.exception("on_show упал")
        self.page.update()

    # ------------------------------------------------------------------ уведомления
    def toast(self, message: str, color: str | None = None) -> None:
        try:
            self.page.show_dialog(
                ft.SnackBar(
                    content=ft.Text(message, size=13, color="#FFFFFF"),
                    bgcolor=color or "#252B36",
                    duration=3500,
                )
            )
        except Exception:  # pragma: no cover
            logger.info("toast: %s", message)

    # ------------------------------------------------------------------ фоновые задачи
    def run_bg(self, function: Callable[[Callable], Any], message: str = "") -> BackgroundTask:
        task = BackgroundTask(message=message)
        self.task = task

        def worker() -> None:
            try:
                task.result = function(task.set_progress)
            except Exception as exc:
                logger.exception("Фоновая задача упала")
                task.error = str(exc)
            finally:
                task.running = False
                task.done = True

        self.page.run_thread(worker)
        return task

    # ------------------------------------------------------------------ мониторинг
    def start_monitor(self) -> bool:
        if self.monitor.is_running:
            return True
        if not database.has_database():
            self.toast("Сначала запишите лицо владельца", "#F2A93B")
            return False
        try:
            self.monitor.start()
            return True
        except MonitorError as exc:
            self.toast(str(exc), "#E5484D")
            return False
        except Exception as exc:  # pragma: no cover
            logger.exception("Не удалось запустить мониторинг")
            self.toast(f"Ошибка запуска: {exc}", "#E5484D")
            return False

    def stop_monitor(self) -> None:
        self.monitor.stop()

    def toggle_monitor(self) -> None:
        if self.monitor.is_running:
            self.stop_monitor()
        else:
            self.start_monitor()

    # ------------------------------------------------------------------ камера
    def _sync_camera(self) -> None:
        """Держит камеру в нужном состоянии, не дёргая устройство зря.

        Камера нужна, когда идёт мониторинг или открыт экран с превью. После
        ухода с такого экрана устройство отпускается не сразу, а через
        ``CAMERA_GRACE`` секунд: иначе листание меню превращается в
        бесконечное «открыл-закрыл», и индикатор камеры мигает.
        """
        now = time.monotonic()
        index = int(config.SETTINGS.camera_index)
        need = self.monitor.is_running or bool(getattr(self.current, "wants_camera", False))

        if need:
            self._camera_needed_at = now

        # пользователь сменил камеру в настройках — переоткрываем один раз
        if self.camera.is_open and self.camera.index != index:
            self.camera.close()
            self.camera_error = None
            self._camera_retry_at = 0.0

        if not need:
            if self.camera.is_open and (now - self._camera_needed_at) > self.CAMERA_GRACE:
                self.camera.close()
            return

        if self.camera.is_open:
            # поток камеры мог умереть сам (выдернули устройство и т.п.)
            self.camera_error = self.camera.error
            if self.camera.error:
                self.camera.close()
                self._camera_retry_at = now + self.CAMERA_RETRY
            return

        if self._camera_opening or self.camera.is_opening or now < self._camera_retry_at:
            return

        self._camera_opening = True

        def open_worker() -> None:
            try:
                self.camera.open(index)
                self.camera_error = None
            except CameraError as exc:
                self.camera_error = str(exc)
                self._camera_retry_at = time.monotonic() + self.CAMERA_RETRY
            except Exception as exc:  # pragma: no cover
                self.camera_error = str(exc)
                self._camera_retry_at = time.monotonic() + self.CAMERA_RETRY
            finally:
                self._camera_opening = False

        self.page.run_thread(open_worker)

    def camera_ready(self) -> bool:
        return self.camera.is_open and self.camera.get_frame(copy=False) is not None

    # ------------------------------------------------------------------ сервисные
    def open_data_folder(self) -> bool:
        path = str(config.DATA_ROOT)
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(path)  # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("Не удалось открыть папку: %s", exc)
            self.toast(f"Не удалось открыть папку: {exc}", "#E5484D")
            return False

    def database_state(self) -> dict:
        return database.database_summary()

    def snapshot_paths(self) -> list[Path]:
        return database.list_snapshots()

    # ------------------------------------------------------------------ цикл опроса
    async def _loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self.POLL_INTERVAL)
            try:
                self._drain_events()
                self._sync_camera()
                screen = self.current
                if screen is not None:
                    screen.tick()
                self.page.update()
                self._failures = 0
            except Exception:
                self._failures += 1
                if self._failures >= 25:
                    logger.exception("Опрос интерфейса остановлен")
                    self._closed = True
                else:
                    logger.debug("Ошибка при обновлении интерфейса", exc_info=True)

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.monitor.events.get_nowait()
            except Exception:
                break
            self.recent.appendleft(event)

    def shutdown(self) -> None:
        self._closed = True
        try:
            self.monitor.stop()
        except Exception:
            pass
        try:
            self.camera.close()
        except Exception:
            pass
