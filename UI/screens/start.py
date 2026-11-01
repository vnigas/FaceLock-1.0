"""Стартовое окно.

При запуске приложение проверяет, есть ли база лиц. Пока базы нет — стартовое
окно честно об этом сообщает, а кнопка «Старт» ведёт на главную страницу, где
предлагается записать лицо. Если база уже есть, «Старт» сразу открывает
главную страницу с мониторингом.
"""

from __future__ import annotations

import time

import flet as ft

import config
from UI import theme
from UI.screens import Screen


class StartScreen(Screen):
    name = "start"
    wants_camera = False

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._state: dict = {}
        self._checked_at = 0.0
        self.info_text = theme.subtitle("", 13)
        self.status_host = ft.Container()
        self.notes = ft.Column(spacing=8)
        self.start_button = theme.primary_button(
            "Старт", icon=ft.Icons.PLAY_ARROW, on_click=self.safe(self._start), width=280, height=54
        )
        self.setup_button = theme.secondary_button(
            "Записать лицо", icon=ft.Icons.PERSON, on_click=self.safe(self._register)
        )

    # ------------------------------------------------------------------- отрисовка
    def build(self) -> ft.Control:
        self._refresh_state(force=True)

        logo = ft.Container(
            content=ft.Icon(ft.Icons.SHIELD, size=44, color="#FFFFFF"),
            width=88,
            height=88,
            border_radius=26,
            bgcolor=theme.ACCENT,
            alignment=ft.Alignment.CENTER,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(expand=True),
                    ft.Column(
                        [
                            logo,
                            ft.Text("FaceLock", size=42, weight=ft.FontWeight.BOLD, color=theme.TEXT),
                            theme.subtitle(
                                "Экран блокируется, как только в кадре появляется чужое лицо",
                                14,
                            ),
                        ],
                        spacing=12,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=26),
                    theme.card(
                        ft.Column(
                            [
                                ft.Row(
                                    [self.status_host, ft.Container(expand=True)],
                                ),
                                self.info_text,
                                self.notes,
                                ft.Row([self.setup_button], alignment=ft.MainAxisAlignment.CENTER),
                            ],
                            spacing=14,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=22,
                        width=460,
                    ),
                    ft.Container(height=26),
                    self.start_button,
                    ft.Container(height=14),
                    theme.subtitle("FaceLock " + config.APP_VERSION, 11),
                    ft.Container(height=36),
                    ft.Container(expand=True),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
                expand=True,
            ),
            expand=True,
            padding=24,
            alignment=ft.Alignment.CENTER,
        )

    # ------------------------------------------------------------------- состояние
    def _refresh_state(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._checked_at < 2.0:
            return
        self._checked_at = time.monotonic()
        self._state = self.ctx.database_state()

        if self._state["exists"]:
            theme.set_pill(
                self.status_host,
                f"База готова · {self._state['embeddings']} записей",
                theme.OK,
                ft.Icons.CHECK_CIRCLE,
            )
            self.info_text.value = (
                "Владелец зарегистрирован. Нажмите «Старт», чтобы открыть главную "
                "страницу и включить мониторинг."
            )
            self.setup_button.content = ft.Text("Моё лицо", size=14, color=theme.TEXT)
        else:
            theme.set_pill(self.status_host, "База лиц не создана", theme.WARN, ft.Icons.WARNING_AMBER)
            self.info_text.value = (
                "Это первый запуск: база лиц пока пуста. Нажмите «Старт» — на главной "
                "странице будет предложено записать лицо владельца (5–7 снимков)."
            )
            self.setup_button.content = ft.Text("Записать лицо сразу", size=14, color=theme.TEXT)

        self.notes.controls = [
            theme.info_row("Фотографий в папке", str(self._state["photos"])),
            theme.info_row("Снимков посторонних", str(self._state["snapshots"])),
        ]

    def tick(self) -> None:
        self._refresh_state()

    # ------------------------------------------------------------------- действия
    def _start(self, event) -> None:
        self.ctx.show("dashboard")

    def _register(self, event) -> None:
        self.ctx.show("register")
