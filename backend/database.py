"""База лиц: построение, хранение и сравнение embedding'ов.

Все тяжёлые операции (DeepFace) выполняются лениво и могут занимать десятки
секунд (первая загрузка TensorFlow), поэтому UI вызывает их из фонового потока.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import os
import pickle
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

import config

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]


class NoFaceDetected(Exception):
    """На изображении не найдено лицо."""


class ModelUnavailable(RuntimeError):
    """DeepFace/TensorFlow не удалось загрузить."""


_deepface = None
_deepface_lock = threading.Lock()


def fake_ai_enabled() -> bool:
    """Режим без TensorFlow: детерминированные embedding'и из пикселей.

    Нужен для демонстрации интерфейса и автотестов: ``FACELOCK_FAKE_AI=1``.
    """
    return os.environ.get("FACELOCK_FAKE_AI", "").strip().lower() in ("1", "true", "yes", "on")


def _missing_module_hint(module: str) -> str:
    """Понятный текст вместо голого ModuleNotFoundError."""
    if module.startswith("werkzeug"):
        return (
            "DeepFace не может загрузиться: не хватает модуля werkzeug "
            "(он не указан в его зависимостях). Исправление: "
            "python -m pip install werkzeug"
        )
    if module.startswith("onnxruntime"):
        return (
            "DeepFace скачался, но без движка onnxruntime. Исправление: "
            "python -m pip install onnxruntime  (или python install_ai.py)"
        )
    return (
        f"Для распознавания не хватает модуля «{module}». "
        "Исправление: python install_ai.py — он доставит всё нужное"
    )


def _cv2():
    try:
        import cv2
    except Exception as exc:  # pragma: no cover
        raise ModelUnavailable(f"OpenCV не установлен: {exc}") from exc
    return cv2


def _load_deepface():
    """Импортирует DeepFace один раз (медленно: тянет TensorFlow)."""
    global _deepface
    if _deepface is not None:
        return _deepface
    with _deepface_lock:
        if _deepface is None:
            try:
                from deepface import DeepFace  # noqa: PLC0415

                DeepFace.build_model(config.SETTINGS.model_name)
                _deepface = DeepFace
            except ModuleNotFoundError as exc:
                module = exc.name or str(exc)
                raise ModelUnavailable(_missing_module_hint(module)) from exc
            except Exception as exc:
                raise ModelUnavailable(
                    "Не удалось загрузить DeepFace. Запустите: python install_ai.py. "
                    f"Подробности: {type(exc).__name__}: {exc}"
                ) from exc
    return _deepface


def is_model_ready() -> bool:
    return _deepface is not None or fake_ai_enabled()


# --------------------------------------------------------------------- embedding
def _fake_embedding(image) -> np.ndarray:
    """Дешёвый псевдо-embedding: уменьшенное изображение как вектор."""
    cv = _cv2()
    if isinstance(image, (str, Path)):
        image = _read_image(Path(image))
    gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
    small = cv.resize(gray, (24, 24), interpolation=cv.INTER_AREA).astype(np.float32)
    small = small - small.mean()
    norm = float(np.linalg.norm(small)) or 1.0
    return (small / norm).ravel()


def _read_image(path: Path) -> np.ndarray:
    cv = _cv2()
    data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    image = cv.imdecode(data, cv.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Не удалось прочитать изображение: {path.name}")
    return image


def embedding(image, model_name: str | None = None, enforce_detection: bool | None = None) -> np.ndarray:
    """Считает embedding лица на кадре (numpy BGR) или в файле.

    Бросает :class:`NoFaceDetected`, если лица нет, и :class:`ModelUnavailable`,
    если модель не загрузилась.
    """
    if fake_ai_enabled():
        return _fake_embedding(image)

    settings = config.SETTINGS
    model_name = model_name or settings.model_name
    if enforce_detection is None:
        enforce_detection = settings.enforce_detection

    DeepFace = _load_deepface()
    try:
        representations = DeepFace.represent(
            img_path=image,
            model_name=model_name,
            detector_backend=settings.detector_backend,
            enforce_detection=enforce_detection,
        )
    except ValueError as exc:
        if "face could not be detected" in str(exc).lower():
            raise NoFaceDetected("Лицо не обнаружено") from exc
        raise
    except Exception as exc:  # pragma: no cover - зависит от модели
        raise ModelUnavailable(f"Ошибка распознавания: {exc}") from exc

    if not representations:
        raise NoFaceDetected("Либо лицо не обнаружено")

    def area(rep: dict) -> int:
        box = rep.get("facial_area") or {}
        return int(box.get("w", 0)) * int(box.get("h", 0))

    best = max(representations, key=area)
    return np.asarray(best["embedding"], dtype=np.float32).ravel()


def embedding_from_path(path: Path) -> np.ndarray:
    return embedding(_read_image(Path(path)))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Косинусное расстояние (0 — одинаковые, 2 — противоположные)."""
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0.0:
        return 1.0
    similarity = float(np.dot(a, b) / denominator)
    return 1.0 - similarity


def best_distance(candidate: np.ndarray, database: list[np.ndarray]) -> float:
    if not database:
        return 1.0
    return min(cosine_distance(candidate, known) for known in database)


def is_known(candidate: np.ndarray, database: list[np.ndarray], threshold: float | None = None) -> tuple[bool, float]:
    threshold = config.SETTINGS.threshold if threshold is None else threshold
    distance = best_distance(candidate, database)
    return distance <= threshold, distance


# ------------------------------------------------------------------ файлы базы
_db_state_cache: dict[str, object] = {"key": None, "value": False, "at": 0.0}
_DB_CACHE_TTL = 5.0


def has_database() -> bool:
    """Есть ли непустая база embedding'ов.

    Результат кешируется по (размер, mtime) файла: интерфейс спрашивает это
    несколько раз в секунду, а читать pickle каждый раз незачем.
    """
    path = config.DB_PATH
    try:
        stat = path.stat()
    except OSError:
        return False
    if stat.st_size == 0:
        return False

    key = (str(path), stat.st_size, stat.st_mtime)
    now = time.monotonic()
    if _db_state_cache["key"] == key and now - float(_db_state_cache["at"]) < _DB_CACHE_TTL:
        return bool(_db_state_cache["value"])

    try:
        value = bool(load_embeddings())
    except Exception:
        value = False
    _db_state_cache.update(key=key, value=value, at=now)
    return value


def _invalidate_db_cache() -> None:
    _db_state_cache["key"] = None


def load_embeddings() -> list[np.ndarray]:
    path = config.DB_PATH
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with open(path, "rb") as file:
            data = pickle.load(file)
    except Exception as exc:
        logger.warning("Не удалось прочитать базу %s: %s", path, exc)
        return []

    if isinstance(data, dict):  # запас на будущие форматы
        data = data.get("embeddings", [])
    result: list[np.ndarray] = []
    for item in data or []:
        try:
            array = np.asarray(item, dtype=np.float32).ravel()
            if array.size:
                result.append(array)
        except Exception:
            continue
    return result


def save_embeddings(embeddings: list[np.ndarray]) -> Path:
    path = config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as file:
        pickle.dump([np.asarray(e, dtype=np.float32).ravel() for e in embeddings], file)
    _invalidate_db_cache()
    return path


def clear_database() -> None:
    try:
        config.DB_PATH.unlink(missing_ok=True)
        _invalidate_db_cache()
    except Exception as exc:  # pragma: no cover
        logger.warning("Не удалось удалить базу: %s", exc)


# --------------------------------------------------------------------- фотографии
def list_photos() -> list[Path]:
    if not config.IMAGE_DIR.exists():
        return []
    files = [
        path
        for path in config.IMAGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in config.IMAGE_SUFFIXES
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def add_photo(image, prefix: str = "owner") -> Path:
    """Сохраняет кадр (numpy BGR) или байты изображения в папку лиц."""
    cv = _cv2()
    config.IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    path = config.IMAGE_DIR / f"{prefix}_{stamp}.jpg"

    if isinstance(image, (bytes, bytearray)):
        raw = np.frombuffer(bytes(image), dtype=np.uint8)
        decoded = cv.imdecode(raw, cv.IMREAD_COLOR)
        if decoded is None:
            raise ValueError("Не удалось прочитать изображение")
        image = decoded

    frame = np.asarray(image)
    ok, buffer = cv.imencode(".jpg", frame, [int(cv.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise ValueError("Не удалось закодировать кадр в JPEG")
    path.write_bytes(buffer.tobytes())
    return path


def import_photo_file(source: Path, prefix: str = "import") -> Path:
    """Копирует выбранный пользователем файл в папку лиц."""
    source = Path(source)
    if source.suffix.lower() not in config.IMAGE_SUFFIXES:
        raise ValueError(f"Формат {source.suffix} не поддерживается, нужен JPG или PNG")
    frame = _read_image(source)
    return add_photo(frame, prefix=prefix)


def import_photo_bytes(data: bytes, name: str = "", prefix: str = "import") -> Path:
    """Сохраняет фотографию, полученную как байты.

    Нужно для веб- и мобильной версии: там ``FilePicker`` не отдаёт путь к
    файлу на диске, а только его содержимое.
    """
    cv = _cv2()
    suffix = Path(name).suffix.lower()
    if suffix and suffix not in config.IMAGE_SUFFIXES:
        raise ValueError(f"Формат {suffix} не поддерживается, нужен JPG или PNG")

    raw = np.frombuffer(bytes(data), dtype=np.uint8)
    frame = cv.imdecode(raw, cv.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Не удалось прочитать изображение")
    return add_photo(frame, prefix=prefix)


def delete_photo(path: Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover
        logger.warning("Не удалось удалить фото %s: %s", path, exc)


# ------------------------------------------------------------------- сборка базы
@dataclass
class BuildReport:
    total: int = 0
    built: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.built > 0

    def summary(self) -> str:
        text = f"Обработано фото: {self.built} из {self.total}"
        if self.skipped:
            first = self.skipped[0]
            text += f". Пропущено: {len(self.skipped)} (например, {first[0]}: {first[1]})"
        return text


def build_database(progress: ProgressCallback | None = None) -> BuildReport:
    """Строит базу embedding'ов из фотографий в ``data/known_face``."""
    photos = list_photos()
    report = BuildReport(total=len(photos))
    if not photos:
        if progress:
            progress(0.0, "В папке нет фотографий")
        return report

    embeddings: list[np.ndarray] = []
    for index, photo in enumerate(photos, start=1):
        if progress:
            progress((index - 1) / len(photos), f"Обработка {index}/{len(photos)}: {photo.name}")
        try:
            embeddings.append(embedding_from_path(photo))
            report.built += 1
        except NoFaceDetected:
            report.skipped.append((photo.name, "лицо не найдено"))
        except Exception as exc:
            report.skipped.append((photo.name, str(exc)[:120]))

    if embeddings:
        save_embeddings(embeddings)
    if progress:
        progress(1.0, report.summary())
    return report


# --------------------------------------------------------------------- снимки
def save_snapshot(frame) -> Path | None:
    """Сохраняет снимок постороннего в block_users."""
    cv = _cv2()
    try:
        config.BLOCK_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
        path = config.BLOCK_DIR / f"block_user_{stamp}.jpg"
        ok, buffer = cv.imencode(".jpg", np.asarray(frame), [int(cv.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return None
        path.write_bytes(buffer.tobytes())
        return path
    except Exception as exc:  # pragma: no cover
        logger.warning("Не удалось сохранить снимок: %s", exc)
        return None


def list_snapshots() -> list[Path]:
    if not config.BLOCK_DIR.exists():
        return []
    files = [
        path
        for path in config.BLOCK_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in config.IMAGE_SUFFIXES
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def clear_snapshots() -> int:
    removed = 0
    for path in list_snapshots():
        try:
            path.unlink()
            removed += 1
        except Exception:
            continue
    return removed


# ------------------------------------------------------------------- утилиты UI
def frame_to_data_uri(frame, width: int = 320, quality: int = 70) -> str | None:
    """Кадр → data:image/jpeg;base64,... для ft.Image."""
    cv = _cv2()
    try:
        frame = np.asarray(frame)
        if frame.ndim != 3:
            return None
        height, actual_width = frame.shape[:2]
        if actual_width > width:
            new_height = int(height * width / actual_width)
            frame = cv.resize(frame, (width, new_height), interpolation=cv.INTER_AREA)
        ok, buffer = cv.imencode(".jpg", frame, [int(cv.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return None
        encoded = base64.b64encode(buffer.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        return None


def path_to_data_uri(path: Path, width: int = 240, quality: int = 70) -> str | None:
    try:
        return frame_to_data_uri(_read_image(Path(path)), width=width, quality=quality)
    except Exception:
        return None


def database_summary() -> dict:
    embeddings = load_embeddings()
    photos = list_photos()
    return {
        "exists": bool(embeddings),
        "embeddings": len(embeddings),
        "photos": len(photos),
        "snapshots": len(list_snapshots()),
        "db_path": str(config.DB_PATH),
        "image_dir": str(config.IMAGE_DIR),
    }
