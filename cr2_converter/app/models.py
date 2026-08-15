"""Modelo de dados da lista de arquivos de origem.

Um ``QAbstractTableModel`` (em vez de ``QTableWidget``) porque a aplicação pode
receber milhares de arquivos: aqui cada linha é um dataclass leve, o tamanho do
arquivo é lido uma única vez na inclusão e a atualização de status durante a
conversão emite ``dataChanged`` apenas para a célula afetada.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt
from PySide6.QtGui import QBrush, QColor

from cr2_converter.core.types import FileStatus
from cr2_converter.utils.filesystem import SourceFile, human_size, path_key, safe_size

__all__ = ["FileEntry", "FileListModel"]

#: Tons médios, escolhidos para manter contraste tanto no tema claro quanto no
#: escuro do Windows.
_STATUS_COLORS = {
    FileStatus.PENDING: None,
    FileStatus.RUNNING: QColor("#1e88e5"),
    FileStatus.CONVERTED: QColor("#2e9e4f"),
    FileStatus.SKIPPED: QColor("#c98a00"),
    FileStatus.ERROR: QColor("#d9534f"),
    FileStatus.CANCELLED: QColor("#8a8a8a"),
}


@dataclass(slots=True)
class FileEntry:
    """Uma linha da lista de origem."""

    path: Path
    root: Path | None = None
    size: int = 0
    status: FileStatus = FileStatus.PENDING
    message: str = ""

    def as_source(self) -> SourceFile:
        return SourceFile(self.path, self.root)


class FileListModel(QAbstractTableModel):
    """Lista de arquivos CR2 com nome, caminho, tamanho e status."""

    COLUMN_NAME = 0
    COLUMN_PATH = 1
    COLUMN_SIZE = 2
    COLUMN_STATUS = 3
    HEADERS = ("Nome", "Caminho", "Tamanho", "Status")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[FileEntry] = []
        self._keys: set[str] = set()

    # -- API Qt --------------------------------------------------------
    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self.HEADERS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return self.HEADERS[section]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == self.COLUMN_NAME:
                return entry.path.name
            if column == self.COLUMN_PATH:
                return str(entry.path.parent)
            if column == self.COLUMN_SIZE:
                return human_size(entry.size)
            if column == self.COLUMN_STATUS:
                return entry.status.label

        elif role == Qt.ItemDataRole.ToolTipRole:
            if column == self.COLUMN_STATUS and entry.message:
                return entry.message
            return str(entry.path)

        elif role == Qt.ItemDataRole.TextAlignmentRole and column == self.COLUMN_SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        elif role == Qt.ItemDataRole.ForegroundRole and column == self.COLUMN_STATUS:
            color = _STATUS_COLORS.get(entry.status)
            return QBrush(color) if color else None

        return None

    # -- API da aplicação ---------------------------------------------
    @property
    def entries(self) -> tuple[FileEntry, ...]:
        return tuple(self._entries)

    def is_empty(self) -> bool:
        return not self._entries

    def entry_at(self, row: int) -> FileEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def add_sources(self, sources: Iterable[SourceFile]) -> tuple[int, int]:
        """Adiciona arquivos ignorando duplicatas.

        :return: ``(adicionados, duplicados_ignorados)``
        """
        new_entries = []
        duplicates = 0
        for source in sources:
            key = path_key(source.path)
            if key in self._keys:
                duplicates += 1
                continue
            self._keys.add(key)
            new_entries.append(
                FileEntry(path=source.path, root=source.root, size=safe_size(source.path))
            )

        if new_entries:
            first = len(self._entries)
            self.beginInsertRows(QModelIndex(), first, first + len(new_entries) - 1)
            self._entries.extend(new_entries)
            self.endInsertRows()
        return len(new_entries), duplicates

    def clear(self) -> None:
        self.beginResetModel()
        self._entries.clear()
        self._keys.clear()
        self.endResetModel()

    def remove_rows(self, rows: Sequence[int]) -> None:
        """Remove as linhas indicadas (em qualquer ordem)."""
        target = {row for row in rows if 0 <= row < len(self._entries)}
        if not target:
            return
        self.beginResetModel()
        self._entries = [e for i, e in enumerate(self._entries) if i not in target]
        self._keys = {path_key(entry.path) for entry in self._entries}
        self.endResetModel()

    def set_status(self, row: int, status: FileStatus, message: str = "") -> None:
        """Atualiza o status de uma linha, notificando somente aquela célula."""
        if not 0 <= row < len(self._entries):
            return
        entry = self._entries[row]
        entry.status = status
        entry.message = message
        index = self.index(row, self.COLUMN_STATUS)
        self.dataChanged.emit(
            index,
            index,
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.ForegroundRole,
                Qt.ItemDataRole.ToolTipRole,
            ],
        )

    def reset_statuses(self) -> None:
        """Volta todas as linhas para "Aguardando" (início de um novo lote)."""
        if not self._entries:
            return
        for entry in self._entries:
            entry.status = FileStatus.PENDING
            entry.message = ""
        top = self.index(0, self.COLUMN_STATUS)
        bottom = self.index(len(self._entries) - 1, self.COLUMN_STATUS)
        self.dataChanged.emit(top, bottom)
