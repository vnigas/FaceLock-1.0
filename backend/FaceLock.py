"""Точка входа консольной версии FaceLock (без интерфейса).

Запуск::

    python backend/FaceLock.py

Логика распознавания живёт в ``backend/monitor.py``, поэтому графический
интерфейс (``main.py``) использует ровно тот же код.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

# чтобы `python backend/FaceLock.py` видел config.py в корне проекта
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from backend.camera import CameraManager, CameraError  # noqa: E402
from backend.monitor import FaceMonitor, KIND_BLOCK, KIND_ERROR, KIND_INTRUDER  # noqa: E402
from backend import database  # noqa: E402

logger = logging.getLogger("facelock")


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(config.LOG_PATH, encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def ensure_database() -> bool:
    """Проверяет базу и при необходимости строит её из фотографий."""
    if database.has_database():
        logger.info("База найдена: %s записей", len(database.load_embeddings()))
        return True

    photos = database.list_photos()
    if not photos:
        logger.error(
            "Нет ни базы, ни фотографий. Положите фото в %s или запишите лицо в интерфейсе.",
            config.IMAGE_DIR,
        )
        return False

    logger.info("Строю базу из %s фотографий…", len(photos))
    report = database.build_database(progress=lambda value, message: logger.info("[%3d%%] %s", int(value * 100), message))
    if not report.ok:
        logger.error("Не удалось построить базу: %s", report.summary())
        return False
    logger.info("Готово: %s лиц в базе", report.built)
    return True


def main() -> int:
    _setup_logging()
    logger.info("FaceLock %s, каталог данных: %s", config.APP_VERSION, config.DATA_ROOT)

    if not ensure_database():
        return 2

    camera = CameraManager()
    try:
        camera.open(config.SETTINGS.camera_index)
    except CameraError as exc:
        logger.error("%s", exc)
        return 3

    monitor = FaceMonitor(camera)
    monitor.start()

    stopping = False

    def handle_signal(signum, frame):  # noqa: ARG001
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except Exception:  # pragma: no cover - Windows
            pass

    logger.info("Мониторинг запущен. Ctrl+C — выход.")
    last_state = None
    try:
        while not stopping:
            try:
                event = monitor.events.get(timeout=0.5)
            except Exception:
                event = None
            if event is not None and event.kind in (KIND_BLOCK, KIND_INTRUDER, KIND_ERROR):
                logger.warning("%s", event.message)

            state = monitor.state()
            if state.state != last_state:
                last_state = state.state
                logger.debug("состояние: %s (%s)", state.state, state.message)
            time.sleep(0.05)
    finally:
        monitor.stop()
        camera.close()
        logger.info("Остановлено")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
