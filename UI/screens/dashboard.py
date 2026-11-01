"""Главная страница: статус защиты, живой кадр, статистика и журнал событий."""

from __future__ import annotations

import time

import flet as ft

import config
from backend import database, monitor as monitor_module
from UI import theme
from UI.screens import Screen

STATE_STYLE = {
    monitor_module.STATE_IDLE: ("Мониторинг остановлен", theme.MUTED, ft.Icons.PAUSE_CIRCLE),
    monitor_module.STATE_STARTING: ("Запуск…", theme.ACCENT, ft.Icons.AUTORENEW),
    monitor_module.STATE_CHECKING: ("Проверка лица…", theme.ACCENT, ft.Icons.SEARCH),
    monitor_module.STATE_KNOWN: ("Свой человек", theme.OK, ft.Icons.CHECK_CIRCLE),
    monitor_module.STATE_NO_FACE: ("Лицо не в кадре", theme.MUTED, ft.Icons.PERSON_OFF if hasattr(ft.Icons, "PERSON_OFF") else ft.Icons.PERSON),
    monitor_module.STATE_INTRUDER: ("Посторонний!", theme.DANGER, ft.Icons.WARNING_AMBER),
    monitor_module.STATE_SCREEN_LOCKED: ("Экран заблокирован", theme.WARN, ft.Icons.LOCK),
    monitor_module.STATE_NO_CAMERA: ("Нет сигнала с камеры", theme.WARN, ft.Icons.VIDEOCAM_OFF if hasattr(ft.Icons, "VIDEOCAM_OFF") else ft.Icons.VIDEOCAM),
    monitor_module.STATE_ERROR: ("Ошибка", theme.DANGER, ft.Icons.ERROR_OUTLINE),
}

EVENT_STYLE = {
    monitor_module.KIND_BLOCK: (ft.Icons.LOCK, theme.DANGER),
    monitor_module.KIND_INTRUDER: (ft.Icons.VISIBILITY, theme.WARN),
    monitor_module.KIND_ERROR: (ft.Icons.ERROR_OUTLINE, theme.DANGER),
    monitor_module.KIND_INFO: (ft.Icons.INFO_OUTLINE, theme.ACCENT),
}


class DashboardScreen(Screen):
    name = "dashboard"
    wants_camera = True

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        # gapless_playback не даёт кадру «пропадать» между обновлениями:
        # без него превью мигает при каждой смене data-uri
        self.preview = ft.Image(src="", height=285, fit=ft.BoxFit.COVER, gapless_playback=True)
        self.preview_box = ft.Container(
            height=285,
            border_radius=14,
            bgcolor=theme.SURFACE_ALT,
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=self.preview,
        )
        self.status_pill = ft.Container()
        self.status_detail = theme.subtitle("—", 12)
        self.toggle_text = ft.Text("Начать мониторинг", size=15, weight=ft.FontWeight.W_600)
        self.toggle_button = ft.Button(
            content=self.toggle_text,
            icon=ft.Icons.PLAY_ARROW,
            on_click=self.safe(self._toggle),
            bgcolor=theme.ACCENT,
            color="#FFFFFF",
            icon_color="#FFFFFF",
            elevation=0,
            expand=True,
            height=52,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=14),
                padding=ft.Padding.symmetric(horizontal=20),
            ),
        )
        self.stat_checks = ft.Text("0")
        self.stat_blocks = ft.Text("0")
        self.stat_errors = ft.Text("0")
        self.distance_text = theme.subtitle("Расстояние до владельца: —", 12)
        self.distance_bar = ft.ProgressBar(
            value=0.0, height=6, color=theme.OK, bgcolor=theme.alpha(0.12, "#FFFFFF")
        )
        self.events_column = ft.Column(spacing=6)
        self.events_count = theme.subtitle("", 12)
        self.banner = ft.Container(visible=False)
        self._last_events = -1
        self._db_checked = 0.0
        self._has_db = True
        self._last_state_key = None
        self._last_running: bool | None = None
        self._last_frame = 0.0

    # ------------------------------------------------------------------- отрисовка
    def build(self) -> ft.Control:
        self._refresh_db_state(force=True)
        self._render_banner()
        self._render_events()

        logo = ft.Container(
            content=ft.Icon(ft.Icons.SHIELD, size=22, color="#FFFFFF"),
            width=44,
            height=44,
            border_radius=14,
            bgcolor=theme.ACCENT,
            alignment=ft.Alignment.CENTER,
        )
        header = ft.Row(
            [
                logo,
                ft.Column(
                    [theme.title("FaceLock", 20), theme.subtitle("Защита экрана по лицу", 11)],
                    spacing=0,
                ),
                ft.Container(expand=True),
                self.status_pill,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        )

        preview_card = theme.card(
            ft.Column(
                [
                    ft.Row(
                        [
                            theme.title("Камера", 16),
                            ft.Container(expand=True),
                            self.status_detail,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.preview_box,
                ],
                spacing=12,
            ),
            expand=6,
        )

        controls_card = theme.card(
            ft.Column(
                [
                    theme.title("Защита", 16),
                    self.toggle_button,
                    ft.Row(
                        [
                            theme.stat_block("проверок", self.stat_checks),
                            theme.stat_block("блокировок", self.stat_blocks),
                            theme.stat_block("ошибок", self.stat_errors),
                        ],
                        spacing=10,
                    ),
                    ft.Column([self.distance_text, self.distance_bar], spacing=6),
                    ft.Divider(height=1, color=theme.BORDER),
                    ft.Row(
                        [
                            theme.secondary_button(
                                "Снимки", icon=ft.Icons.PHOTO_LIBRARY if hasattr(ft.Icons, "PHOTO_LIBRARY") else ft.Icons.IMAGE,
                                on_click=self.safe(lambda e: self.ctx.show("history")), height=40,
                            ),
                            theme.secondary_button(
                                "Моё лицо", icon=ft.Icons.PERSON,
                                on_click=self.safe(lambda e: self.ctx.show("register")), height=40,
                            ),
                        ],
                        spacing=10,
                    ),
                ],
                spacing=14,
                expand=True,
            ),
            expand=4,
        )

        events_card = theme.card(
            ft.Column(
                [
                    ft.Row(
                        [
                            theme.title("Журнал событий", 16),
                            ft.Container(expand=True),
                            self.events_count,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.events_column,
                ],
                spacing=10,
            ),
        )

        body = ft.Column(
            [
                self.banner,
                ft.Row([preview_card, controls_card], spacing=theme.GAP, vertical_alignment=ft.CrossAxisAlignment.START),
                events_card,
            ],
            spacing=theme.GAP,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        nav = theme.nav_bar(0, self._on_nav)

        return ft.Container(
            content=ft.Column(
                [ft.Container(content=header, padding=ft.Padding.only(left=24, right=24, top=20, bottom=12)), ft.Container(content=body, padding=ft.Padding.only(left=24, right=24), expand=True), nav],
                spacing=0,
                expand=True,
            ),
            expand=True,
            bgcolor=theme.BG,
        )

    # ------------------------------------------------------------------- навигация
    def _on_nav(self, event) -> None:
        try:
            index = int(event.control.selected_index)
        except Exception:
            index = int(getattr(event, "data", 0) or 0)
        targets = {1: "history", 2: "settings"}
        if index in targets:
            self.ctx.show(targets[index])
        else:
            event.control.selected_index = 0

    # ------------------------------------------------------------------- баннер БД
    def _refresh_db_state(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._db_checked < 2.0:
            return
        self._db_checked = time.monotonic()
        previous = self._has_db
        self._has_db = database.has_database()
        if previous != self._has_db or force:
            self._render_banner()

    def _render_banner(self) -> None:
        if self._has_db:
            self.banner.visible = False
            self.banner.content = None
            return
        summary = self.ctx.database_state()
        self.banner.visible = True
        self.banner.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.WARNING_AMBER, color=theme.WARN, size=22),
                    ft.Column(
                        [
                            ft.Text("База лиц не создана", size=14, weight=ft.FontWeight.W_600, color=theme.TEXT),
                            theme.subtitle(
                                f"Фотографий в папке: {summary['photos']}. Запишите лицо владельца, "
                                "чтобы включить мониторинг.",
                                12,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    theme.primary_button(
                        "Записать лицо", icon=ft.Icons.PERSON, on_click=self.safe(lambda e: self.ctx.show("register")), height=42
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=16,
            border_radius=16,
            bgcolor=theme.alpha(0.12, theme.WARN),
            border=ft.Border.all(1, theme.alpha(0.35, theme.WARN)),
        )

    # ------------------------------------------------------------------- действия
    def _toggle(self, event) -> None:
        if self.ctx.monitor.is_running:
            self.ctx.stop_monitor()
            self.ctx.toast("Мониторинг остановлен")
        else:
            if self.ctx.start_monitor():
                self.ctx.toast("Мониторинг запущен")
        self._db_checked = 0.0
        self._refresh_db_state(force=True)

    # ------------------------------------------------------------------- журнал
    def _render_events(self) -> None:
        events = list(self.ctx.recent)[:6]
        self.events_count.value = f"всего событий: {len(self.ctx.recent)}"
        if not events:
            self.events_column.controls = [
                theme.empty_state(ft.Icons.EVENT_NOTE, "Событий пока нет: журнал заполняется,\nкогда в кадре появляется посторонний")
            ]
            return

        rows: list[ft.Control] = []
        for event in events:
            icon, color = EVENT_STYLE.get(event.kind, (ft.Icons.INFO_OUTLINE, theme.MUTED))
            details = [theme.human_ago(event.timestamp)]
            if event.distance is not None:
                details.append(f"расстояние {event.distance:.3f}")
            if event.snapshot:
                details.append("снимок сохранён")
            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(icon, size=16, color=color),
                                width=30,
                                height=30,
                                border_radius=10,
                                bgcolor=theme.alpha(0.14, color),
                                alignment=ft.Alignment.CENTER,
                            ),
                            ft.Column(
                                [
                                    ft.Text(event.message, size=13, color=theme.TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    theme.subtitle(" · ".join(details), 11),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                            theme.subtitle(theme.human_time(event.timestamp), 11),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    border_radius=12,
                    bgcolor=theme.alpha(0.03, "#FFFFFF"),
                )
            )
        self.events_column.controls = rows

    # ------------------------------------------------------------------- цикл
    def tick(self) -> None:
        state = self.ctx.monitor.state()
        self._apply_state(state)

        # ширина кадра подгоняется под ширину карточки, чтобы превью
        # заполняло её целиком при любом размере окна
        frame_width = self._preview_width()
        uri = self.preview_uri(width=frame_width, quality=66)
        if uri:
            self.preview.src = uri
            if self.preview.width != frame_width:
                self.preview.width = frame_width
            self._last_frame = time.monotonic()

        if len(self.ctx.recent) != self._last_events:
            self._last_events = len(self.ctx.recent)
            self._render_events()

        self._refresh_db_state()

    def _preview_width(self) -> int:
        try:
            page_width = float(self.page.width or 1120)
        except Exception:
            page_width = 1120.0
        # карточка камеры занимает ~60 % ширины окна минус отступы и паддинги
        return int(max(320, min(900, page_width * 0.55 - 60)))

    def _apply_state(self, state) -> None:
        label, color, icon = STATE_STYLE.get(state.state, ("—", theme.MUTED, ft.Icons.INFO_OUTLINE))
        if state.state != self._last_state_key:
            self._last_state_key = state.state
            theme.set_pill(self.status_pill, label, color, icon)

        # контролы обновляем только при смене состояния, а не 8 раз в секунду
        if state.running != self._last_running:
            self._last_running = state.running
            self.toggle_text.value = "Остановить мониторинг" if state.running else "Начать мониторинг"
            self.toggle_button.icon = ft.Icons.STOP_CIRCLE if state.running else ft.Icons.PLAY_ARROW
            if state.running:
                self.toggle_button.bgcolor = theme.alpha(0.16, theme.DANGER)
                self.toggle_button.color = theme.DANGER
                self.toggle_button.icon_color = theme.DANGER
            else:
                self.toggle_button.bgcolor = theme.ACCENT
                self.toggle_button.color = "#FFFFFF"
                self.toggle_button.icon_color = "#FFFFFF"

        detail = state.message or "—"
        if state.last_check:
            detail += f" · {theme.human_ago(state.last_check)}"
        self.status_detail.value = detail

        self.stat_checks.value = str(state.checks)
        self.stat_blocks.value = str(state.blocks)
        self.stat_blocks.color = theme.DANGER if state.blocks else theme.TEXT
        self.stat_errors.value = str(state.errors)
        self.stat_errors.color = theme.WARN if state.errors else theme.TEXT

        threshold = max(0.01, float(state.threshold))
        if state.distance is None:
            self.distance_text.value = f"Расстояние до владельца: — · порог {threshold:.2f}"
            self.distance_bar.value = 0.0
            self.distance_bar.color = theme.MUTED
        else:
            known = state.distance <= threshold
            self.distance_text.value = (
                f"Расстояние: {state.distance:.3f} · порог {threshold:.2f} "
                f"({'свой' if known else 'чужой'})"
            )
            self.distance_bar.value = min(1.0, state.distance / threshold)
            self.distance_bar.color = theme.OK if known else theme.DANGER

    def on_show(self) -> None:
        self._db_checked = 0.0
        self._refresh_db_state(force=True)
        self._last_events = -1
        if not self.ctx.auto_start_done:
            self.ctx.auto_start_done = True
            if config.SETTINGS.auto_start and database.has_database():
                self.ctx.start_monitor()
