from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from travel_photo_mapper.i18n import tr, trn


class AlbumExportDialog(QDialog):
    def __init__(self, title: str, photo_count: int, parent_folder: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("album.export_title"))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        description = QLabel(tr("album.description", count=trn("count.photos", photo_count)))
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.title_edit = QLineEdit(title)
        form.addRow(tr("album.title"), self.title_edit)
        folder_row = QWidget()
        row = QHBoxLayout(folder_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.folder_edit = QLineEdit(parent_folder)
        browse = QPushButton(tr("album.browse"))
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        form.addRow(tr("album.destination"), folder_row)
        layout.addLayout(form)
        self.gps_check = QCheckBox(tr("album.include_gps"))
        self.gps_check.setChecked(True)
        layout.addWidget(self.gps_check)
        hint = QLabel(tr("album.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("album.export"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("toolbar.cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.title_edit.textChanged.connect(self._validate)
        self.folder_edit.textChanged.connect(self._validate)
        self._validate()

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, tr("album.destination"), self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def _validate(self):
        enabled = (bool(self.title_edit.text().strip()) and bool(self.folder_edit.text().strip())
                   and Path(self.folder_edit.text()).is_dir())
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(enabled)
