"""Диагностика окружения FaceLock.

Запуск::

    python check_env.py

Печатает версию Python, какие зависимости установлены (и каких не хватает),
находит ли приложение свои модули и видит ли камеру. Ничего не меняет.
"""

from __future__ import annotations

import importlib.util
import platform
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK = "OK  "
FAIL = "НЕТ "

# модуль → (что это, обязателен ли)
MODULES: list[tuple[str, str, bool]] = [
    ("flet", "интерфейс Flet", True),
    ("flet_cli", "командная строка flet (flet run / flet build)", False),
    ("flet_web", "режим `flet run --web`", False),
    ("flet_desktop", "настольное окно Flet", False),
    ("numpy", "вычисления", True),
    ("cv2", "OpenCV: камера и картинки", True),
    ("deepface", "распознавание лиц", True),
    ("werkzeug", "скрытая зависимость DeepFace (без неё ModuleNotFoundError)", True),
    ("onnxruntime", "движок DeepFace для Facenet512 (TensorFlow не нужен)", True),
    ("tensorflow", "опционально: нужен только для других моделей DeepFace", False),
    ("tf_keras", "опционально, вместе с TensorFlow", False),
    ("scipy", "расстояния (используется DeepFace)", False),
    ("PIL", "Pillow", False),
]

problems: list[str] = []


def module_status(name: str) -> tuple[bool, str]:
    try:
        spec = importlib.util.find_spec(name)
    except Exception as exc:  # pragma: no cover
        return False, str(exc)
    if spec is None:
        return False, ""
    return True, ""


def installed_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name.replace("_", "-"))
    except Exception:
        return "?"


def main() -> int:
    print("=" * 62)
    print("FaceLock — проверка окружения")
    print("=" * 62)
    print(f"Python : {platform.python_version()} ({sys.executable})")
    print(f"Система: {platform.platform()}")
    print(f"Проект : {ROOT}")

    if sys.version_info < (3, 10):
        problems.append("Нужен Python 3.10 или новее")
    # TensorFlow больше не обязателен: Facenet512 считается через onnxruntime,
    # поэтому свежий Python не является проблемой.

    print("\n--- зависимости ---")
    for name, description, required in MODULES:
        found, error = module_status(name)
        if found:
            print(f"[{OK}] {name:<14} {installed_version(name):<12} {description}")
        else:
            print(f"[{FAIL}] {name:<14} {'':<12} {description}")
            if required:
                problems.append(f"Не установлен модуль {name} ({description})")
            elif name.startswith("flet"):
                problems.append(f"Нет пакета {name}: выполните `pip install \"flet[all]==1.0.5\"`")

    print("\n--- файлы проекта ---")
    for relative in ("main.py", "config.py", "UI/app.py", "backend/monitor.py", "pyproject.toml"):
        path = ROOT / relative
        print(f"[{OK if path.exists() else FAIL}] {relative}")

    print("\n--- импорт модулей проекта ---")
    for name in ("config", "backend.database", "backend.monitor", "UI.app"):
        try:
            __import__(name)
            print(f"[{OK}] {name}")
        except Exception as exc:
            print(f"[{FAIL}] {name}: {exc}")
            problems.append(f"Ошибка импорта {name}: {exc}")

    print("\n--- пробный запуск приложения (только импорт) ---")
    for name in ("main", "UI.screens.dashboard", "UI.screens.register", "UI.screens.settings"):
        try:
            __import__(name)
            print(f"[{OK}] {name}")
        except Exception:
            print(f"[{FAIL}] {name}")
            print("      " + traceback.format_exc(limit=6).replace("\n", "\n      ").rstrip())
            problems.append(f"Приложение не запускается: см. traceback для {name}")

    print("\n--- модель распознавания ---")
    if all(module_status(m)[0] for m in ("deepface", "werkzeug", "onnxruntime")):
        try:
            from deepface import DeepFace  # noqa: PLC0415

            import config  # noqa: PLC0415

            DeepFace.build_model(config.SETTINGS.model_name)
            print(f"[{OK}] модель {config.SETTINGS.model_name} загружается")
        except Exception as exc:
            print(f"[{FAIL}] модель не загрузилась: {type(exc).__name__}: {exc}")
            if "werkzeug" in str(exc).lower():
                print("       исправление: python -m pip install werkzeug")
            problems.append("Модель распознавания не загружается — запустите python install_ai.py")
    else:
        print(f"[{FAIL}] нет пакетов для распознавания — запустите: python install_ai.py")

    print("\n--- камера ---")
    try:
        import cv2

        capture = cv2.VideoCapture(0)
        available = capture.isOpened()
        if available:
            ok, frame = capture.read()
            available = bool(ok)
        capture.release()
        print(f"[{OK if available else FAIL}] камера 0 {'доступна' if available else 'не найдена или занята'}")
        if not available:
            problems.append("Камера 0 недоступна: закройте приложения, использующие камеру")
    except Exception as exc:
        print(f"[{FAIL}] камера: {exc}")

    print("\n" + "=" * 62)
    if problems:
        print("Что нужно поправить:")
        for index, problem in enumerate(dict.fromkeys(problems), start=1):
            print(f"  {index}. {problem}")
        print("\nОбычно достаточно:")
        print("  python -m pip install -r requirements.txt   # интерфейс и камера")
        print("  python install_ai.py                        # распознавание лиц")
        print('  python -m pip install "flet[all]==1.0.5"    # если нет flet-desktop/web')
        return 1

    print("Всё на месте. Запуск: python main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
