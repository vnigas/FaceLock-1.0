"""Фоновый мониторинг: сравнение лица с базой и блокировка экрана.

Класс :class:`FaceMonitor` — единственное место, где выполняется цикл проверки.
Он не знает про Flet: интерфейс читает состояние через :meth:`FaceMonitor.state`
и слушает очередь событий. Это позволяет использовать тот же монитор из
консольного запуска (``backend/FaceLock.py``).
"""

from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
import time
from dataclasses import asdict, dataclass

import config
from . import database, funct

logger = logging.getLogger(__name__)

# состояния, которые показывает интерфейс
STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_CHECKING = "checking"
STATE_KNOWN = "known"
STATE_NO_FACE = "no_face"
STATE_INTRUDER = "intruder"
STATE_SCREEN_LOCKED = "screen_locked"
STATE_NO_CAMERA = "no_camera"
STATE_ERROR = "error"

KIND_BLOCK = "block"
KIND_INTRUDER = "intruder"
KIND_INFO = "info"
KIND_ERROR = "error"


class MonitorError(RuntimeError):
    """Не удалось запустить мониторинг."""


@dataclass
class MonitorState:
    """Снимок состояния монитора для интерфейса."""

    running: bool = False
    state: str = STATE_IDLE
    message: str = ""
    distance: float | None = None
    threshold: float = config.THRESHOLD
    checks: int = 0
    blocks: int = 0
    errors: int = 0
    last_check: float = 0.0
    last_block: float = 0.0
    started_at: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class MonitorEvent:
    """Событие для журнала интерфейса."""

    kind: str
    message: str
    timestamp: float
    distance: float | None = None
    snapshot: str | None = None


class FaceMonitor:
    def __init__(self, camera, events: "queue.Queue[MonitorEvent]" | None = None) -> None:
        self.camera = camera
        self.events: queue.Queue[MonitorEvent] = events if events is not None else queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state = MonitorState(threshold=config.SETTINGS.threshold)
        self._embeddings: list = []
        self._last_lock_at = 0.0

    # ------------------------------------------------------------------ состояние
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def state(self) -> MonitorState:
        with self._lock:
            snapshot = MonitorState(**self._state.as_dict())
            snapshot.running = self.is_running
            snapshot.threshold = config.SETTINGS.threshold
        return snapshot

    def _update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self._state, key, value)

    def _emit(self, kind: str, message: str, distance: float | None = None, snapshot: str | None = None) -> None:
        event = MonitorEvent(
            kind=kind,
            message=message,
            timestamp=time.time(),
            distance=distance,
            snapshot=snapshot,
        )
        self.events.put(event)
        logger.info("[%s] %s", kind, message)

    # ------------------------------------------------------------------ запуск/стоп
    def start(self) -> None:
        """Запускает цикл проверки. Бросает MonitorError, если базы нет."""
        if self.is_running:
            return

        embeddings = database.load_embeddings()
        if not embeddings:
            raise MonitorError("База лиц пуста — сначала запишите лицо владельца")

        self._embeddings = embeddings
        self._stop.clear()
        self._last_lock_at = 0.0
        with self._lock:
            self._state = MonitorState(
                running=True,
                state=STATE_STARTING,
                message="Запуск…",
                threshold=config.SETTINGS.threshold,
                started_at=time.time(),
            )
        self._thread = threading.Thread(target=self._run, name="facelock-monitor", daemon=True)
        self._thread.start()
        self._emit(KIND_INFO, f"Мониторинг запущен (лиц в базе: {len(embeddings)})")

    def stop(self, timeout: float = 3.0) -> None:
        if self._thread is None:
            return
        self._stop.set()
        thread = self._thread
        thread.join(timeout=timeout)
        self._thread = None
        self._update(running=False, state=STATE_IDLE, message="Мониторинг остановлен", distance=None)
        self._emit(KIND_INFO, "Мониторинг остановлен")

    def reload_faces(self) -> int:
        """Перечитывает базу (после перерегистрации лица)."""
        self._embeddings = database.load_embeddings()
        return len(self._embeddings)

    # ------------------------------------------------------------------ цикл
    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    self._iteration()
                except Exception as exc:  # pragma: no cover - защита от падения цикла
                    logger.exception("Ошибка в цикле мониторинга")
                    with self._lock:
                        self._state.errors += 1
                    self._update(state=STATE_ERROR, message=f"Ошибка: {exc}")
                    self._emit(KIND_ERROR, f"Ошибка распознавания: {exc}")
                delay = max(0.2, float(config.SETTINGS.check_interval)) - (time.monotonic() - started)
                if delay > 0:
                    self._stop.wait(delay)
        finally:
            self._update(running=False, state=STATE_IDLE, message="Мониторинг остановлен", distance=None)

    def _iteration(self) -> None:
        frame = self.camera.get_frame(copy=True)
        if frame is None:
            self._update(state=STATE_NO_CAMERA, message="Камера недоступна", distance=None)
            self._stop.wait(0.5)
            return

        if funct.is_screen_locked():
            self._update(state=STATE_SCREEN_LOCKED, message="Экран заблокирован — проверка на паузе")
            self._stop.wait(1.0)
            return

        self._update(state=STATE_CHECKING, message="Проверка лица…")

        try:
            candidate = database.embedding(frame)
        except database.NoFaceDetected:
            self._update(state=STATE_NO_FACE, message="Лицо не обнаружено", distance=None)
            with self._lock:
                self._state.last_check = time.time()
            return

        distance = database.best_distance(candidate, self._embeddings)
        threshold = float(config.SETTINGS.threshold)
        now = time.time()
        with self._lock:
            self._state.checks += 1
            self._state.last_check = now
            self._state.distance = distance
            self._state.threshold = threshold

        if distance <= threshold:
            self._update(state=STATE_KNOWN, message="Свой человек в кадре")
        else:
            self._update(state=STATE_INTRUDER, message="Посторонний в кадре")
            self._handle_intruder(frame, distance)

    def _handle_intruder(self, frame, distance: float) -> None:
        settings = config.SETTINGS
        snapshot_path = None
        if settings.save_snapshots:
            path = database.save_snapshot(frame)
            snapshot_path = str(path) if path else None

        now = time.monotonic()
        cooldown = float(settings.lock_cooldown)
        if cooldown and (now - self._last_lock_at) < cooldown:
            self._emit(
                KIND_INTRUDER,
                "Посторонний в кадре (блокировка уже была недавно)",
                distance=distance,
                snapshot=snapshot_path,
            )
            return

        self._last_lock_at = now
        locked = funct.lock_screen()
        with self._lock:
            self._state.blocks += 1
            self._state.last_block = time.time()

        if locked:
            self._emit(KIND_BLOCK, "Экран заблокирован: обнаружен посторонний", distance=distance, snapshot=snapshot_path)
        else:
            self._emit(
                KIND_ERROR,
                "Посторонний в кадре, но заблокировать экран не удалось",
                distance=distance,
                snapshot=snapshot_path,
            )
