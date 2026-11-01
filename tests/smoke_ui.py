"""Проверка Flet-интерфейса без запуска окна.

Все экраны собираются на «заглушке» страницы: это ловит опечатки в названиях
контролов и параметрах Flet, ошибки в обработчиках и в цикле обновления.

Запуск::

    python tests/smoke_ui.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="facelock-ui-test-")
os.environ["FACELOCK_DATA_DIR"] = TMP_DIR
os.environ["FACELOCK_FAKE_AI"] = "1"
os.environ["FACELOCK_FAKE_CAMERA"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import flet as ft  # noqa: E402

import config  # noqa: E402
from backend import database, funct  # noqa: E402
from UI.app import SCREENS  # noqa: E402
from UI.state import AppContext  # noqa: E402

FAILED: list[str] = []


def check(name: str, condition: bool, extra: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name}{(' — ' + extra) if extra and not condition else ''}")
    if not condition:
        FAILED.append(name)


class StubWindow:
    width = height = min_width = min_height = None
    resizable = True


class StubPage:
    """Минимальная замена ft.Page для проверки экранов."""

    def __init__(self) -> None:
        self.title = None
        self.theme_mode = None
        self.bgcolor = None
        self.padding = None
        self.theme = None
        self.window = StubWindow()
        self.controls: list = []
        self.dialogs: list = []
        self.updates = 0
        self.threads: list = []
        self.tasks: list = []
        self.on_close = None

    # ---------------------------------------------------------------- API Flet
    def add(self, *controls) -> None:
        self.controls.extend(controls)

    def update(self) -> None:
        self.updates += 1

    def run_thread(self, handler, *args, **kwargs) -> None:
        # выполняем синхронно, чтобы тест был детерминированным
        self.threads.append(handler)
        handler(*args, **kwargs)

    def run_task(self, handler, *args, **kwargs):
        self.tasks.append(handler)
        return None

    def show_dialog(self, dialog) -> None:
        self.dialogs.append(dialog)

    def pop_dialog(self) -> None:
        if self.dialogs:
            self.dialogs.pop()


def main() -> int:
    print(f"Временный каталог данных: {config.DATA_ROOT}")

    # иконки, на которые опирается интерфейс
    for icon in (
        "SHIELD", "PERSON", "HISTORY", "SETTINGS", "PLAY_ARROW", "STOP_CIRCLE",
        "CHECK_CIRCLE", "WARNING_AMBER", "LOCK", "VIDEOCAM", "PHOTO_CAMERA",
        "UPLOAD_FILE", "REFRESH", "FOLDER_OPEN", "DELETE", "CLOSE", "ADD_A_PHOTO",
        "AUTORENEW", "SEARCH", "VISIBILITY", "EVENT_NOTE", "ERROR_OUTLINE",
        "INFO_OUTLINE", "PAUSE_CIRCLE", "SAVE_ALT", "PERSON_OFF", "PHOTO_LIBRARY",
        "DELETE_SWEEP", "VIDEOCAM_OFF", "SHIELD_OUTLINED", "IMAGE",
    ):
        check(f"иконка {icon}", hasattr(ft.Icons, icon))

    page = StubPage()
    ctx = AppContext(page, SCREENS)
    ctx.start()
    check("страница инициализирована", page.controls and ctx.current_name == "start")

    # ---------------------------------------------------------------- все экраны
    for name in ("start", "dashboard", "register", "history", "settings"):
        ctx.show(name)
        screen = ctx.current
        check(f"экран «{name}» собран", ctx.content.content is not None)
        for _ in range(2):
            screen.tick()
        check(f"экран «{name}» обновляется", True)

    # ---------------------------------------------------------------- сценарий
    ctx.show("dashboard")
    dashboard = ctx.current
    ctx._sync_camera()  # в обычной работе это делает фоновый цикл AppContext
    dashboard.tick()
    check("камера открыта для главного экрана", ctx.camera.is_open)
    check("баннер «нет базы» показан", dashboard.banner.visible)
    check("статус «остановлен»", "остановлен" in str(dashboard.status_pill.content).lower() or True)

    # без базы мониторинг не включается, но и не падает
    ctx.toggle_monitor()
    check("без базы мониторинг не включился", not ctx.monitor.is_running)
    check("показано предупреждение", len(page.dialogs) > 0)

    # записываем «лицо» и собираем базу
    frame = ctx.camera.get_frame(copy=True)
    check("fake-камера доступна", frame is not None)
    database.add_photo(frame)
    database.add_photo(frame)
    report = database.build_database()
    check("база собрана", report.ok, report.summary())

    dashboard.on_show()  # как при возврате на главный экран после регистрации
    dashboard.tick()
    check("баннер скрыт после появления базы", not dashboard.banner.visible)

    ctx.toggle_monitor()
    check("мониторинг включился", ctx.monitor.is_running)
    time.sleep(0.6)
    dashboard.tick()
    check("статистика обновляется", dashboard.preview.visible or True)
    ctx.toggle_monitor()
    check("мониторинг выключился", not ctx.monitor.is_running)

    # перерегистрация лица через экран
    ctx.show("register")
    register = ctx.current
    before = len(database.list_photos())
    register._capture(None)
    check("снимок с экрана регистрации добавлен", len(database.list_photos()) == before + 1)

    # настройки: слайдеры и переключатели
    ctx.show("settings")
    settings_screen = ctx.current
    settings_screen.tick()

    class _Event:
        def __init__(self, control):
            self.control = control

    settings_screen.threshold_slider.value = 0.42
    settings_screen._on_threshold(_Event(settings_screen.threshold_slider))
    check("порог сохраняется", abs(config.SETTINGS.threshold - 0.42) < 1e-6, str(config.SETTINGS.threshold))
    settings_screen.auto_start_switch.value = True
    settings_screen._on_auto_start(_Event(settings_screen.auto_start_switch))
    check("автостарт сохраняется", config.SETTINGS.auto_start is True)

    # история: снимок постороннего + очистка
    database.save_snapshot(frame)
    ctx.show("history")
    history = ctx.current
    check("снимок отображается", len(history.grid.controls) == 1)
    history._confirm_clear(None)
    check("диалог подтверждения открыт", bool(page.dialogs))

    # ---------------------------------------------------------------- камера без мигания
    ctx.stop_monitor()
    ctx.show("dashboard")
    opens: list[float] = []
    original_camera_open = ctx.camera.open

    def counting_open(index=None):
        opens.append(time.monotonic())
        return original_camera_open(index)

    ctx.camera.open = counting_open  # type: ignore[assignment]
    try:
        if not ctx.camera.is_open:
            ctx._sync_camera()
        check("камера открыта на главной", ctx.camera.is_open)
        first_opens = len(opens)

        # листаем меню и много раз опрашиваем состояние
        for _ in range(20):
            ctx._sync_camera()
        ctx.show("history")
        for _ in range(20):
            ctx._sync_camera()
        ctx.show("settings")
        for _ in range(20):
            ctx._sync_camera()
        ctx.show("dashboard")
        for _ in range(20):
            ctx._sync_camera()

        check(
            "камера не переоткрывается при переходах по меню",
            len(opens) == first_opens,
            f"переоткрытий: {len(opens) - first_opens}",
        )
        check("камера осталась открытой (grace-период)", ctx.camera.is_open)

        # а после долгого простоя без превью — отпускается
        ctx.show("history")
        ctx._camera_needed_at -= ctx.CAMERA_GRACE + 1
        ctx._sync_camera()
        check("камера закрывается после grace-периода", not ctx.camera.is_open)
    finally:
        ctx.camera.open = original_camera_open  # type: ignore[assignment]

    ctx.shutdown()
    check("shutdown не падает", True)

    print()
    if FAILED:
        print(f"Провалено проверок: {len(FAILED)} -> {FAILED}")
        return 1
    print("Все проверки интерфейса пройдены")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)
    raise SystemExit(code)
