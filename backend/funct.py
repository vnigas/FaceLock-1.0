"""Кроссплатформенная блокировка экрана и проверка «заблокирован ли он».

Windows — ``LockWorkStation`` из user32.dll.
macOS   — ``pmset displaysleepnow`` (плюс Quartz для проверки состояния сессии).
Linux   — loginctl / gnome-screensaver / xdg-screensaver / dm-tool.
"""

from __future__ import annotations

import ctypes
import logging
import platform
import shutil
import subprocess

logger = logging.getLogger(__name__)

SYSTEM = platform.system()


def _run_command(args: list[str], timeout: float = 5.0) -> bool:
    """Запускает команду, возвращает True при коде выхода 0."""
    if not shutil.which(args[0]):
        logger.debug("Команда %s не найдена", args[0])
        return False
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0
    except Exception as exc:  # pragma: no cover - зависит от ОС
        logger.debug("Команда %s не выполнилась: %s", args, exc)
        return False


# --------------------------------------------------------------------- блокировка
def lock_screen() -> bool:
    """Блокирует экран. Возвращает True, если команда выполнилась успешно."""
    if SYSTEM == "Windows":
        try:
            return bool(ctypes.windll.user32.LockWorkStation())
        except Exception as exc:  # pragma: no cover - только Windows
            logger.error("Не удалось заблокировать экран: %s", exc)
            return False

    if SYSTEM == "Darwin":
        if _run_command(["pmset", "displaysleepnow"]):
            return True
        return _run_command(
            [
                "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession",
                "-suspend",
            ]
        )

    # Linux и прочие Unix
    candidates = [
        ["loginctl", "lock-session"],
        ["gnome-screensaver-command", "--lock"],
        ["xdg-screensaver", "lock"],
        ["dm-tool", "lock"],
        ["swaymsg", "swaylock"],
        ["betterlockscreen", "-l"],
    ]
    for command in candidates:
        if _run_command(command):
            return True

    logger.warning("Ни один способ блокировки экрана не сработал")
    return False


# ------------------------------------------------------------------ состояние
def is_screen_locked() -> bool:
    """Best-effort проверка: заблокирован ли сейчас экран.

    Нужна, чтобы не дёргать блокировку повторно и не тратить ресурсы, пока
    пользователь отошёл. Если определить нельзя — возвращает False.
    """
    if SYSTEM == "Darwin":
        try:
            import Quartz  # type: ignore

            session = Quartz.CGSessionCopyCurrentDictionary()
            if session and session.get("CGSSessionScreenIsLocked", 0) == 1:
                return True
        except Exception:
            pass
        return False

    if SYSTEM == "Windows":
        try:
            user32 = ctypes.windll.user32
            # При заблокированном экране рабочего стола ввода нет -> NULL
            handle = user32.OpenInputDesktop(0, False, 0x0100)
            if not handle:
                return True
            user32.CloseDesktop(handle)
        except Exception:
            pass
        return False

    # Linux: пробуем несколько индикаторов
    if shutil.which("loginctl"):
        try:
            out = subprocess.run(
                ["loginctl", "show-session", "self", "-p", "LockedHint", "--value"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if out.stdout.strip().lower() == "yes":
                return True
        except Exception:
            pass

    if shutil.which("gnome-screensaver-command"):
        try:
            out = subprocess.run(
                ["gnome-screensaver-command", "-q"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if "is active" in out.stdout.lower():
                return True
        except Exception:
            pass

    return False
