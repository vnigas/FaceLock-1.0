"""Настройки: чувствительность, камера, обслуживание базы лиц."""

from __future__ import annotations

import flet as ft

import config
from backend import database
from UI import theme
from UI.screens import Screen


class SettingsScreen(Screen):
    name = "settings"
    wants_camera = False

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        settings = config.SETTINGS
        self.threshold_value = ft.Text(f"{settings.threshold:.2f}", size=13, color=theme.TEXT, weight=ft.FontWeight.W_600)
        self.threshold_slider = ft.Slider(
            min=0.10, max=0.60, divisions=50, value=float(settings.threshold),
            active_color=theme.ACCENT, on_change=self._on_threshold, on_change_end=self._on_threshold,
        )
        self.interval_value = ft.Text(f"{settings.check_interval:.1f} с", size=13, color=theme.TEXT, weight=ft.FontWeight.W_600)
        self.interval_slider = ft.Slider(
            min=0.3, max=5.0, divisions=47, value=float(settings.check_interval),
            active_color=theme.ACCENT, on_change=self._on_interval, on_change_end=self._on_interval,
        )
        self.cooldown_value = ft.Text(f"{settings.lock_cooldown} с", size=13, color=theme.TEXT, weight=ft.FontWeight.W_600)
        self.cooldown_slider = ft.Slider(
            min=0, max=300, divisions=30, value=float(settings.lock_cooldown),
            active_color=theme.ACCENT, on_change=self._on_cooldown, on_change_end=self._on_cooldown,
        )
        self.camera_dropdown = ft.Dropdown(
            width=170,
            label="Камера",
            value=str(settings.camera_index),
            options=[ft.DropdownOption(key=str(index), text=f"Камера {index}") for index in range(5)],
            on_select=self.safe(self._on_camera),
        )
        self.auto_start_switch = ft.Switch(
            label="Включать мониторинг сразу после «Старт»",
            value=bool(settings.auto_start),
            on_change=self.safe(self._on_auto_start),
        )
        self.snapshots_switch = ft.Switch(
            label="Сохранять снимки посторонних",
            value=bool(settings.save_snapshots),
            on_change=self.safe(self._on_snapshots),
        )
        self.strict_switch = ft.Switch(
            label="Требовать уверенного обнаружения лица",
            value=bool(settings.enforce_detection),
            on_change=self.safe(self._on_strict),
        )
        self.info_column = ft.Column(spacing=8)
        self._handled_task = None

    # ------------------------------------------------------------------- отрисовка
    def build(self) -> ft.Control:
        self._refresh_info()

        sensitivity = theme.card(
            ft.Column(
                [
                    theme.title("Чувствительность", 17),
                    theme.subtitle(
                        "Порог косинусного расстояния: меньше — строже проверка. "
                        "0.30 — рекомендуемое значение; 0.20 — блокировка при малейшем отличии.",
                        12,
                    ),
                    self._slider_row("Порог", self.threshold_value, self.threshold_slider),
                    self._slider_row("Интервал проверки", self.interval_value, self.interval_slider),
                    self._slider_row("Пауза между блокировками", self.cooldown_value, self.cooldown_slider),
                ],
                spacing=10,
            )
        )

        device = theme.card(
            ft.Column(
                [
                    theme.title("Камера и запуск", 17),
                    ft.Row([self.camera_dropdown], spacing=10),
                    self.auto_start_switch,
                    self.snapshots_switch,
                    self.strict_switch,
                ],
                spacing=12,
            )
        )

        maintenance = theme.card(
            ft.Column(
                [
                    theme.title("База лиц", 17),
                    theme.subtitle(
                        "Пересборка пересчитывает embedding'и по всем фотографиям из папки лиц.",
                        12,
                    ),
                    ft.Row(
                        [
                            theme.secondary_button(
                                "Пересобрать базу", icon=ft.Icons.AUTORENEW, on_click=self.safe(self._rebuild_db)
                            ),
                            theme.secondary_button(
                                "Открыть папку данных", icon=ft.Icons.FOLDER_OPEN, on_click=self.safe(lambda e: self.ctx.open_data_folder())
                            ),
                            theme.danger_button(
                                "Удалить базу", icon=ft.Icons.DELETE, on_click=self.safe(self._confirm_clear_db)
                            ),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                spacing=12,
            )
        )

        about = theme.card(
            ft.Column(
                [
                    theme.title("О приложении", 17),
                    self.info_column,
                ],
                spacing=12,
            )
        )

        sensitivity.expand = 3
        right_column = ft.Column([device, maintenance], spacing=theme.GAP, expand=2)
        body = ft.Column(
            [
                ft.Row([sensitivity, right_column], spacing=theme.GAP, vertical_alignment=ft.CrossAxisAlignment.START),
                about,
            ],
            spacing=theme.GAP,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(content=theme.title("Настройки", 20), padding=ft.Padding.only(left=24, right=24, top=20, bottom=4)),
                    ft.Container(content=body, padding=ft.Padding.only(left=24, right=24, top=8, bottom=8), expand=True),
                    theme.nav_bar(2, self._on_nav),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
            bgcolor=theme.BG,
        )

    def _slider_row(self, label: str, value_control: ft.Text, slider: ft.Slider) -> ft.Column:
        return ft.Column(
            [
                ft.Row([ft.Text(label, size=13, color=theme.MUTED), ft.Container(expand=True), value_control]),
                slider,
            ],
            spacing=0,
        )

    def _refresh_info(self) -> None:
        summary = self.ctx.database_state()
        self.info_column.controls = [
            theme.info_row("Версия", config.APP_VERSION),
            theme.info_row("Модель", config.SETTINGS.model_name),
            theme.info_row("Записей в базе", str(summary["embeddings"])),
            theme.info_row("Фотографий", str(summary["photos"])),
            theme.info_row("База", summary["db_path"]),
            theme.info_row("Фото владельца", summary["image_dir"]),
            theme.info_row("Каталог данных", str(config.DATA_ROOT)),
        ]

    # ------------------------------------------------------------------- обработчики
    def _on_threshold(self, event) -> None:
        value = round(float(event.control.value), 2)
        self.threshold_value.value = f"{value:.2f}"
        config.update_settings(threshold=value)

    def _on_interval(self, event) -> None:
        value = round(float(event.control.value), 1)
        self.interval_value.value = f"{value:.1f} с"
        config.update_settings(check_interval=value)

    def _on_cooldown(self, event) -> None:
        value = int(round(float(event.control.value)))
        self.cooldown_value.value = f"{value} с"
        config.update_settings(lock_cooldown=value)

    def _on_camera(self, event) -> None:
        index = int(event.control.value)
        config.update_settings(camera_index=index)
        self.ctx.camera.close()
        self.ctx.toast(f"Выбрана камера {index}")

    def _on_auto_start(self, event) -> None:
        config.update_settings(auto_start=bool(event.control.value))

    def _on_snapshots(self, event) -> None:
        config.update_settings(save_snapshots=bool(event.control.value))

    def _on_strict(self, event) -> None:
        config.update_settings(enforce_detection=bool(event.control.value))

    def _rebuild_db(self, event) -> None:
        if self.ctx.task is not None and self.ctx.task.running:
            self.ctx.toast("Уже идёт построение базы")
            return
        if not database.list_photos():
            self.ctx.toast("В папке лиц нет фотографий", theme.WARN)
            return
        self.ctx.toast("Пересборка базы запущена")
        self.ctx.run_bg(lambda progress: database.build_database(progress=progress), message="Строим базу лиц…")

    def _confirm_clear_db(self, event) -> None:
        def close(event) -> None:
            self.page.pop_dialog()

        def confirm(event) -> None:
            if self.ctx.monitor.is_running:
                self.ctx.stop_monitor()
            database.clear_database()
            self.page.pop_dialog()
            self._refresh_info()
            self.ctx.toast("База лиц удалена")

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Удалить базу лиц?"),
                content=ft.Text(
                    "Мониторинг перестанет работать, пока вы снова не запишете лицо. "
                    "Фотографии в папке лиц останутся."
                ),
                actions=[
                    ft.TextButton(content=ft.Text("Отмена"), on_click=self.safe(close)),
                    ft.TextButton(content=ft.Text("Удалить", color=theme.DANGER), on_click=self.safe(confirm)),
                ],
            )
        )

    # ------------------------------------------------------------------- навигация
    def _on_nav(self, event) -> None:
        index = int(event.control.selected_index)
        targets = {0: "dashboard", 1: "history"}
        if index in targets:
            self.ctx.show(targets[index])
        else:
            event.control.selected_index = 2

    # ------------------------------------------------------------------- цикл
    def tick(self) -> None:
        task = self.ctx.task
        if task is not None and task.done and task is not self._handled_task:
            self._handled_task = task
            self._refresh_info()
            if task.error:
                self.ctx.toast(f"Ошибка: {task.error}", theme.DANGER)
            elif getattr(task.result, "ok", False):
                self.ctx.monitor.reload_faces()
                self.ctx.toast(f"База пересобрана: {task.result.built} лиц")
            else:
                summary = task.result.summary() if task.result is not None else ""
                self.ctx.toast(f"Лица не найдены. {summary}", theme.DANGER)

    def on_show(self) -> None:
        self._refresh_info()
        self.threshold_slider.value = float(config.SETTINGS.threshold)
        self.camera_dropdown.value = str(config.SETTINGS.camera_index)
