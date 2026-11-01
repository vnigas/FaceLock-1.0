"""Проверка backend без TensorFlow и без реальной камеры.

Запуск::

    python tests/smoke_backend.py

Используются режимы ``FACELOCK_FAKE_AI=1`` (embedding'и из пикселей) и
``FACELOCK_FAKE_CAMERA=1`` (синтетические кадры), данные пишутся во временный
каталог — рабочие данные проекта не затрагиваются.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="facelock-test-")
os.environ["FACELOCK_DATA_DIR"] = TMP_DIR
os.environ["FACELOCK_FAKE_AI"] = "1"
os.environ["FACELOCK_FAKE_CAMERA"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import config  # noqa: E402
from backend import database, funct  # noqa: E402
from backend import monitor as monitor_module  # noqa: E402
from backend.camera import CameraManager  # noqa: E402

FAILED: list[str] = []


def check(name: str, condition: bool, extra: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name}{(' — ' + extra) if extra and not condition else ''}")
    if not condition:
        FAILED.append(name)


def wait_for(predicate, timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    print(f"Временный каталог данных: {config.DATA_ROOT}")

    # ---------------------------------------------------------------- пути и файлы
    check("данные пишутся во временный каталог", str(config.DATA_ROOT) == str(Path(TMP_DIR).resolve()))
    check("каталоги созданы", config.IMAGE_DIR.is_dir() and config.BLOCK_DIR.is_dir())
    check("базы пока нет", not database.has_database())

    # ---------------------------------------------------------------- камера
    camera = CameraManager()
    check("fake-камера открылась", camera.open(0))

    # камера не должна переоткрываться: ни при повторном open(), ни при
    # параллельных вызовах из нескольких потоков (иначе мигает индикатор)
    opened: list[int] = []
    original_open_locked = CameraManager._open_locked

    def spy_open_locked(self, index):  # noqa: ANN001
        opened.append(index)
        return original_open_locked(self, index)

    CameraManager._open_locked = spy_open_locked  # type: ignore[assignment]
    try:
        camera.open(0)
        threads = [threading.Thread(target=camera.open, args=(0,)) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        check("повторный open() не переоткрывает камеру", len(opened) == 0, f"переоткрытий: {len(opened)}")
        check("камера после параллельных open() работает", camera.is_open and camera.get_frame() is not None)

        camera.close()
        check("после close() камера закрыта", not camera.is_open and camera.get_frame() is None)
        camera.open(0)
        check("переоткрытие после close() ровно одно", len(opened) == 1, f"переоткрытий: {len(opened)}")
    finally:
        CameraManager._open_locked = original_open_locked  # type: ignore[assignment]

    frame = camera.get_frame(copy=True)
    check("кадр получен", frame is not None and getattr(frame, "shape", (0,))[0] > 0)

    # ---------------------------------------------------------------- регистрация
    for _ in range(3):
        database.add_photo(frame)
        time.sleep(0.02)
    check("фото сохранены", len(database.list_photos()) == 3)

    report = database.build_database()
    check("база построена из 3 фото", report.built == 3 and not report.skipped, report.summary())
    check("has_database() = True", database.has_database())

    embeddings = database.load_embeddings()
    check("embedding'и загружены", len(embeddings) == 3)

    same = database.embedding(frame)
    check("свой кадр ближе порога", database.best_distance(same, embeddings) <= config.SETTINGS.threshold)
    foreign = np.random.RandomState(0).rand(embeddings[0].size).astype(np.float32)
    check("случайный вектор дальше порога", database.best_distance(foreign, embeddings) > config.SETTINGS.threshold)

    # ------------------------------------------------- импорт фото (как из веб-версии)
    import cv2

    ok, buffer = cv2.imencode(".png", frame)
    saved = database.import_photo_bytes(buffer.tobytes(), "photo.png")
    check("импорт фото из байтов (PNG → JPG)", saved.exists() and saved.suffix == ".jpg")

    ok, buffer = cv2.imencode(".jpg", frame)
    saved = database.import_photo_bytes(buffer.tobytes(), "photo.jpg")
    check("импорт фото из байтов (JPG)", saved.exists())

    try:
        database.import_photo_bytes(b"not an image", "photo.jpg")
        rejected_garbage = False
    except ValueError:
        rejected_garbage = True
    check("битые байты отклоняются", rejected_garbage)

    try:
        database.import_photo_bytes(b"x", "photo.heic")
        rejected_heic = False
    except ValueError:
        rejected_heic = True
    check("неподдерживаемый формат отклоняется с понятной ошибкой", rejected_heic)

    # ---------------------------------------------------------------- мониторинг
    lock_calls: list[float] = []
    funct.lock_screen = lambda: (lock_calls.append(time.time()), True)[1]  # type: ignore[assignment]
    funct.is_screen_locked = lambda: False  # type: ignore[assignment]

    config.update_settings(check_interval=0.3, lock_cooldown=0, save_snapshots=True)

    face_monitor = monitor_module.FaceMonitor(camera)
    face_monitor.start()
    check("мониторинг запущен", face_monitor.is_running)
    check(
        "проверки выполняются",
        wait_for(lambda: face_monitor.state().checks >= 2),
        str(face_monitor.state()),
    )
    state = face_monitor.state()
    check("свой человек распознан", state.state in (monitor_module.STATE_KNOWN, monitor_module.STATE_CHECKING), state.state)

    # подменяем распознавание: теперь в кадре всегда «чужой»
    original_embedding = database.embedding
    database.embedding = lambda image, **kwargs: np.random.RandomState(42).rand(embeddings[0].size).astype(np.float32)  # type: ignore[assignment]

    check("обнаружен посторонний", wait_for(lambda: face_monitor.state().state == monitor_module.STATE_INTRUDER))
    check("экран заблокирован", wait_for(lambda: len(lock_calls) >= 1), f"вызовов: {len(lock_calls)}")
    check("счётчик блокировок", face_monitor.state().blocks >= 1)
    check("снимок постороннего сохранён", wait_for(lambda: len(database.list_snapshots()) >= 1))

    kinds = []
    while True:
        try:
            kinds.append(face_monitor.events.get_nowait().kind)
        except Exception:
            break
    check("в журнале есть событие блокировки", monitor_module.KIND_BLOCK in kinds, str(kinds))

    # ---------------------------------------------------------------- cooldown
    config.update_settings(lock_cooldown=600)
    blocks_before = face_monitor.state().blocks
    lock_before = len(lock_calls)
    time.sleep(1.5)
    check("cooldown не даёт блокировать повторно", face_monitor.state().blocks == blocks_before and len(lock_calls) == lock_before)

    face_monitor.stop()
    check("мониторинг остановлен", not face_monitor.is_running)

    # ---------------------------------------------------------------- обслуживание
    snapshot_count = len(database.list_snapshots())
    removed = database.clear_snapshots()
    check("снимки очищены", removed == snapshot_count and not database.list_snapshots())

    database.clear_database()
    check("база удалена", not database.has_database())

    try:
        face_monitor.start()
        started_without_db = True
    except monitor_module.MonitorError:
        started_without_db = False
    check("без базы мониторинг не стартует", not started_without_db)

    camera.close()
    check("камера закрыта", not camera.is_open)

    database.embedding = original_embedding  # type: ignore[assignment]

    print()
    if FAILED:
        print(f"Провалено проверок: {len(FAILED)} -> {FAILED}")
        return 1
    print("Все проверки backend пройдены")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)
    raise SystemExit(code)
