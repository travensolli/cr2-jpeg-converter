"""Diálogos: resolução de conflitos e relatório final.

Os conflitos com arquivos já existentes são resolvidos **antes** de o lote
começar, ainda na thread da interface. Isso evita que uma thread de trabalho
precise parar no meio da conversão para perguntar algo ao usuário — o que
exigiria sincronização entre threads e poderia travar a aplicação caso a janela
fosse fechada enquanto a pergunta estivesse aberta.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cr2_converter.core.types import ConflictPolicy, ConversionJob, ConversionResult, FileStatus

__all__ = ["ReportDialog", "resolve_conflicts"]

_log = logging.getLogger(__name__)

_MAX_LISTED_CONFLICTS = 12


def resolve_conflicts(
    parent: QWidget,
    jobs: Sequence[ConversionJob],
    policy: ConflictPolicy,
    conflicts: Sequence[ConversionJob],
) -> list[ConversionJob] | None:
    """Define o campo ``overwrite`` de cada trabalho conforme a política.

    :param conflicts: trabalhos cujo destino já existe.
    :return: a lista de trabalhos atualizada, ou ``None`` se o usuário cancelou
        a operação inteira.
    """
    if not conflicts:
        return list(jobs)

    if policy is ConflictPolicy.OVERWRITE:
        return [replace(job, overwrite=True) for job in jobs]
    if policy is ConflictPolicy.SKIP:
        # overwrite=False já faz o conversor devolver "Ignorado" com o motivo.
        return list(jobs)

    decision = _ask_global(parent, conflicts)
    if decision is None:
        return None
    if decision is True:
        return [replace(job, overwrite=True) for job in jobs]
    if decision is False:
        return list(jobs)
    return _ask_individually(parent, jobs, conflicts)


def _ask_global(parent: QWidget, conflicts: Sequence[ConversionJob]) -> bool | str | None:
    """Pergunta o que fazer com todos os conflitos de uma vez.

    :return: ``True`` (sobrescrever tudo), ``False`` (ignorar tudo),
        ``"individual"`` (decidir um a um) ou ``None`` (cancelar).
    """
    names = [job.destination.name for job in conflicts[:_MAX_LISTED_CONFLICTS]]
    listing = "\n".join(f"• {name}" for name in names)
    if len(conflicts) > _MAX_LISTED_CONFLICTS:
        listing += f"\n… e mais {len(conflicts) - _MAX_LISTED_CONFLICTS} arquivo(s)."

    box = QMessageBox(parent)
    box.setWindowTitle("Arquivos já existentes")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(
        f"{len(conflicts)} arquivo(s) JPEG já existem na pasta de destino.\n"
        "O que você deseja fazer?"
    )
    box.setInformativeText(listing)
    overwrite_button = box.addButton("Sobrescrever todos", QMessageBox.ButtonRole.DestructiveRole)
    skip_button = box.addButton("Ignorar todos", QMessageBox.ButtonRole.AcceptRole)
    each_button = box.addButton("Decidir um a um", QMessageBox.ButtonRole.ActionRole)
    cancel_button = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(skip_button)
    box.exec()

    clicked = box.clickedButton()
    if clicked is overwrite_button:
        return True
    if clicked is skip_button:
        return False
    if clicked is each_button:
        return "individual"
    if clicked is cancel_button:
        return None
    return None


def _ask_individually(
    parent: QWidget,
    jobs: Sequence[ConversionJob],
    conflicts: Sequence[ConversionJob],
) -> list[ConversionJob] | None:
    """Pergunta arquivo por arquivo, com atalhos "para todos"."""
    conflicting = {job.destination: False for job in conflicts}
    apply_to_all: bool | None = None

    for job in conflicts:
        if apply_to_all is not None:
            conflicting[job.destination] = apply_to_all
            continue

        box = QMessageBox(parent)
        box.setWindowTitle("Arquivo já existe")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"“{job.destination.name}” já existe.\nDeseja sobrescrever?")
        box.setInformativeText(str(job.destination.parent))
        yes = box.addButton("Sim", QMessageBox.ButtonRole.YesRole)
        yes_all = box.addButton("Sim para todos", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("Não", QMessageBox.ButtonRole.NoRole)
        no_all = box.addButton("Não para todos", QMessageBox.ButtonRole.NoRole)
        cancel = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)
        box.exec()

        clicked = box.clickedButton()
        if clicked is cancel:
            return None
        if clicked is yes:
            conflicting[job.destination] = True
        elif clicked is yes_all:
            conflicting[job.destination] = True
            apply_to_all = True
        elif clicked is no_all:
            apply_to_all = False

    return [
        replace(job, overwrite=conflicting.get(job.destination, False)) for job in jobs
    ]


class ReportDialog(QDialog):
    """Relatório detalhado com arquivo, status, mensagem e data/hora."""

    _HEADERS = ("Arquivo", "Status", "Mensagem", "Data/hora")

    def __init__(self, results: Sequence[ConversionResult], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Relatório da conversão")
        self.resize(940, 460)
        self._results = list(results)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self._summary_text()))

        self._table = QTableWidget(len(self._results), len(self._HEADERS), self)
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._fill_table()

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(0, 280)
        layout.addWidget(self._table, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self._save_button = QPushButton("Salvar como CSV…", self)
        self._save_button.clicked.connect(self._save_csv)
        buttons.addButton(self._save_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)

        footer = QHBoxLayout()
        footer.addWidget(buttons)
        layout.addLayout(footer)

    # ------------------------------------------------------------------
    def _summary_text(self) -> str:
        counts: dict[FileStatus, int] = {}
        for result in self._results:
            counts[result.status] = counts.get(result.status, 0) + 1
        parts = [f"{status.label}: {count}" for status, count in counts.items()]
        return f"{len(self._results)} arquivo(s) processado(s).   " + "   ".join(parts)

    def _fill_table(self) -> None:
        for row, result in enumerate(self._results):
            values = (
                str(result.source),
                result.status.label,
                result.message,
                result.finished_at.strftime("%d/%m/%Y %H:%M:%S"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(result.source))
                self._table.setItem(row, column, item)

    def _save_csv(self) -> None:
        path_text, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar relatório",
            "relatorio_conversao.csv",
            "Arquivo CSV (*.csv)",
        )
        if not path_text:
            return
        path = Path(path_text)
        try:
            # utf-8-sig + ';' para o Excel em português abrir corretamente.
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(self._HEADERS)
                for result in self._results:
                    writer.writerow(
                        (
                            str(result.source),
                            result.status.label,
                            result.message,
                            result.finished_at.strftime("%d/%m/%Y %H:%M:%S"),
                        )
                    )
        except OSError as exc:
            _log.warning("Falha ao salvar o relatório em %s: %s", path, exc)
            QMessageBox.warning(
                self, "Erro", f"Não foi possível salvar o relatório:\n{exc}"
            )
            return
        QMessageBox.information(self, "Relatório salvo", f"Relatório salvo em:\n{path}")
