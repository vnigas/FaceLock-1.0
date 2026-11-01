"""Регистрация лица владельца.

Снимки делаются прямо с камеры приложения или загружаются из файлов. Каждый
снимок сразу сохраняется в ``data/known_face``; кнопка «Сохранить» строит по
всем фотографиям базу embedding'ов (в фоновом потоке, с прогрессом).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import flet as ft

import config
from backend import database
from UI import theme
from UI.screens import Screen


logger = logging.getLogger(__name__)


class RegisterScreen(Screen):
    name = "register"
    wants_camera = True

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        # картинка всегда в дереве контролов: подменять содержимое контейнера
        # или переключать visible у наложенных контролов ненадёжно
        self.preview = ft.Image(src="", width=420, height=315, fit=ft.BoxFit.COVER, gapless_playback=True)
        self.preview_box = ft.Container(
            width=420,
            height=315,
            border_radius=16,
            bgcolor=theme.SURFACE_ALT,
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=self.preview,
        )
        self.camera_hint = theme.subtitle("Ожидание камеры…", 12)
        self.counter = ft.Text("", size=13, color=theme.MUTED)
        self.hint = theme.subtitle(
            f"Рекомендуем {config.SETTINGS.required_photos} снимков: анфас, поворот влево и "
            "вправо, с очками и без, при разном освещении. Больше разнообразия — "
            "надёжнее распознавание.",
            12,
        )
        self.thumbs = ft.GridView(
            expand=True,
            max_extent=118,
            spacing=10,
            run_spacing=10,
            child_aspect_ratio=1.0,
        )
        self.progress = ft.ProgressBar(value=None, height=6, color=theme.ACCENT, bgcolor=theme.alpha(0.12, "#FFFFFF"), visible=False)
        self.progress_text = theme.subtitle("", 12)
        self.save_button = theme.primary_button(
            "Сохранить лицо", icon=ft.Icons.SAVE_ALT if hasattr(ft.Icons, "SAVE_ALT") else ft.Icons.CHECK,
            on_click=self.safe(self._save), expand=True, height=52, disabled=True,
        )
        self._handled_task = None
        self._last_frame = 0.0
        self._photos: list[Path] = []

    # ------------------------------------------------------------------- отрисовка
    def build(self) -> ft.Control:
        self._refresh_photos()

        capture_button = theme.primary_button(
            "Сделать снимок", icon=ft.Icons.PHOTO_CAMERA, on_click=self.safe(self._capture), expand=True, height=50
        )
        import_button = theme.secondary_button(
            "Загрузить фото", icon=ft.Icons.UPLOAD_FILE, on_click=self._import_files, height=50
        )

        preview_card = theme.card(
            ft.Column(
                [
                    self.preview_box,
                    self.camera_hint,
                    self.counter,
                    ft.Row([capture_button, import_button], spacing=10),
                    self.hint,
                ],
                spacing=14,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            expand=5,
        )

        photos_card = theme.card(
            ft.Column(
                [
                    ft.Row(
                        [
                            theme.title("Мои снимки", 17),
                            ft.Container(expand=True),
                            theme.icon_button(ft.Icons.REFRESH, self.safe(lambda e: self._refresh_photos()), "Обновить"),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(content=self.thumbs, expand=True, height=240),
                    self.progress,
                    self.progress_text,
                    ft.Row([self.save_button]),
                ],
                spacing=12,
                expand=True,
            ),
            expand=4,
        )

        back_button = theme.secondary_button(
            "Назад", icon=ft.Icons.ARROW_BACK, on_click=self.safe(lambda e: self.ctx.show("dashboard")), height=40
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            back_button,
                            ft.Column([theme.title("Регистрация лица", 22)], spacing=0),
                            ft.Container(expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=14,
                    ),
                    ft.Row([preview_card, photos_card], spacing=theme.GAP, expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
                ],
                spacing=theme.GAP,
                expand=True,
            ),
            padding=24,
            expand=True,
        )

    # ------------------------------------------------------------------- снимки
    def _refresh_photos(self) -> None:
        self._photos = database.list_photos()
        controls: list[ft.Control] = []
        for path in self._photos:
            controls.append(self._photo_card(path))
        self.thumbs.controls = controls
        needed = max(1, int(config.SETTINGS.required_photos))
        self.counter.value = f"Снимков: {len(self._photos)} (рекомендуется {needed})"
        self.save_button.disabled = not self._photos or (self.ctx.task is not None and self.ctx.task.running)
        if not self._photos:
            self.thumbs.controls = [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.ADD_A_PHOTO, size=32, color=theme.BORDER),
                            theme.subtitle("Пока нет снимков", 12),
                        ],
                        spacing=8,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    alignment=ft.Alignment.CENTER,
                    height=140,
                )
            ]

    def _photo_card(self, path: Path) -> ft.Control:
        uri = database.path_to_data_uri(path, width=240, quality=70)
        image = (
            ft.Image(src=uri, fit=ft.BoxFit.COVER, width=118, height=118, border_radius=12)
            if uri
            else ft.Container(width=118, height=118, bgcolor=theme.SURFACE_ALT, border_radius=12)
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
        return ft.Stack(
            [
                image,
                ft.Container(content=delete, right=4, top=4),
            ]
        )

    def _delete(self, path: Path) -> None:
        database.delete_photo(path)
        self._refresh_photos()

    def _capture(self, event) -> None:
        frame = self.ctx.camera.get_frame(copy=True)
        if frame is None:
            message = self.ctx.camera_error or "Камера недоступна — проверьте подключение"
            self.ctx.toast(message, theme.DANGER)
            return
        try:
            database.add_photo(frame)
            self.ctx.toast("Снимок добавлен")
        except Exception as exc:
            self.ctx.toast(f"Не удалось сохранить снимок: {exc}", theme.DANGER)
            return
        self._refresh_photos()

    async def _import_files(self, event) -> None:
        picker = self.ctx.file_picker
        if picker is None:
            self.ctx.toast("Выбор файлов недоступен на этой платформе", theme.WARN)
            return
        try:
            # with_data=True обязателен для веба и мобильных платформ: там путь к
            # файлу не передаётся, приходит только его содержимое
            files = await picker.pick_files(
                dialog_title="Фотографии владельца",
                allow_multiple=True,
                allowed_extensions=["jpg", "jpeg", "png"],
                with_data=True,
            )
        except Exception as exc:
            logger.exception("Не удалось открыть выбор файлов")
            self.ctx.toast(f"Не удалось открыть выбор файлов: {exc}", theme.DANGER)
            return

        if not files:
            return  # пользователь закрыл диалог

        added = 0
        for file in files:
            name = getattr(file, "name", "") or "файл"
            path = getattr(file, "path", None)
            data = getattr(file, "bytes", None)
            try:
                if path:
                    database.import_photo_file(Path(path))
                elif data:
                    database.import_photo_bytes(data, name)
                else:
                    raise ValueError("файл пришёл без содержимого")
                added += 1
            except Exception as exc:
                logger.warning("Не удалось импортировать %s: %s", name, exc)
                self.ctx.toast(f"{name}: {exc}", theme.DANGER)

        if added:
            self.ctx.toast(f"Добавлено фотографий: {added}")
        self._refresh_photos()

    # ------------------------------------------------------------------- сборка базы
    def _save(self, event) -> None:
        if self.ctx.task is not None and self.ctx.task.running:
            return
        if not self._photos:
            self.ctx.toast("Сначала сделайте хотя бы один снимок", theme.WARN)
            return
        self.save_button.disabled = True
        self.progress.visible = True
        self.progress.value = None
        self.progress_text.value = "Готовим модель распознавания (первый запуск может занять минуту)…"
        self.ctx.run_bg(lambda progress: database.build_database(progress=progress), message="Строим базу лиц…")

    def _check_task(self) -> None:
        task = self.ctx.task
        if task is None or not task.done or task is self._handled_task:
            return
        self._handled_task = task
        self.progress.visible = False
        self.progress_text.value = ""
        self.save_button.disabled = False

        if task.error:
            self.ctx.toast(f"Не удалось построить базу: {task.error}", theme.DANGER)
            return

        report = task.result
        if report is None or not getattr(report, "ok", False):
            summary = report.summary() if report is not None else "нет данных"
            self.ctx.toast(f"Лица не найдены: {summary}", theme.DANGER)
            return

        self.ctx.monitor.reload_faces()
        self.ctx.toast(f"Готово: {report.built} лиц в базе")
        self.ctx.show("dashboard")

    # ------------------------------------------------------------------- цикл
    def tick(self) -> None:
        uri = self.preview_uri(width=420, quality=70)
        if uri:
            self.preview.src = uri
            self._last_frame = time.monotonic()
        if self.ctx.camera.is_open and self._last_frame:
            self.camera_hint.value = "Кадр с камеры обновляется автоматически"
            self.camera_hint.color = theme.MUTED
        else:
            self.camera_hint.value = self.ctx.camera_error or "Ожидание камеры…"
            self.camera_hint.color = theme.WARN if self.ctx.camera_error else theme.MUTED
        self._check_task()

    def on_show(self) -> None:
        self._refresh_photos()
