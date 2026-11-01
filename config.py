"""Общая конфигурация FaceLock.

Один файл настроек и путей для backend и Flet-интерфейса.

Каталог данных (DATA_ROOT) выбирается так:

1. Переменная окружения ``FACELOCK_DATA_DIR`` — если задана (удобно для тестов
   и для переноса данных на другой диск).
2. Каталог проекта — если в него можно писать (обычный запуск из репозитория).
3. Системный каталог приложений — если код упакован сборкой ``flet build`` и
   каталог проекта доступен только для чтения:

   * Windows: ``%APPDATA%\\FaceLock``
   * macOS:   ``~/Library/Application Support/FaceLock``
   * Linux:   ``$XDG_DATA_HOME/FaceLock`` (по умолчанию ``~/.local/share/FaceLock``)

Внутри каталога данных лежат::

    data/known_face/    — фотографии владельца
    data/embeddings.pkl — база embedding'ов
    data/settings.json  — пользовательские настройки
    block_users/        — снимки посторонних
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_NAME = "FaceLock"
APP_VERSION = "1.0.0"

#: модель DeepFace, которой строятся embedding'и
MODEL_NAME = "Facenet512"
#: детектор лиц DeepFace (opencv — самый быстрый и без лишних зависимостей)
DETECTOR_BACKEND = "opencv"

#: поддерживаемые расширения фотографий
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")

#: каталог, в котором лежит код проекта
BASE_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".facelock_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _user_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def resolve_data_root() -> Path:
    """Выбирает каталог для данных приложения (см. docstring модуля)."""
    env = os.environ.get("FACELOCK_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    if _is_writable(BASE_DIR):
        return BASE_DIR
    return _user_data_dir()


DATA_ROOT = resolve_data_root()

DATA_DIR = DATA_ROOT / "data"
IMAGE_DIR = DATA_DIR / "known_face"
DB_PATH = DATA_DIR / "embeddings.pkl"
SETTINGS_PATH = DATA_DIR / "settings.json"
BLOCK_DIR = DATA_ROOT / "block_users"
LOG_PATH = DATA_DIR / "facelock.log"

# обратная совместимость с прежним API config.py
NAME_FOLDER_BLOCK_USERS = str(BLOCK_DIR)
THRESHOLD = 0.30
img_from_cam = "my_photo.jpg"  # оставлено для старых скриптов, не используется


def ensure_dirs() -> None:
    """Создаёт каталоги данных, если их ещё нет."""
    for path in (DATA_DIR, IMAGE_DIR, BLOCK_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_data() -> None:
    """Переносит данные из старой структуры репозитория в DATA_ROOT.

    Старая версия проекта хранила базу в ``backend/embeddings.pkl``, а фото —
    в ``data/known_face`` рядом с кодом. Если сборка читает код из read-only
    каталога, данные нужно один раз скопировать в пользовательский каталог.
    """
    if DATA_ROOT == BASE_DIR:
        return

    legacy_db = BASE_DIR / "backend" / "embeddings.pkl"
    if legacy_db.exists() and not DB_PATH.exists():
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_db, DB_PATH)
            logger.info("База embedding'ов перенесена из %s", legacy_db)
        except Exception as exc:  # pragma: no cover - зависит от ФС
            logger.warning("Не удалось перенести старую базу: %s", exc)

    legacy_photos = BASE_DIR / "data" / "known_face"
    if legacy_photos.is_dir() and legacy_photos.resolve() != IMAGE_DIR.resolve():
        try:
            IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            for file in legacy_photos.iterdir():
                if file.suffix.lower() in IMAGE_SUFFIXES and not (IMAGE_DIR / file.name).exists():
                    shutil.copy2(file, IMAGE_DIR / file.name)
        except Exception as exc:  # pragma: no cover - зависит от ФС
            logger.warning("Не удалось перенести старые фото: %s", exc)


@dataclass
class Settings:
    """Пользовательские настройки (data/settings.json)."""

    #: порог косинусного расстояния: меньше — строже проверка
    threshold: float = THRESHOLD
    #: модель DeepFace
    model_name: str = MODEL_NAME
    #: детектор лиц DeepFace
    detector_backend: str = DETECTOR_BACKEND
    #: индекс камеры (cv2.VideoCapture)
    camera_index: int = 0
    #: пауза между проверками, секунды
    check_interval: float = 1.0
    #: не блокировать экран чаще, чем раз в N секунд
    lock_cooldown: int = 30
    #: сколько фото рекомендуем при регистрации лица
    required_photos: int = 5
    #: запускать мониторинг сразу после нажатия «Старт»
    auto_start: bool = False
    #: сохранять снимки посторонних в block_users
    save_snapshots: bool = True
    #: требовать уверенного обнаружения лица (enforce_detection в DeepFace)
    enforce_detection: bool = True

    # --------------------------------------------------------------- сериализация
    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        clean = {}
        for key, value in (data or {}).items():
            if key not in known:
                continue
            template = getattr(cls, key)
            try:
                clean[key] = type(template)(value)
            except Exception:
                continue
        return cls(**clean)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = Path(path or SETTINGS_PATH)
        try:
            if path.exists():
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("Не удалось прочитать настройки (%s): %s", path, exc)
        return cls()

    def save(self, path: Path | None = None) -> None:
        path = Path(path or SETTINGS_PATH)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - зависит от ФС
            logger.warning("Не удалось сохранить настройки: %s", exc)

    def as_dict(self) -> dict:
        return asdict(self)


#: текущие настройки — единый объект для backend и UI
SETTINGS = Settings.load()


def get_settings() -> Settings:
    return SETTINGS


def update_settings(**kwargs) -> Settings:
    """Меняет поля настроек и сразу сохраняет их на диск."""
    for key, value in kwargs.items():
        if hasattr(SETTINGS, key):
            setattr(SETTINGS, key, value)
    SETTINGS.save()
    return SETTINGS


def reload_settings() -> Settings:
    global SETTINGS
    SETTINGS = Settings.load()
    return SETTINGS


ensure_dirs()
_migrate_legacy_data()
