"""Работа с веб-камерой.

Один объект ``CameraManager`` на всё приложение: и интерфейс, и мониторинг
читают последний кадр из одного и того же захвата, поэтому камера не
открывается дважды (на macOS/Windows второе открытие обычно падает).

Захват идёт в отдельном потоке: поток постоянно «вычитывает» кадры, чтобы в
буфере камеры не копились устаревшие кадры, а потребители забирают последний.

Для разработки без камеры можно выставить ``FACELOCK_FAKE_CAMERA=1`` —
тогда генерируются синтетические кадры.
"""

from __future__ import annotations

import logging
import os
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)


def _fake_camera_enabled() -> bool:
    return os.environ.get("FACELOCK_FAKE_CAMERA", "").strip().lower() in ("1", "true", "yes", "on")


class CameraError(RuntimeError):
    """Камера недоступна."""


class CameraManager:
    """Потокобезопасный доступ к веб-камере."""

    def __init__(self) -> None:
        self._capture = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._opening = False
        # открытие/закрытие устройства сериализуем: параллельные open() приводят
        # к тому, что камера переоткрывается по несколько раз в секунду и её
        # индикатор непрерывно мигает
        self._open_lock = threading.Lock()
        self.index: int | None = None
        self.error: str | None = None
        self.fake = _fake_camera_enabled()

    # ------------------------------------------------------------------ состояние
    @property
    def is_open(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_opening(self) -> bool:
        return self._opening

    # ------------------------------------------------------------------ открытие
    def open(self, index: int | None = None) -> bool:
        """Открывает камеру. Возвращает True в случае успеха.

        Метод идемпотентен: повторный вызов для уже открытой камеры ничего не
        делает, а параллельные вызовы сериализуются мьютексом.
        """
        index = 0 if index is None else int(index)
        with self._open_lock:
            if self.is_open and self.index == index:
                return True
            if self._opening:
                return False
            self._opening = True
            try:
                return self._open_locked(index)
            finally:
                self._opening = False

    def _open_locked(self, index: int) -> bool:
        self._close_locked()
        self.error = None
        try:
            if self.fake:
                self._thread = threading.Thread(target=self._fake_loop, name="facelock-camera", daemon=True)
            else:
                try:
                    import cv2
                except Exception as exc:  # pragma: no cover
                    self.error = f"OpenCV не установлен: {exc}"
                    raise CameraError(self.error) from exc

                capture = cv2.VideoCapture(index)
                if not capture.isOpened():
                    capture.release()
                    self.error = f"Камера {index} не найдена или занята другим приложением"
                    raise CameraError(self.error)

                capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self._capture = capture
                self._thread = threading.Thread(
                    target=self._loop, args=(capture,), name="facelock-camera", daemon=True
                )

            self.index = index
            self._stop.clear()
            self._thread.start()
            logger.info("Камера %s открыта (fake=%s)", index, self.fake)
            return True
        except CameraError:
            raise
        except Exception as exc:
            self.error = str(exc)
            raise CameraError(f"Не удалось открыть камеру: {exc}") from exc

    # ------------------------------------------------------------------ закрытие
    def close(self) -> None:
        with self._open_lock:
            self._close_locked()

    def _close_locked(self) -> None:
        self._stop.set()

        # сначала отпускаем устройство: после release() поток чтения быстро
        # завершится, и камера не останется занятой
        capture, self._capture = self._capture, None
        if capture is not None:
            try:
                capture.release()
            except Exception:  # pragma: no cover
                pass

        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

        with self._lock:
            self._frame = None

    # ------------------------------------------------------------------ кадры
    def get_frame(self, copy: bool = True) -> np.ndarray | None:
        """Возвращает последний кадр (BGR, numpy) или None."""
        with self._lock:
            frame = self._frame
        if frame is None:
            # камере нужно время на первый кадр
            for _ in range(10):
                time.sleep(0.05)
                with self._lock:
                    frame = self._frame
                if frame is not None:
                    break
        if frame is None:
            return None
        return frame.copy() if copy else frame

    def snapshot(self) -> np.ndarray | None:
        return self.get_frame(copy=True)

    # ------------------------------------------------------------------ потоки
    def _loop(self, capture) -> None:
        misses = 0
        while not self._stop.is_set():
            try:
                ok, frame = capture.read()
            except Exception as exc:  # pragma: no cover
                self.error = str(exc)
                break
            if not ok or frame is None:
                misses += 1
                if misses > 60:
                    self.error = "Камера перестала отдавать кадры"
                    break
                time.sleep(0.05)
                continue
            misses = 0
            with self._lock:
                self._frame = frame
            time.sleep(0.01)
        logger.info("Поток камеры остановлен")

    def _fake_loop(self) -> None:
        """Синтетические кадры для тестов и демо без камеры."""
        height, width = 480, 640
        base = np.zeros((height, width, 3), dtype=np.uint8)
        for y in range(height):
            base[y, :, :] = (40 + y // 8, 46 + y // 10, 58)

        phase = 0.0
        while not self._stop.is_set():
            frame = base.copy()
            # «лицо»: круг светлого цвета, слегка смещается — embedding стабилен
            cx = int(width / 2 + 10 * np.sin(phase))
            cy = int(height / 2 + 6 * np.cos(phase * 0.7))
            import cv2

            cv2.circle(frame, (cx, cy), 110, (188, 200, 214), -1)
            cv2.circle(frame, (cx - 38, cy - 30), 12, (60, 60, 60), -1)
            cv2.circle(frame, (cx + 38, cy - 30), 12, (60, 60, 60), -1)
            cv2.ellipse(frame, (cx, cy + 35), (40, 20), 0, 0, 180, (90, 90, 90), 3)
            noise = np.random.randint(0, 8, frame.shape, dtype=np.uint8)
            frame = cv2.add(frame, noise)
            with self._lock:
                self._frame = frame
            phase += 0.4
            self._stop.wait(0.05)
