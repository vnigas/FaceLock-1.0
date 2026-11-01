#!/usr/bin/env python3
"""Установка и диагностика «мозгов» FaceLock — DeepFace.

Главное, что нужно знать: TensorFlow этому проекту НЕ нужен. Начиная с
DeepFace 0.0.103 модель Facenet512 скачивается в формате ONNX и считается
через onnxruntime — установка занимает ~200 МБ вместо ~800 МБ с TensorFlow.

Скрипт делает три вещи:
  1. проверяет Python и платформу (и говорит, если что-то несовместимо);
  2. ставит deepface и его недокументированную зависимость werkzeug;
  3. проверяет, что модель реально загружается, и сам доставляет
     недостающие модули, если они всплывут.

    python install_ai.py            # поставить всё нужное
    python install_ai.py --check    # только диагностика
    python install_ai.py --with-tf  # дополнительно TensorFlow (не обязательно)

Работает на Windows, macOS и Linux.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import os
import platform
import shutil
import subprocess
import sys

BASE_PKGS = ["deepface>=0.0.103", "werkzeug>=3.0"]
TF_PKGS = ["tensorflow>=2.16.1", "tf-keras>=2.16"]

# Советы под конкретный текст ошибки pip. Ключ — фрагмент вывода (в нижнем регистре).
HINTS: list[tuple[tuple[str, ...], list[str]]] = [
    (
        ("could not find a version", "no matching distribution", "requires-python"),
        [
            "У вашего Python нет готового пакета под эту версию.",
            "Поставьте Python 3.12 и соберите окружение на нём:",
            "  Windows:     py -3.12 -m venv .venv  &&  .venv\\Scripts\\activate",
            "  macOS/Linux: python3.12 -m venv .venv  &&  source .venv/bin/activate",
            "Затем: python install_ai.py",
        ],
    ),
    (
        ("read timed out", "connection", "ssl", "temporary failure", "proxy", "incompleteread",
         "failed after", "resume"),
        [
            "Проблема с сетью: скачивается ~200 МБ. Повторите с большими таймаутами:",
            "  python -m pip install --timeout 300 --retries 15 deepface>=0.0.103 werkzeug",
            "Если нужен прокси/зеркало: pip config set global.index-url <url>",
            "Учтите: при первом запуске модель ещё раз качает 94 МБ весов с GitHub.",
        ],
    ),
    (
        ("no space left", "errno 28", "not enough space"),
        [
            "Не хватает места на диске. Нужно ~1 ГБ под пакеты и веса модели.",
        ],
    ),
    (
        ("permission", "access is denied", "errno 13"),
        [
            "Нет прав на запись. Ставьте в виртуальное окружение, а не в системный Python:",
            "  python -m venv .venv  →  активировать  →  python install_ai.py",
        ],
    ),
    (
        ("microsoft visual c++", "error: microsoft visual", "unable to find vcvarsall"),
        [
            "Нужны средства сборки C++ (обычно только для --with-tf):",
            "  https://visualstudio.microsoft.com/visual-cpp-build-tools/",
        ],
    ),
]


def head(text: str, char: str = "=") -> None:
    print(f"\n{char * 62}\n{text}\n{char * 62}")


def where_tf_needed() -> str:
    return (
        "TensorFlow не нужен: Facenet512 в DeepFace 0.0.103 работает на onnxruntime.\n"
        "  Ставьте его только если хотите другие модели/старый DeepFace."
    )


def python_info(with_tf: bool) -> bool:
    ver = sys.version_info
    arch = platform.machine() or "?"
    problems = False

    print(f"Python:   {sys.version.split()[0]}  ({platform.python_implementation()})")
    print(f"Где:      {sys.executable}")
    print(f"Система:  {platform.system()} {platform.release()} / {arch}")

    if ver < (3, 8):
        problems = True
        print("\n[!] DeepFace требует Python 3.8+. Поставьте Python 3.12.")

    if with_tf:
        if ver >= (3, 14):
            problems = True
            print(
                f"\n[!] Для TensorFlow нет колёс под Python {ver.major}.{ver.minor}.\n"
                "  " + where_tf_needed()
            )
        if platform.system() == "Darwin" and arch.lower() in ("x86_64", "i386"):
            problems = True
            print("\n[!] macOS на Intel: колёс TensorFlow 2.16+ нет (только Apple Silicon).\n  " + where_tf_needed())
        if platform.system() == "Windows" and platform.architecture()[0] == "32bit":
            problems = True
            print("\n[!] 32-битный Python: TensorFlow не поддерживается. Нужен 64-битный.")

    root = os.environ.get("SystemDrive", "C:") + "\\" if platform.system() == "Windows" else "/"
    try:
        free_gb = shutil.disk_usage(root).free / 1024**3
        print(f"Свободно: {free_gb:.1f} ГБ на диске")
        if free_gb < 1.5:
            problems = True
            print("\n[!] Мало места: нужно ~1 ГБ (пакеты + веса модели).")
    except OSError:
        pass

    return problems


def versions() -> dict[str, str]:
    found = {}
    for dist in ("deepface", "werkzeug", "onnxruntime", "tensorflow", "tf-keras"):
        try:
            found[dist] = md.version(dist)
        except md.PackageNotFoundError:
            pass
    return found


def run_pip(packages: list[str]) -> tuple[bool, str]:
    cmd = [
        sys.executable, "-m", "pip", "install", "--upgrade",
        "--timeout", "300", "--retries", "12", *packages,
    ]
    print("\n$ " + " ".join(cmd), flush=True)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    collected: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        collected.append(line)
        print(line.rstrip(), flush=True)
    proc.wait()
    return proc.returncode == 0, "".join(collected)


def explain(output: str) -> None:
    low = output.lower()
    printed = False
    for keys, advice in HINTS:
        if any(k in low for k in keys):
            print("\n--- что делать ---")
            for line in advice:
                print("  " + line)
            printed = True
    if not printed:
        print("\n--- что делать ---")
        print("  Скопируйте последние 20 строк ошибки выше — по ним видна причина.")
        print("  Универсальный вариант: окружение на Python 3.12.")
        print("  " + where_tf_needed())


def model_name() -> str:
    try:
        from config import SETTINGS  # noqa: PLC0415

        return SETTINGS.model_name
    except Exception:
        return "Facenet512"


def check_model() -> tuple[bool, str]:
    """Пробует импортировать DeepFace и загрузить модель."""
    try:
        from deepface import DeepFace  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        return False, exc.name or str(exc)
    except Exception as exc:  # pragma: no cover
        return False, f"{type(exc).__name__}: {exc}"
    try:
        print(f"[i] загружаю модель {model_name()} (первый раз качает 94 МБ весов)...")
        DeepFace.build_model(model_name())
        print("[ OK ] модель загружена — распознавание готово")
        return True, ""
    except Exception as exc:  # pragma: no cover
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Установка DeepFace для FaceLock")
    parser.add_argument("--check", action="store_true", help="только диагностика")
    parser.add_argument("--with-tf", action="store_true", help="дополнительно TensorFlow")
    parser.add_argument("--yes", "-y", action="store_true", help="не задавать вопросов")
    args = parser.parse_args()

    head("FaceLock: установка распознавания лиц")
    problems = python_info(args.with_tf)
    print("\nУже установлено: " + (", ".join(f"{k} {v}" for k, v in versions().items()) or "—"))

    if args.check:
        ok, err = check_model()
        if not ok:
            print(f"\n[!] Модель не загружается: {err}")
            print("    Запустите: python install_ai.py")
            return 1
        return 0

    if problems and not args.yes:
        answer = input("\nЕсть предупреждения (см. выше). Продолжать? [y/N] ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return 1

    # Шаг 1: deepface + werkzeug (недокументированная зависимость DeepFace 0.0.103)
    head("Шаг 1/2: deepface и werkzeug", "-")
    ok, out = run_pip(BASE_PKGS)
    if not ok:
        explain(out)
        return 1

    # Шаг 2: проверка модели; недостающие модули доставляем сами
    head("Шаг 2/2: проверка модели", "-")
    for attempt in range(1, 4):
        ok, err = check_model()
        if ok:
            break
        missing = err.strip()
        looks_like_module = (
            missing and " " not in missing and "." not in missing
            or (isinstance(err, str) and err.replace("_", "").isalnum())
        )
        print(f"[FAIL] попытка {attempt}: {err}")
        if attempt < 3 and looks_like_module:
            print(f"[i] доставляю недостающий модуль «{missing}»...")
            ok2, out2 = run_pip([missing])
            if not ok2:
                explain(out2)
                return 1
            continue
        break

    if args.with_tf:
        head("Дополнительно: TensorFlow", "-")
        ok, out = run_pip(TF_PKGS)
        if not ok:
            explain(out)
            print("\nНичего страшного: " + where_tf_needed())

    head("Итог")
    ok, err = check_model()
    if ok:
        print("\nГотово. Дальше: python check_env.py, затем python main.py")
        return 0
    print(f"\nМодель не загрузилась: {err}")
    if "werkzeug" in err.lower():
        print("  Лечится одной командой: python -m pip install werkzeug")
    print("  " + where_tf_needed())
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        sys.exit(130)
