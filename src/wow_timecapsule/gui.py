from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from PySide6.QtCore import QUrl

from .adapters.wow_export import WowExportAdapter
from .api import BlizzardAPI, CharacterRef
from .archive import Archive, now
from .config import Config
from .install import detect_products
from .oauth import authorize
from .model_spec import character_export_spec, default_pet, pet_display_id
from .world import MapTile, SpawnPoint


class Events(QObject):
    connected = Signal(object)
    exported = Signal(str)
    failure = Signal(str)


class CredentialsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent); self.setWindowTitle("Battle.net application")
        form = QFormLayout(self)
        self.region = QComboBox(); self.region.addItems(["us", "eu", "kr", "tw"]); self.region.setCurrentText(config.region)
        self.locale = QLineEdit(config.locale); self.client_id = QLineEdit(config.client_id)
        self.secret = QLineEdit(config.client_secret); self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Region", self.region); form.addRow("Locale", self.locale); form.addRow("OAuth client ID", self.client_id); form.addRow("OAuth client secret", self.secret)
        note = QLabel("Create an OAuth client in the Battle.net developer portal. Credentials are saved only in local app settings, never in an archive."); note.setWordWrap(True); form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); form.addRow(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("WoW Time Capsule"); self.resize(850, 600)
        self.config = Config.load(); self.token: dict | None = None; self.api: BlizzardAPI | None = None; self.characters: list[CharacterRef] = []; self.account_raw: dict = {}
        self.events = Events(); self.events.connected.connect(self._connected); self.events.exported.connect(self._exported); self.events.failure.connect(self._error)
        root = QWidget(); layout = QVBoxLayout(root); title = QLabel("WoW Time Capsule"); title.setStyleSheet("font-size: 22px; font-weight: bold"); layout.addWidget(title)
        self.wow_edit = self._path_row(layout, "WoW Installation:", self.config.wow_path, True)
        self.export_edit = self._path_row(layout, "wow.export:", self.config.wow_export_path, False)
        self.archive_edit = self._path_row(layout, "Archive:", self.config.archive_path, True)
        layout.addWidget(QLabel("Battle.net")); row = QHBoxLayout(); self.connect_button = QPushButton("Connect Battle.net"); self.connect_button.clicked.connect(self.connect); row.addWidget(self.connect_button); self.status = QLabel("Status: Not Connected"); row.addWidget(self.status); row.addStretch(); layout.addLayout(row)
        layout.addWidget(QLabel("Characters")); self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["Realm", "Character", "Level", "Class"]); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); layout.addWidget(self.table)
        self.assets = QCheckBox("Export character GLB and default companion pet"); self.assets.setChecked(True); layout.addWidget(self.assets)
        controls = QHBoxLayout(); manual = QPushButton("Add Manual Character"); manual.clicked.connect(self.add_manual); controls.addWidget(manual); export = QPushButton("Export Selected Character"); export.clicked.connect(self.export_selected); controls.addWidget(export); open_archive = QPushButton("Open Archive"); open_archive.clicked.connect(self.open_archive); controls.addWidget(open_archive); controls.addStretch(); layout.addLayout(controls)
        world = QPushButton("Export World Area"); world.clicked.connect(self.export_world); controls.insertWidget(2, world)
        self.message = QLabel(""); self.message.setWordWrap(True); layout.addWidget(self.message); self.setCentralWidget(root)

    def _path_row(self, parent: QVBoxLayout, label: str, value: str, directory: bool) -> QLineEdit:
        row = QHBoxLayout(); row.addWidget(QLabel(label)); edit = QLineEdit(value); row.addWidget(edit); button = QPushButton("Browse")
        def browse():
            result = QFileDialog.getExistingDirectory(self, label, edit.text()) if directory else QFileDialog.getOpenFileName(self, label, edit.text(), "Executables (*.exe);;All files (*)")[0]
            if result: edit.setText(result); self.save_config()
        button.clicked.connect(browse); row.addWidget(button); parent.addLayout(row); return edit

    def save_config(self) -> None:
        self.config.wow_path = self.wow_edit.text(); self.config.wow_export_path = self.export_edit.text(); self.config.archive_path = self.archive_edit.text(); self.config.save()

    def connect(self) -> None:
        dialog = CredentialsDialog(self.config, self)
        if not dialog.exec(): return
        self.config.region = dialog.region.currentText(); self.config.locale = dialog.locale.text().strip(); self.config.client_id = dialog.client_id.text().strip(); self.config.client_secret = dialog.secret.text(); self.save_config()
        if not self.config.client_id or not self.config.client_secret: self._error("Client ID and secret are required."); return
        self.connect_button.setEnabled(False); self.status.setText("Status: Waiting for browser authorization…")
        def work():
            try:
                token = authorize(self.config.region, self.config.client_id, self.config.client_secret)
                api = BlizzardAPI(self.config.region, self.config.locale, token["access_token"]); chars, raw, status = api.discover_characters()
                self.events.connected.emit((token, api, chars, raw, status))
            except Exception as exc: self.events.failure.emit(str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _connected(self, result: object) -> None:
        self.token, self.api, self.characters, raw, status = result
        self.account_raw = raw
        self.status.setText("Status: Connected"); self.connect_button.setEnabled(True); self._populate()

    def _populate(self) -> None:
        self.table.setRowCount(len(self.characters))
        for row, char in enumerate(self.characters):
            for col, value in enumerate((char.realm_name, char.name, char.level or "", char.playable_class)):
                item = QTableWidgetItem(str(value)); item.setData(Qt.ItemDataRole.UserRole, row); self.table.setItem(row, col, item)

    def add_manual(self) -> None:
        dialog = QDialog(self); dialog.setWindowTitle("Manual character"); form = QFormLayout(dialog); region = QComboBox(); region.addItems(["us", "eu", "kr", "tw"]); region.setCurrentText(self.config.region); realm = QLineEdit(); name = QLineEdit(); form.addRow("Region", region); form.addRow("Realm slug", realm); form.addRow("Character name", name); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() and realm.text().strip() and name.text().strip(): self.characters.append(CharacterRef(region.currentText(), None, realm.text().strip(), realm.text().strip(), None, name.text().strip())); self._populate()

    def export_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0: self._error("Select a character first."); return
        if not self.api or self.api.region != self.characters[row].region: self._error("Connect Battle.net for this character's region first."); return
        archive_path = self.archive_edit.text().strip()
        if not archive_path: self._error("Choose an archive folder first."); return
        self.save_config(); char = self.characters[row]; export_assets = self.assets.isChecked(); self.message.setText("Exporting…")
        products = detect_products(self.wow_edit.text()); product = products[0] if products else None
        def work():
            archive = None
            try:
                archive = Archive(archive_path); adapter = WowExportAdapter(self.export_edit.text()); probe = adapter.write_diagnostic(archive.root / "logs" / f"wow_export_probe_{now().replace(':', '')}.json")
                with archive.run(region=char.region, locale=self.config.locale, product=product.product if product else "", build=product.version if product else "", wow_export_version=probe.version) as run_id:
                    observed = now()
                    if self.account_raw:
                        archive.save_raw(run_id, "account", "/profile/user/wow", self.account_raw, 200, observed)
                    captured = self.api.capture_character(char, lambda name, endpoint, payload, status: archive.save_raw(run_id, name, endpoint, payload, status, observed))
                    snapshot_id = archive.import_capture(run_id, char, captured, observed)
                    if export_assets:
                        if not probe.automation_available:
                            raise RuntimeError("3D export requested, but no compatible wow-timecapsule-bridge/v1 service is running on 127.0.0.1:17890")
                        if product is None:
                            raise RuntimeError("3D export requested, but no supported WoW installation product was detected")
                        adapter.open_installation(product.path, product.product)
                        with tempfile.TemporaryDirectory(prefix="wow-timecapsule-") as staging:
                            staging_root = Path(staging)
                            spec = character_export_spec(char, captured)
                            character_result = adapter.export_character(spec, staging_root / "character")
                            archive.preserve_character_export(run_id, snapshot_id, char, observed, spec, character_result.files, character_result.metadata)
                            pet = default_pet(captured)
                            if pet:
                                pet_result = adapter.export_creature(pet_display_id(pet), staging_root / "pet")
                                archive.preserve_pet_export(run_id, snapshot_id, pet, pet_result.files, pet_result.metadata)
                self.events.exported.emit(f"Exported {char.name} to {archive_path}")
            except Exception as exc: self.events.failure.emit(str(exc))
            finally:
                if archive: archive.close()
        threading.Thread(target=work, daemon=True).start()

    def export_world(self) -> None:
        dialog = QDialog(self); dialog.setWindowTitle("World Locations")
        form = QFormLayout(dialog); map_id = QLineEdit("0"); tiles = QLineEdit("32,32")
        name = QLineEdit("Small test area"); spawn = QLineEdit("0,0,0,0")
        form.addRow("Map ID", map_id); form.addRow("Tiles (x,y; x,y)", tiles)
        form.addRow("Name", name); form.addRow("Spawn (x,y,z,heading)", spawn)
        note = QLabel("Choose only a small number of adjacent ADT tiles. Whole-continent exports are intentionally unsupported.")
        note.setWordWrap(True); form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if not dialog.exec(): return
        try:
            selected_tiles = [MapTile(*(int(part.strip()) for part in value.split(",")))
                              for value in tiles.text().split(";") if value.strip()]
            spawn_values = [float(value.strip()) for value in spawn.text().split(",")]
            if len(spawn_values) != 4 or not selected_tiles: raise ValueError
            if len(selected_tiles) > 16: raise ValueError("Select at most 16 tiles")
            selected_map = int(map_id.text()); selected_name = name.text().strip()
            if selected_map < 0 or not selected_name: raise ValueError
            selected_spawn = SpawnPoint(*spawn_values)
        except (TypeError, ValueError) as exc:
            self._error(str(exc) or "Enter a valid map ID, name, tile list, and four-value spawn point."); return
        archive_path = self.archive_edit.text().strip()
        products = detect_products(self.wow_edit.text()); product = products[0] if products else None
        if not archive_path or product is None:
            self._error("Choose an archive folder and a supported WoW installation first."); return
        self.save_config(); self.message.setText("Exporting world area…")
        def work():
            archive = None
            try:
                archive = Archive(archive_path); adapter = WowExportAdapter(self.export_edit.text())
                probe = adapter.write_diagnostic(archive.root / "logs" / f"wow_export_probe_{now().replace(':', '')}.json")
                if not probe.automation_available: raise RuntimeError("No compatible localhost wow.export bridge is running.")
                adapter.open_installation(product.path, product.product)
                with archive.run(region=self.config.region, locale=self.config.locale, product=product.product,
                                 build=product.version, wow_export_version=probe.version) as run_id:
                    with tempfile.TemporaryDirectory(prefix="wow-timecapsule-map-") as staging:
                        result = adapter.export_map(selected_map, [tile.as_bridge_value() for tile in selected_tiles], Path(staging))
                        archive.preserve_map_export(run_id, selected_map, selected_name, product.version,
                                                    result.files, result.metadata, selected_spawn)
                self.events.exported.emit(f"Exported {selected_name} to {archive_path}")
            except Exception as exc: self.events.failure.emit(str(exc))
            finally:
                if archive: archive.close()
        threading.Thread(target=work, daemon=True).start()

    def open_archive(self) -> None:
        path = Path(self.archive_edit.text())
        if path.exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        else: self._error("Archive folder does not exist.")

    def _error(self, message: str) -> None:
        self.connect_button.setEnabled(True); self.message.setText(message); QMessageBox.critical(self, "WoW Time Capsule", message)

    def _exported(self, message: str) -> None:
        self.message.setText(message)
        QMessageBox.information(self, "WoW Time Capsule", message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.save_config()
        if self.api: self.api.close()
        super().closeEvent(event)


def run() -> int:
    app = QApplication(sys.argv); window = MainWindow(); window.show(); return app.exec()
