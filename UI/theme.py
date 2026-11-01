"""Визуальный стиль FaceLock: цвета, отступы и переиспользуемые элементы."""

from __future__ import annotations

import datetime as dt

import flet as ft

# --------------------------------------------------------------------- палитра
BG = "#0E1116"
SURFACE = "#161A22"
SURFACE_ALT = "#1E232D"
BORDER = "#242B38"

ACCENT = "#4C8DFF"
OK = "#2FBF71"
WARN = "#F2A93B"
DANGER = "#E5484D"
TEXT = "#EDEFF4"
MUTED = "#8B95A7"

RADIUS = 18
GAP = 16


# --------------------------------------------------------------------- утилиты
def alpha(opacity: float, color: str) -> str:
    """Полупрозрачный цвет для заливок."""
    return ft.Colors.with_opacity(opacity, color)


def human_time(timestamp: float | None) -> str:
    if not timestamp:
        return "—"
    return dt.datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def human_datetime(timestamp: float | None) -> str:
    if not timestamp:
        return "—"
    return dt.datetime.fromtimestamp(timestamp).strftime("%d.%m.%Y %H:%M:%S")


def human_ago(timestamp: float | None) -> str:
    if not timestamp:
        return "никогда"
    seconds = max(0, int(dt.datetime.now().timestamp() - timestamp))
    if seconds < 5:
        return "только что"
    if seconds < 60:
        return f"{seconds} с назад"
    if seconds < 3600:
        return f"{seconds // 60} мин назад"
    return human_datetime(timestamp)


# --------------------------------------------------------------------- элементы
def card(content, padding: int | None = 20, bgcolor: str = SURFACE, expand=False, width=None) -> ft.Container:
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=bgcolor,
        border_radius=RADIUS,
        border=ft.Border.all(1, BORDER),
        expand=expand,
        width=width,
    )


def title(text: str, size: int = 22) -> ft.Text:
    return ft.Text(text, size=size, weight=ft.FontWeight.BOLD, color=TEXT)


def subtitle(text: str, size: int = 13) -> ft.Text:
    return ft.Text(text, size=size, color=MUTED)


def pill(text: str, color: str, icon=None) -> ft.Container:
    controls: list[ft.Control] = []
    if icon is not None:
        controls.append(ft.Icon(icon, size=14, color=color))
    controls.append(ft.Text(text, size=12, weight=ft.FontWeight.W_600, color=color))
    return ft.Container(
        content=ft.Row(controls, spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        bgcolor=alpha(0.14, color),
        border_radius=999,
    )


def set_pill(container: ft.Container, text: str, color: str, icon=None) -> None:
    """Обновляет содержимое «таблетки» статуса без пересоздания контрола."""
    controls: list[ft.Control] = []
    if icon is not None:
        controls.append(ft.Icon(icon, size=14, color=color))
    controls.append(ft.Text(text, size=12, weight=ft.FontWeight.W_600, color=color))
    container.content = ft.Row(controls, spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER)
    container.bgcolor = alpha(0.14, color)


def primary_button(text: str, icon=None, on_click=None, expand=False, width=None, height: int = 50, disabled=False) -> ft.Button:
    return ft.Button(
        content=ft.Text(text, size=15, weight=ft.FontWeight.W_600),
        icon=icon,
        on_click=on_click,
        bgcolor=ACCENT,
        color="#FFFFFF",
        icon_color="#FFFFFF",
        elevation=0,
        expand=expand,
        width=width,
        height=height,
        disabled=disabled,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=14), padding=ft.Padding.symmetric(horizontal=20)),
    )


def secondary_button(text: str, icon=None, on_click=None, width=None, height: int = 44, disabled=False) -> ft.Button:
    return ft.Button(
        content=ft.Text(text, size=14, color=TEXT),
        icon=icon,
        on_click=on_click,
        bgcolor=alpha(0.06, "#FFFFFF"),
        color=TEXT,
        icon_color=TEXT,
        elevation=0,
        width=width,
        height=height,
        disabled=disabled,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=16),
        ),
    )


def danger_button(text: str, icon=None, on_click=None, width=None, height: int = 44) -> ft.Button:
    return ft.Button(
        content=ft.Text(text, size=14, color=DANGER),
        icon=icon,
        on_click=on_click,
        bgcolor=alpha(0.12, DANGER),
        color=DANGER,
        icon_color=DANGER,
        elevation=0,
        width=width,
        height=height,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=12),
            padding=ft.Padding.symmetric(horizontal=16),
        ),
    )


def icon_button(icon, on_click, tooltip: str | None = None, color: str = MUTED) -> ft.IconButton:
    return ft.IconButton(icon=icon, icon_color=color, icon_size=18, tooltip=tooltip, on_click=on_click)


def stat_block(label: str, value_control: ft.Text, color: str = TEXT) -> ft.Container:
    value_control.size = 26
    value_control.weight = ft.FontWeight.BOLD
    value_control.color = color
    return ft.Container(
        content=ft.Column(
            [value_control, ft.Text(label, size=12, color=MUTED)],
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.START,
        ),
        padding=ft.Padding.symmetric(horizontal=14, vertical=12),
        bgcolor=alpha(0.04, "#FFFFFF"),
        border_radius=14,
        expand=True,
    )


def info_row(label: str, value: str) -> ft.Row:
    return ft.Row(
        [
            ft.Text(label, size=12, color=MUTED),
            ft.Container(expand=True),
            ft.Text(value, size=12, color=TEXT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def nav_bar(selected_index: int, on_change) -> ft.NavigationBar:
    """Нижняя навигация: Главная / Снимки / Настройки."""
    shield = ft.Icons.SHIELD
    shield_outlined = getattr(ft.Icons, "SHIELD_OUTLINED", ft.Icons.SHIELD)
    return ft.NavigationBar(
        selected_index=selected_index,
        bgcolor=SURFACE,
        indicator_color=alpha(0.18, ACCENT),
        height=64,
        destinations=[
            ft.NavigationBarDestination(icon=shield_outlined, selected_icon=shield, label="Главная"),
            ft.NavigationBarDestination(icon=ft.Icons.HISTORY, selected_icon=ft.Icons.HISTORY, label="Снимки"),
            ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, selected_icon=ft.Icons.SETTINGS, label="Настройки"),
        ],
        on_change=on_change,
    )


def empty_state(icon, text: str) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(icon, size=40, color=BORDER),
                ft.Text(text, size=13, color=MUTED, text_align=ft.TextAlign.CENTER),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        alignment=ft.Alignment.CENTER,
        padding=22,
    )
