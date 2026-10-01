from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .api import BlizzardAPI, CharacterRef
from .archive import Archive, now
from .config import Config
from .html_view import SECTION_LABELS, generate_html
from .oauth import authorize


class Events(QObject):
    connected = Signal(object)
    exported = Signal(object)
    failure = Signal(str)
    progress = Signal(str)
    screenshot_progress = Signal(object)
    screenshots_imported = Signal(object)


SORT_VALUE_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class AlbumPage(QWebEnginePage):
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

    def acceptNavigationRequest(self, url: QUrl, navigation_type, is_main_frame: bool) -> bool:  # noqa: N802
        if (
            navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
            and url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in self.IMAGE_EXTENSIONS
        ):
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)


class SortableTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(SORT_VALUE_ROLE)
        right = other.data(SORT_VALUE_ROLE)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        return str(left or "").casefold() < str(right or "").casefold()


class CredentialsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Battle.net application")
        form = QFormLayout(self)
        self.region = QComboBox()
        self.region.addItems(["us", "eu", "kr", "tw"])
        self.region.setCurrentText(config.region)
        self.locale = QLineEdit(config.locale)
        self.client_id = QLineEdit(config.client_id)
        self.secret = QLineEdit(config.client_secret)
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Region", self.region)
        form.addRow("Locale", self.locale)
        form.addRow("OAuth client ID", self.client_id)
        form.addRow("OAuth client secret", self.secret)
        note = QLabel(
            "Create an OAuth client in the Battle.net developer portal. Credentials are "
            "saved only in local app settings, never in an archive."
        )
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WoW Time Capsule")
        self.resize(1120, 760)
        self.config = Config.load()
        self.token: dict | None = None
        self.api: BlizzardAPI | None = None
        self.characters: list[CharacterRef] = []
        self.account_raw: dict = {}
        self.sort_column: int | None = None
        self.sort_order = Qt.SortOrder.AscendingOrder
        self.events = Events()
        self.events.connected.connect(self._connected)
        self.events.exported.connect(self._exported)
        self.events.failure.connect(self._error)
        self.events.progress.connect(self._export_progress)
        self.events.screenshot_progress.connect(self._screenshot_import_progress)
        self.events.screenshots_imported.connect(self._screenshots_imported)
        self._export_busy = False
        self._screenshot_import_busy = False

        root = QWidget()
        layout = QVBoxLayout(root)
        title = QLabel("WoW Time Capsule")
        title.setStyleSheet("font-size: 22px; font-weight: bold")
        layout.addWidget(title)
        self.tabs = QTabWidget()
        self.view_tab = self._build_view_tab()
        self.timeline_tab = self._build_timeline_tab()
        self.export_tab = self._build_export_tab()
        self.tabs.addTab(self.view_tab, "View")
        self.tabs.addTab(self.timeline_tab, "Timeline")
        self.tabs.addTab(self.export_tab, "Export")
        layout.addWidget(self.tabs)
        self.setCentralWidget(root)
        QTimer.singleShot(0, self.refresh_view)

    def _build_view_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("Archive:"))
        self.view_archive_edit = QLineEdit(self.config.archive_path)
        row.addWidget(self.view_archive_edit)
        browse = QPushButton("Browse")
        browse.clicked.connect(lambda: self._choose_archive(self.view_archive_edit))
        row.addWidget(browse)
        rebuild = QPushButton("Rebuild HTML")
        rebuild.clicked.connect(self.refresh_view)
        row.addWidget(rebuild)
        open_browser = QPushButton("Open in Browser")
        open_browser.clicked.connect(self.open_html)
        row.addWidget(open_browser)
        layout.addLayout(row)

        memory_row = QHBoxLayout()
        memory_row.addWidget(QLabel("Add note to:"))
        self.view_character_combo = QComboBox()
        self.view_character_combo.currentIndexChanged.connect(
            self._show_selected_character
        )
        memory_row.addWidget(self.view_character_combo, 1)
        note = QPushButton("Add Note")
        note.clicked.connect(self.add_memory)
        memory_row.addWidget(note)
        memory_row.addStretch()
        layout.addLayout(memory_row)
        screenshot_row = QHBoxLayout()
        screenshot_row.addWidget(QLabel("Screenshots (Timeline):"))
        self.screenshot_button = QPushButton("Add Screenshot")
        self.screenshot_button.clicked.connect(self.add_screenshot)
        screenshot_row.addWidget(self.screenshot_button)
        self.screenshot_folder_button = QPushButton("Add Screenshot Folder")
        self.screenshot_folder_button.clicked.connect(self.import_screenshot_folder)
        screenshot_row.addWidget(self.screenshot_folder_button)
        self.screenshot_rescan_button = QPushButton("Rescan Screenshot Folders")
        self.screenshot_rescan_button.clicked.connect(self.rescan_screenshot_folders)
        screenshot_row.addWidget(self.screenshot_rescan_button)
        screenshot_row.addStretch()
        layout.addLayout(screenshot_row)
        self.view_status = QLabel("")
        layout.addWidget(self.view_status)

        self.viewer = QWebEngineView()
        self.viewer.setPage(AlbumPage(self.viewer))
        self.viewer.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        layout.addWidget(self.viewer, 1)
        return tab

    def _build_timeline_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("Archive:"))
        self.timeline_archive_edit = QLineEdit(self.config.archive_path)
        row.addWidget(self.timeline_archive_edit)
        browse = QPushButton("Browse")
        browse.clicked.connect(lambda: self._choose_archive(self.timeline_archive_edit))
        row.addWidget(browse)
        refresh = QPushButton("Refresh Timeline")
        refresh.clicked.connect(self._refresh_from_timeline)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.timeline_viewer = QWebEngineView()
        self.timeline_viewer.setPage(AlbumPage(self.timeline_viewer))
        self.timeline_viewer.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        self.timeline_viewer.loadFinished.connect(self._timeline_loaded)
        layout.addWidget(self.timeline_viewer, 1)
        return tab

    def _build_export_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("Export destination:"))
        self.export_archive_edit = QLineEdit(self.config.archive_path)
        row.addWidget(self.export_archive_edit)
        browse = QPushButton("Browse")
        browse.clicked.connect(lambda: self._choose_archive(self.export_archive_edit))
        row.addWidget(browse)
        layout.addLayout(row)

        layout.addWidget(QLabel("Battle.net"))
        row = QHBoxLayout()
        self.connect_button = QPushButton("Connect Battle.net")
        self.connect_button.clicked.connect(self.connect)
        row.addWidget(self.connect_button)
        self.status = QLabel("Status: Not Connected")
        row.addWidget(self.status)
        row.addStretch()
        layout.addLayout(row)

        layout.addWidget(QLabel("Characters — select one or more rows"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Game", "Realm", "Character", "Level", "Class"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.table.horizontalHeader().sectionClicked.connect(self._sort_by_column)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.table, 2)

        controls = QHBoxLayout()
        manual = QPushButton("Add Manual Character")
        manual.clicked.connect(self.add_manual)
        controls.addWidget(manual)
        self.export_button = QPushButton("Export Selected Characters")
        self.export_button.clicked.connect(self.export_selected)
        controls.addWidget(self.export_button)
        rebuild = QPushButton("Rebuild HTML from Existing Archive")
        rebuild.clicked.connect(self._rebuild_from_export)
        controls.addWidget(rebuild)
        controls.addStretch()
        layout.addLayout(controls)

        layout.addWidget(QLabel("Capture results"))
        self.results = QTableWidget(0, 3)
        self.results.setHorizontalHeaderLabels(["Character", "Section", "Result"])
        self.results.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.results.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.results.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.results.cellDoubleClicked.connect(self._show_result_detail)
        layout.addWidget(self.results, 1)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        return tab

    def _choose_archive(self, source: QLineEdit) -> None:
        result = QFileDialog.getExistingDirectory(self, "Archive", source.text())
        if not result:
            return
        self._set_archive_path(result)
        self.refresh_view()

    def _set_archive_path(self, path: str) -> None:
        self.view_archive_edit.setText(path)
        self.timeline_archive_edit.setText(path)
        self.export_archive_edit.setText(path)
        self.config.archive_path = path
        self.config.save()

    def save_config(self) -> None:
        path = self.export_archive_edit.text().strip() or self.view_archive_edit.text().strip()
        self._set_archive_path(path)

    def connect(self) -> None:
        dialog = CredentialsDialog(self.config, self)
        if not dialog.exec():
            return
        self.config.region = dialog.region.currentText()
        self.config.locale = dialog.locale.text().strip()
        self.config.client_id = dialog.client_id.text().strip()
        self.config.client_secret = dialog.secret.text()
        self.save_config()
        if not self.config.client_id or not self.config.client_secret:
            self._error("Client ID and secret are required.")
            return
        self.connect_button.setEnabled(False)
        self.status.setText("Status: Waiting for browser authorization…")

        def work():
            try:
                token = authorize(
                    self.config.region, self.config.client_id, self.config.client_secret
                )
                api = BlizzardAPI(
                    self.config.region, self.config.locale, token["access_token"]
                )
                chars, raw, status = api.discover_characters()
                self.events.connected.emit((token, api, chars, raw, status))
            except Exception as exc:
                self.events.failure.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _connected(self, result: object) -> None:
        self.token, self.api, self.characters, raw, _status = result
        self.account_raw = raw
        self.status.setText("Status: Connected")
        self.connect_button.setEnabled(True)
        self._populate()

    def _populate(self) -> None:
        self.table.setRowCount(len(self.characters))
        for row, char in enumerate(self.characters):
            values = (
                char.game_version,
                char.realm_name,
                char.name,
                char.level,
                char.playable_class,
            )
            for col, value in enumerate(values):
                item = SortableTableWidgetItem("" if value is None else str(value))
                item.setData(Qt.ItemDataRole.UserRole, row)
                item.setData(SORT_VALUE_ROLE, value)
                self.table.setItem(row, col, item)
        if self.sort_column is not None:
            self.table.sortItems(self.sort_column, self.sort_order)

    def _sort_by_column(self, column: int) -> None:
        if column == self.sort_column:
            self.sort_order = (
                Qt.SortOrder.DescendingOrder
                if self.sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self.sort_column = column
            self.sort_order = Qt.SortOrder.AscendingOrder
        self.table.sortItems(column, self.sort_order)
        self.table.horizontalHeader().setSortIndicator(column, self.sort_order)
        self.table.horizontalHeader().setSortIndicatorShown(True)

    def add_manual(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Manual character")
        form = QFormLayout(dialog)
        region = QComboBox()
        region.addItems(["us", "eu", "kr", "tw"])
        region.setCurrentText(self.config.region)
        game = QComboBox()
        game.addItem("Retail", "profile")
        game.addItem("Classic progression", "profile-classic")
        game.addItem("Classic Era / Hardcore / seasonal", "profile-classic1x")
        realm = QLineEdit()
        name = QLineEdit()
        form.addRow("Region", region)
        form.addRow("Game version", game)
        form.addRow("Realm slug", realm)
        form.addRow("Character name", name)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() and realm.text().strip() and name.text().strip():
            self.characters.append(
                CharacterRef(
                    region.currentText(), None, realm.text().strip(), realm.text().strip(),
                    None, name.text().strip(), namespace=str(game.currentData())
                )
            )
            self._populate()

    def _selected_characters(self) -> list[CharacterRef]:
        indexes: set[int] = set()
        for model_index in self.table.selectionModel().selectedRows():
            item = self.table.item(model_index.row(), 0)
            value = item.data(Qt.ItemDataRole.UserRole) if item else None
            if isinstance(value, int) and 0 <= value < len(self.characters):
                indexes.add(value)
        return [self.characters[index] for index in sorted(indexes)]

    def export_selected(self) -> None:
        characters = self._selected_characters()
        if not characters:
            self._error("Select one or more characters first.")
            return
        if not self.api or any(self.api.region != char.region for char in characters):
            self._error("Connect Battle.net for the selected characters' region first.")
            return
        archive_path = self.export_archive_edit.text().strip()
        if not archive_path:
            self._error("Choose an export destination first.")
            return
        self.save_config()
        self._set_export_busy(True)
        self.message.setText("Export started — preparing the selected characters…")
        self.results.setRowCount(0)

        def work():
            started = time.perf_counter()
            summaries: list[dict] = []
            total = len(characters)
            for position, char in enumerate(characters, 1):
                archive = None
                try:
                    self.events.progress.emit(
                        f"Exporting {position}/{total}: {char.name} — starting profile"
                    )
                    archive = Archive(archive_path)
                    with archive.run(region=char.region, locale=self.config.locale) as run_id:
                        observed = now()
                        if self.account_raw:
                            archive.save_raw(
                                run_id, "account", "/profile/user/wow",
                                self.account_raw, 200, observed,
                            )
                        captured = self.api.capture_character(
                            char,
                            lambda name, endpoint, payload, status: archive.save_raw(
                                run_id, name, endpoint, payload, status, observed
                            ),
                            archive.achievement_reference_ids(),
                            lambda stage, char=char, position=position: self.events.progress.emit(
                                f"Exporting {position}/{total}: {char.name} — {stage}"
                            ),
                            archive.quest_reference_ids(),
                        )
                        snapshot_id = archive.import_capture(run_id, char, captured, observed)
                        sections = archive.capture_summary(snapshot_id)
                    summaries.append({"character": char.name, "sections": sections})
                except Exception as exc:
                    summaries.append({
                        "character": char.name,
                        "sections": [{
                            "section": "export", "status": "request_failed",
                            "count": None, "detail": str(exc),
                        }],
                    })
                finally:
                    if archive:
                        archive.close()
            try:
                self.events.progress.emit("Generating the offline HTML album…")
                generate_html(archive_path)
            except Exception as exc:
                summaries.append({
                    "character": "Archive", "sections": [{
                        "section": "html", "status": "request_failed",
                        "count": None, "detail": str(exc),
                    }],
                })
            self.events.exported.emit({
                "archive": archive_path,
                "summaries": summaries,
                "elapsed": time.perf_counter() - started,
            })

        threading.Thread(target=work, daemon=True).start()

    def _result_text(self, section: dict) -> str:
        status = section.get("status")
        count = section.get("count")
        detail = section.get("detail") or ""
        if status == "captured":
            if "Basic identity captured" in detail:
                return "Captured basic account data only — double-click for details"
            if "authenticated protected-character" in detail:
                return "Captured via authenticated profile — double-click for details"
            return f"Captured — {count} record{'s' if count != 1 else ''}"
        if status == "unavailable":
            return f"Unavailable{f' — {detail}' if detail else ''}"
        if "Blizzard has no profile" in detail:
            return "Profile unavailable (404) — double-click for details"
        summary = detail.split("\n", 1)[0]
        if len(summary) > 140:
            summary = summary[:137] + "…"
        return f"Request failed{f' — {summary}' if summary else ''}"

    def _exported(self, result: object) -> None:
        summaries = result["summaries"]
        rows = sum(len(item["sections"]) for item in summaries)
        self.results.setRowCount(rows)
        row = 0
        failures = 0
        for summary in summaries:
            for section in summary["sections"]:
                if section.get("status") == "request_failed":
                    failures += 1
                label = SECTION_LABELS.get(
                    section["section"], section["section"].replace("_", " ").title()
                )
                self.results.setItem(row, 0, QTableWidgetItem(summary["character"]))
                self.results.setItem(row, 1, QTableWidgetItem(label))
                result_item = QTableWidgetItem(self._result_text(section))
                result_item.setToolTip(section.get("detail") or result_item.text())
                self.results.setItem(row, 2, result_item)
                row += 1
        elapsed = float(result.get("elapsed", 0))
        outcome = (
            f"completed with {failures} failed section{'s' if failures != 1 else ''}"
            if failures else "completed successfully"
        )
        self.message.setText(
            f"Export {outcome} in {elapsed:.1f} seconds. "
            "Double-click any result with details for the full explanation."
        )
        self._set_archive_path(result["archive"])
        self.refresh_view()
        if not failures:
            self.tabs.setCurrentWidget(self.view_tab)
        self._set_export_busy(False)

    def _rebuild_from_export(self) -> None:
        self._set_archive_path(self.export_archive_edit.text().strip())
        self.refresh_view()
        self.tabs.setCurrentWidget(self.view_tab)

    def refresh_view(self) -> None:
        path = Path(self.view_archive_edit.text().strip())
        database = path / "wow_archive.sqlite"
        if not database.is_file():
            empty = (
                "<html><body style='font:16px Segoe UI;background:#111722;color:#e8edf6;"
                "padding:40px'><h2>Choose an existing archive</h2><p>View and Timeline "
                "work without Battle.net credentials. Select a folder containing "
                "<code>wow_archive.sqlite</code>.</p></body></html>"
            )
            self.viewer.setHtml(empty)
            self.timeline_viewer.setHtml(empty)
            self.view_character_combo.clear()
            return
        try:
            archive = Archive(path)
            archive.close()
            html_path = generate_html(path)
            self.viewer.setUrl(QUrl.fromLocalFile(str(html_path)))
            self.timeline_viewer.setUrl(QUrl.fromLocalFile(str(html_path)))
            self._load_view_characters(database)
        except Exception as exc:
            self._error(f"Could not open archive: {exc}")

    def _timeline_loaded(self, successful: bool) -> None:
        if successful:
            self.timeline_viewer.page().runJavaScript(
                "if (typeof timeline === 'function') timeline()"
            )

    def _refresh_from_timeline(self) -> None:
        self._set_archive_path(self.timeline_archive_edit.text().strip())
        self.refresh_view()

    def _load_view_characters(self, database: Path) -> None:
        db = sqlite3.connect(database)
        rows = db.execute(
            "SELECT character_id,character_name,realm_name FROM character c "
            "WHERE EXISTS (SELECT 1 FROM character_snapshot s "
            "JOIN archive_run r ON r.archive_run_id=s.archive_run_id "
            "WHERE s.character_id=c.character_id AND r.status='complete') "
            "ORDER BY character_name COLLATE NOCASE,realm_name COLLATE NOCASE"
        ).fetchall()
        db.close()
        self.view_character_combo.clear()
        for character_id, name, realm in rows:
            self.view_character_combo.addItem(f"{name} — {realm or 'unknown realm'}", character_id)

    def _view_character_id(self) -> int | None:
        value = self.view_character_combo.currentData()
        return value if isinstance(value, int) else None

    def _show_selected_character(self, _index: int = -1) -> None:
        character_id = self._view_character_id()
        if character_id is not None:
            self.viewer.page().runJavaScript(f"showCharacterById({character_id})")

    def add_screenshot(self) -> None:
        archive_path = self.view_archive_edit.text().strip()
        if not (Path(archive_path) / "wow_archive.sqlite").is_file():
            self._error("Open an archive before adding screenshot links.")
            return
        source = QFileDialog.getOpenFileName(
            self, "Add screenshot", "", "Images (*.png *.jpg *.jpeg *.webp);;All files (*)"
        )[0]
        if not source:
            return
        caption, accepted = QInputDialog.getText(self, "Screenshot caption", "Caption:")
        if not accepted:
            return
        archive = Archive(archive_path)
        try:
            archive.add_screenshot(source, caption)
        finally:
            archive.close()
        self.refresh_view()

    def import_screenshot_folder(self) -> None:
        archive_path = self.view_archive_edit.text().strip()
        if not (Path(archive_path) / "wow_archive.sqlite").is_file():
            self._error("Open an archive before adding a screenshot folder.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose screenshot root folder")
        if not folder:
            return
        answer = QMessageBox.question(
            self,
            "Import screenshot folder",
            f"Recursively import supported images from:\n{folder}\n\n"
            "Only file links and dates will be stored. Images will not be copied. "
            "The folder will be registered for later rescans.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_screenshot_import_busy(True)
        self.view_status.setText("Scanning screenshot folders…")

        def work():
            archive = None
            try:
                archive = Archive(archive_path)
                result = archive.import_screenshot_folder(
                    folder, self.events.screenshot_progress.emit
                )
                result["folder"] = folder
            except Exception as exc:
                result = {"error": str(exc), "folder": folder}
            finally:
                if archive:
                    archive.close()
            self.events.screenshots_imported.emit(result)

        threading.Thread(target=work, daemon=True).start()

    def rescan_screenshot_folders(self) -> None:
        archive_path = self.view_archive_edit.text().strip()
        if not (Path(archive_path) / "wow_archive.sqlite").is_file():
            self._error("Open an archive before rescanning screenshot folders.")
            return
        self._set_screenshot_import_busy(True)
        self.view_status.setText("Rescanning registered screenshot folders…")

        def work():
            archive = None
            try:
                archive = Archive(archive_path)
                result = archive.rescan_screenshot_folders(
                    self.events.screenshot_progress.emit
                )
            except Exception as exc:
                result = {"error": str(exc)}
            finally:
                if archive:
                    archive.close()
            self.events.screenshots_imported.emit(result)

        threading.Thread(target=work, daemon=True).start()

    def _screenshot_import_progress(self, result: object) -> None:
        self.view_status.setText(
            f"Scanning screenshots: {result['scanned']:,} found, "
            f"{result['imported']:,} new, {result.get('updated', 0):,} updated"
        )

    def _screenshots_imported(self, result: object) -> None:
        self._set_screenshot_import_busy(False)
        if result.get("error"):
            self.view_status.setText("Screenshot import failed.")
            QMessageBox.critical(self, "Screenshot import", result["error"])
            return
        self.view_status.setText(
            f"Screenshot scan finished: {result.get('imported', 0):,} new links, "
            f"{result.get('updated', 0):,} updated, "
            f"{result.get('unchanged', 0):,} unchanged, "
            f"{result.get('missing', 0):,} missing, {result.get('errors', 0):,} errors."
        )
        self.refresh_view()

    def _set_screenshot_import_busy(self, busy: bool) -> None:
        if busy == self._screenshot_import_busy:
            return
        self._screenshot_import_busy = busy
        self.screenshot_button.setEnabled(not busy)
        self.screenshot_folder_button.setEnabled(not busy)
        self.screenshot_rescan_button.setEnabled(not busy)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        elif QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

    def add_memory(self) -> None:
        character_id = self._view_character_id()
        if character_id is None:
            self._error("Open an archive and choose a character first.")
            return
        title, accepted = QInputDialog.getText(self, "Memory title", "Title:")
        if not accepted:
            return
        body, accepted = QInputDialog.getMultiLineText(self, "Memory", "Story or note:")
        if not accepted or not body.strip():
            return
        archive = Archive(self.view_archive_edit.text().strip())
        try:
            archive.add_memory(character_id, title, body)
        finally:
            archive.close()
        self.refresh_view()

    def open_html(self) -> None:
        path = Path(self.view_archive_edit.text().strip()) / "index.html"
        if not path.is_file():
            self.refresh_view()
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        else:
            self._error("This archive does not have an HTML summary yet.")

    def _error(self, message: str) -> None:
        self._set_export_busy(False)
        self.connect_button.setEnabled(True)
        self.message.setText(message)
        QMessageBox.critical(self, "WoW Time Capsule", message)

    def _export_progress(self, message: str) -> None:
        self.message.setText(message)

    def _set_export_busy(self, busy: bool) -> None:
        if busy == self._export_busy:
            return
        self._export_busy = busy
        self.export_button.setEnabled(not busy)
        self.connect_button.setEnabled(not busy)
        self.table.setEnabled(not busy)
        if busy:
            self.status.setText("Status: Connected — Exporting…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        elif QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        if not busy and self.api:
            self.status.setText("Status: Connected")

    def _show_result_detail(self, row: int, _column: int) -> None:
        item = self.results.item(row, 2)
        if item and item.toolTip():
            QMessageBox.information(self, "Capture result details", item.toolTip())

    def closeEvent(self, event) -> None:  # noqa: N802
        self._set_export_busy(False)
        self.save_config()
        if self.api:
            self.api.close()
        super().closeEvent(event)


def run() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
