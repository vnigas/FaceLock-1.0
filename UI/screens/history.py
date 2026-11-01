"""История: снимки людей, чьё лицо не совпало с базой."""

from __future__ import annotations

from pathlib import Path

import flet as ft

from backend import database
from UI import theme
from UI.screens import Screen


class HistoryScreen(Screen):
    name = "history"
    wants_camera = False

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        # сетка из строк с переносом: карточки имеют фиксированный размер,
        # поэтому не остаётся пустого места под подписями
        self.grid = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
        self.count_pill = ft.Container()
        self._cache: dict[str, str | None] = {}

    # ------------------------------------------------------------------- отрисовка
    def build(self) -> ft.Control:
        self._rebuild()

        header = ft.Row(
            [
                theme.title("Снимки посторонних", 20),
                self.count_pill,
                ft.Container(expand=True),
                theme.secondary_button("Обновить", icon=ft.Icons.REFRESH, on_click=self.safe(lambda e: self._rebuild()), height=40),
                theme.danger_button("Очистить", icon=ft.Icons.DELETE_SWEEP if hasattr(ft.Icons, "DELETE_SWEEP") else ft.Icons.DELETE, on_click=self.safe(self._confirm_clear), height=40),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        body = ft.Container(content=self.grid, expand=True)

        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(content=header, padding=ft.Padding.only(left=24, right=24, top=20, bottom=4)),
                    ft.Container(
                        content=ft.Column(
                            [
                                theme.subtitle(
                                    "Каждый раз, когда FaceLock блокирует экран, кадр сохраняется сюда. "
                                    "Файлы лежат в папке block_users.",
                                    12,
                                ),
                                body,
                            ],
                            spacing=14,
                            expand=True,
                        ),
                        padding=ft.Padding.only(left=24, right=24, top=8, bottom=8),
                        expand=True,
                    ),
                    theme.nav_bar(1, self._on_nav),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
            bgcolor=theme.BG,
        )

    def _rebuild(self) -> None:
        paths = self.ctx.snapshot_paths()


        theme.set_pill(self.count_pill, f"{len(paths)} снимков" if paths else "пусто",
                       theme.MUTED if not paths else theme.WARN,
                       ft.Icons.PHOTO_LIBRARY if hasattr(ft.Icons, "PHOTO_LIBRARY") else ft.Icons.IMAGE)

        if not paths:
            self.grid.controls = [
                theme.empty_state(
                    ft.Icons.PHOTO_LIBRARY if hasattr(ft.Icons, "PHOTO_LIBRARY") else ft.Icons.IMAGE,
                    "Пока пусто: снимки появятся здесь после\nпервой блокировки экрана",
                )
            ]
            return

        cards = [self._card(path) for path in paths]
        self.grid.controls = [ft.Row(cards, wrap=True, spacing=12, run_spacing=12)]
        self._prune_cache(paths)

    def _prune_cache(self, paths: list[Path]) -> None:
        for file in list(self._cache):
            if not Path(file).exists():
                self._cache.pop(file, None)

    def _uri(self, path: Path) -> str | None:
        key = str(path)
        if key not in self._cache:
            self._cache[key] = database.path_to_data_uri(path, width=280, quality=70)
        return self._cache[key]

    def _card(self, path: Path) -> ft.Control:
        uri = self._uri(path)
        image = (
            ft.Image(src=uri, fit=ft.BoxFit.COVER, width=200, height=150, border_radius=10)
            if uri
            else ft.Container(width=200, height=150, bgcolor=theme.SURFACE_ALT, border_radius=10)
        )
        delete = ft.Container(
            content=ft.Icon(ft.Icons.CLOSE, size=14, color="#FFFFFF"),
            width=24,
            height=24,
            border_radius=999,
            bgcolor=theme.alpha(0.75, theme.DANGER),
            alignment=ft.Alignment.CENTER,
            on_click=self.safe(lambda e, p=path: self._delete(p)),
            tooltip="Удалить снимок",
        )
        try:
            stamp = theme.human_datetime(path.stat().st_mtime)
        except OSError:
            stamp = path.name
        return ft.Container(
            content=ft.Column(
                [
                    ft.Stack([image, ft.Container(content=delete, right=4, top=4)]),
                    theme.subtitle(stamp, 11),
                ],
                spacing=8,
            ),
            padding=10,
            width=222,
            border_radius=16,
            bgcolor=theme.SURFACE,
            border=ft.Border.all(1, theme.BORDER),
        )

    # ------------------------------------------------------------------- действия
    def _delete(self, path: Path) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception as exc:
            self.ctx.toast(f"Не удалось удалить: {exc}", theme.DANGER)
            return
        self._rebuild()

    def _confirm_clear(self, event) -> None:
        if not self.ctx.snapshot_paths():
            self.ctx.toast("Снимков нет")
            return

        def close(event) -> None:
            self.page.pop_dialog()

        def confirm(event) -> None:
            removed = database.clear_snapshots()
            self.page.pop_dialog()
            self._cache.clear()
            self._rebuild()
            self.ctx.toast(f"Удалено снимков: {removed}")

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Удалить все снимки?"),
                content=ft.Text("Файлы будут удалены безвозвратно."),
                actions=[
                    ft.TextButton(content=ft.Text("Отмена"), on_click=self.safe(close)),
                    ft.TextButton(content=ft.Text("Удалить", color=theme.DANGER), on_click=self.safe(confirm)),
                ],
            )
        )

    # ------------------------------------------------------------------- навигация
    def _on_nav(self, event) -> None:
        index = int(event.control.selected_index)
        targets = {0: "dashboard", 2: "settings"}
        if index in targets:
            self.ctx.show(targets[index])
        else:
            event.control.selected_index = 1

    def on_show(self) -> None:
        self._rebuild()
