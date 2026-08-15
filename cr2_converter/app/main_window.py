"""Janela principal da aplicação."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QThread, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from cr2_converter import APP_NAME, __version__
from cr2_converter.app.dialogs import ReportDialog, resolve_conflicts
from cr2_converter.app.models import FileListModel
from cr2_converter.app.preview import PreviewPanel
from cr2_converter.app.settings_panel import SettingsPanel
from cr2_converter.app.style import PRIMARY_BUTTON
from cr2_converter.app.workers import ConversionWorker
from cr2_converter.core.planner import existing_destinations, plan_jobs
from cr2_converter.core.settings import AppSettings, ConversionSettings, SettingsStore
from cr2_converter.core.types import BatchSummary, ConversionResult, FileStatus
from cr2_converter.utils.filesystem import collect_sources, prepare_output_dir
from cr2_converter.utils.paths import default_log_dir

__all__ = ["MainWindow"]

_log = logging.getLogger(__name__)

_FILE_FILTER = "Arquivos Canon RAW (*.CR2 *.cr2);;Todos os arquivos (*)"
_THREAD_STOP_TIMEOUT_MS = 15_000


class MainWindow(QMainWindow):
    """Janela única da aplicação: origem, destino, configurações e progresso."""

    def __init__(self, store: SettingsStore | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setMinimumSize(1040, 660)
        self.setAcceptDrops(True)

        self._store = store or SettingsStore()
        self._model = FileListModel(self)
        self._results: list[ConversionResult] = []
        self._thread: QThread | None = None
        self._worker: ConversionWorker | None = None
        self._last_source_dir = ""
        # Impede que os widgets, ao receberem os valores salvos, disparem uma
        # gravação por cima das configurações que ainda estão sendo carregadas.
        self._loading_settings = False

        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.setInterval(500)
        self._settings_timer.timeout.connect(self._flush_settings)

        self._build_ui()
        self._build_menu()
        self._load_settings()
        self._update_actions()

    # ==================================================================
    # Construção da interface
    # ==================================================================
    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        root.addWidget(self._build_progress_group())
        root.addLayout(self._build_action_bar())

        self.setCentralWidget(central)
        self.statusBar().showMessage("Pronto.")

    def _build_left_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_source_group(), stretch=1)
        layout.addWidget(self._build_output_group())
        return panel

    def _build_source_group(self) -> QGroupBox:
        group = QGroupBox("Arquivos de origem", self)
        layout = QVBoxLayout(group)

        buttons = QHBoxLayout()
        self._add_files_button = QPushButton("Adicionar arquivos")
        self._add_files_button.clicked.connect(self._add_files)
        self._add_folder_button = QPushButton("Selecionar pasta")
        self._add_folder_button.clicked.connect(self._add_folder)
        self._remove_button = QPushButton("Remover selecionados")
        self._remove_button.clicked.connect(self._remove_selected)
        self._clear_button = QPushButton("Limpar lista")
        self._clear_button.clicked.connect(self._clear_list)
        for button in (
            self._add_files_button,
            self._add_folder_button,
            self._remove_button,
            self._clear_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._table = QTableView(group)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(FileListModel.COLUMN_NAME, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(FileListModel.COLUMN_PATH, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            FileListModel.COLUMN_SIZE, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(
            FileListModel.COLUMN_STATUS, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setColumnWidth(FileListModel.COLUMN_NAME, 190)

        selection = self._table.selectionModel()
        if selection is not None:
            selection.currentChanged.connect(self._on_current_row_changed)
        layout.addWidget(self._table, stretch=1)

        hint = QLabel("Dica: arraste arquivos ou pastas para esta janela.")
        hint.setObjectName("hintLabel")
        layout.addWidget(hint)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Destino", self)
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Pasta de saída:"))
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("Escolha a pasta onde os JPEG serão gravados")
        self._output_edit.setClearButtonEnabled(True)
        self._output_edit.textChanged.connect(lambda _text: self._update_actions())
        row.addWidget(self._output_edit, stretch=1)
        self._output_button = QPushButton("Selecionar")
        self._output_button.clicked.connect(self._choose_output_dir)
        row.addWidget(self._output_button)
        layout.addLayout(row)

        self._keep_structure_check = QCheckBox("Manter estrutura de subpastas")
        self._keep_structure_check.setToolTip(
            "Reproduz no destino a hierarquia de pastas das origens adicionadas\n"
            "por “Selecionar pasta” ou arrastadas para a janela."
        )
        self._keep_structure_check.toggled.connect(lambda _checked: self._save_settings())
        layout.addWidget(self._keep_structure_check)
        return group

    def _build_right_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._preview = PreviewPanel(panel)
        # A pré-visualização acompanha o redimensionamento, mas as configurações
        # recebem a maior parte do espaço: são elas que o usuário ajusta.
        self._preview.setMaximumHeight(420)
        layout.addWidget(self._preview, stretch=1)

        self._settings_panel = SettingsPanel(panel)
        self._settings_panel.changed.connect(self._save_settings)

        scroll = QScrollArea(panel)
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._settings_panel)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(330)
        layout.addWidget(scroll, stretch=3)
        return panel

    def _build_progress_group(self) -> QGroupBox:
        group = QGroupBox("Progresso", self)
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self._progress = QProgressBar(group)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%p%")
        layout.addWidget(self._progress)

        info = QHBoxLayout()
        self._files_label = QLabel("0 / 0 arquivos")
        self._current_label = QLabel("Arquivo atual: —")
        self._current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._state_label = QLabel("Status: pronto")
        info.addWidget(self._files_label)
        info.addSpacing(16)
        info.addWidget(self._current_label, stretch=1)
        info.addWidget(self._state_label)
        layout.addLayout(info)
        return group

    def _build_action_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self._report_button = QPushButton("Ver relatório")
        self._report_button.clicked.connect(self._show_report)
        self._report_button.setEnabled(False)
        bar.addWidget(self._report_button)
        bar.addStretch(1)

        self._cancel_button = QPushButton("Cancelar")
        self._cancel_button.clicked.connect(self._cancel_conversion)
        self._cancel_button.setEnabled(False)
        bar.addWidget(self._cancel_button)

        self._convert_button = QPushButton("Converter")
        self._convert_button.setObjectName(PRIMARY_BUTTON)
        self._convert_button.setDefault(True)
        self._convert_button.clicked.connect(self._start_conversion)
        bar.addWidget(self._convert_button)
        return bar

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Arquivo")
        add_files = QAction("Adicionar arquivos…", self)
        add_files.setShortcut(QKeySequence.StandardKey.Open)
        add_files.triggered.connect(self._add_files)
        file_menu.addAction(add_files)

        add_folder = QAction("Selecionar pasta…", self)
        add_folder.triggered.connect(self._add_folder)
        file_menu.addAction(add_folder)
        file_menu.addSeparator()

        remove_action = QAction("Remover selecionados", self)
        remove_action.setShortcut(QKeySequence.StandardKey.Delete)
        remove_action.triggered.connect(self._remove_selected)
        file_menu.addAction(remove_action)
        self.addAction(remove_action)  # atalho ativo mesmo com o menu fechado

        clear_action = QAction("Limpar lista", self)
        clear_action.triggered.connect(self._clear_list)
        file_menu.addAction(clear_action)
        file_menu.addSeparator()

        quit_action = QAction("Sair", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("A&juda")
        logs_action = QAction("Abrir pasta de logs", self)
        logs_action.triggered.connect(self._open_logs)
        help_menu.addAction(logs_action)
        about_action = QAction("Sobre", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # ==================================================================
    # Configurações
    # ==================================================================
    def _load_settings(self) -> None:
        self._loading_settings = True
        try:
            settings = self._store.load()
            self._settings_panel.apply(settings.conversion)
            self._keep_structure_check.setChecked(settings.conversion.keep_structure)
            self._last_source_dir = settings.last_source_dir

            output = settings.output_dir or QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.PicturesLocation
            )
            self._output_edit.setText(output)
            if settings.window_geometry:
                try:
                    self.restoreGeometry(bytes.fromhex(settings.window_geometry))
                except ValueError:
                    _log.debug("Geometria da janela inválida nas configurações.")
        finally:
            self._loading_settings = False

    def _current_settings(self) -> ConversionSettings:
        """Configurações do painel + o "manter estrutura" da seção Destino."""
        return replace(
            self._settings_panel.settings(),
            keep_structure=self._keep_structure_check.isChecked(),
        )

    @Slot()
    def _save_settings(self) -> None:
        """Agenda a gravação das configurações.

        Arrastar o controle de qualidade emite uma alteração por pixel; gravar
        o arquivo a cada uma delas seria dezenas de escritas em disco por
        segundo. O temporizador junta tudo em uma única gravação.
        """
        if self._loading_settings:
            return
        self._settings_timer.start()

    def _flush_settings(self) -> None:
        """Grava as configurações imediatamente."""
        if self._loading_settings:
            return
        self._settings_timer.stop()
        self._store.save(
            AppSettings(
                conversion=self._current_settings(),
                output_dir=self._output_edit.text().strip(),
                last_source_dir=self._last_source_dir,
                window_geometry=bytes(self.saveGeometry()).hex(),
            )
        )

    # ==================================================================
    # Origem
    # ==================================================================
    @Slot()
    def _add_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Selecionar arquivos CR2", self._last_source_dir, _FILE_FILTER
        )
        if paths:
            self._last_source_dir = str(Path(paths[0]).parent)
            self._add_paths([Path(path) for path in paths])

    @Slot()
    def _add_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Selecionar pasta com arquivos CR2", self._last_source_dir
        )
        if directory:
            self._last_source_dir = directory
            self._add_paths([Path(directory)])

    def _add_paths(self, paths: list[Path]) -> None:
        """Expande arquivos/pastas e adiciona à lista, evitando duplicatas."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            sources = collect_sources(paths)
            added, duplicates = self._model.add_sources(sources)
        finally:
            QApplication.restoreOverrideCursor()

        if added == 0 and duplicates == 0:
            self.statusBar().showMessage("Nenhum arquivo .CR2 encontrado.", 6000)
            QMessageBox.information(
                self,
                "Nenhum arquivo encontrado",
                "Não foram encontrados arquivos .CR2 nos caminhos selecionados.",
            )
        else:
            message = f"{added} arquivo(s) adicionado(s)."
            if duplicates:
                message += f" {duplicates} já estava(m) na lista."
            self.statusBar().showMessage(message, 6000)

        self._update_actions()
        self._save_settings()

    @Slot()
    def _remove_selected(self) -> None:
        if self._is_running():
            return
        selection = self._table.selectionModel()
        if selection is None:
            return
        rows = sorted({index.row() for index in selection.selectedRows()})
        if not rows:
            return
        self._model.remove_rows(rows)
        self._preview.clear()
        self._update_actions()

    @Slot()
    def _clear_list(self) -> None:
        if self._is_running():
            return
        self._model.clear()
        self._preview.clear()
        self._reset_progress()
        self._update_actions()

    @Slot()
    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Selecionar pasta de destino", self._output_edit.text()
        )
        if directory:
            self._output_edit.setText(directory)
            self._save_settings()

    def _on_current_row_changed(self, current, _previous) -> None:
        entry = self._model.entry_at(current.row()) if current.isValid() else None
        if entry is None:
            self._preview.clear()
        else:
            self._preview.load(entry.path, entry.size)

    # ==================================================================
    # Arrastar e soltar
    # ==================================================================
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if not self._is_running() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if not self._is_running() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if self._is_running():
            event.ignore()
            return
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile()
        ]
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._add_paths(paths)

    # ==================================================================
    # Conversão
    # ==================================================================
    @Slot()
    def _start_conversion(self) -> None:
        if self._is_running() or self._model.is_empty():
            return

        output_dir = self._validated_output_dir()
        if output_dir is None:
            return

        settings = self._current_settings()
        entries = self._model.entries
        jobs = plan_jobs(
            [entry.as_source() for entry in entries],
            output_dir,
            keep_structure=settings.keep_structure,
            rows=list(range(len(entries))),
        )
        conflicts = existing_destinations(jobs)
        resolved = resolve_conflicts(self, jobs, settings.conflict_policy, conflicts)
        if resolved is None:
            self.statusBar().showMessage("Conversão cancelada.", 5000)
            return

        self._results.clear()
        self._model.reset_statuses()
        self._progress.setRange(0, len(resolved))
        self._progress.setValue(0)
        self._files_label.setText(f"0 / {len(resolved)} arquivos")
        self._current_label.setText("Arquivo atual: —")
        self._state_label.setText("Status: convertendo…")

        self._worker = ConversionWorker(resolved, settings)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_finished.connect(self._on_file_finished)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_batch_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)

        self._set_running(True)
        _log.info(
            "Conversão iniciada: %d arquivo(s), destino=%s, qualidade=%d, threads=%d",
            len(resolved),
            output_dir,
            settings.quality,
            settings.workers,
        )
        self._thread.start()

    def _validated_output_dir(self) -> Path | None:
        """Valida a pasta de destino, avisando o usuário se houver problema."""
        directory, error = prepare_output_dir(self._output_edit.text())
        if directory is None:
            QMessageBox.warning(self, "Pasta de destino", error)
        return directory

    @Slot()
    def _cancel_conversion(self) -> None:
        if self._worker is None:
            return
        self._cancel_button.setEnabled(False)
        self._state_label.setText("Status: cancelando…")
        self.statusBar().showMessage("Cancelando… os arquivos em andamento serão concluídos.")
        try:
            self._worker.cancel()
        except RuntimeError:  # pragma: no cover - worker já removido
            _log.debug("Cancelamento solicitado após o término do lote.")

    @Slot(int, str)
    def _on_file_started(self, row: int, name: str) -> None:
        self._model.set_status(row, FileStatus.RUNNING)
        self._current_label.setText(f"Arquivo atual: {name}")

    @Slot(int, object)
    def _on_file_finished(self, row: int, result: object) -> None:
        if not isinstance(result, ConversionResult):  # pragma: no cover - proteção
            return
        self._results.append(result)
        self._model.set_status(row, result.status, result.message)

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self._progress.setValue(done)
        self._files_label.setText(f"{done} / {total} arquivos")

    @Slot(object)
    def _on_batch_finished(self, summary: object) -> None:
        if not isinstance(summary, BatchSummary):  # pragma: no cover - proteção
            return
        self._set_running(False)
        self._report_button.setEnabled(bool(self._results))
        self._current_label.setText("Arquivo atual: —")
        self._state_label.setText(
            "Status: cancelado" if summary.cancelled else "Status: concluído"
        )
        _log.info(
            "Lote finalizado em %.1fs: %d convertido(s), %d ignorado(s), "
            "%d erro(s), %d cancelado(s)",
            summary.elapsed_s,
            summary.converted,
            summary.skipped,
            summary.errors,
            summary.cancelled,
        )
        self._show_summary(summary)

    @Slot()
    def _on_thread_finished(self) -> None:
        thread, self._thread = self._thread, None
        self._worker = None
        if thread is not None:
            thread.deleteLater()

    def _show_summary(self, summary: BatchSummary) -> None:
        title = "Conversão cancelada" if summary.cancelled else "Conversão concluída"
        lines = [
            f"Arquivos processados: {summary.processed}",
            f"Convertidos: {summary.converted}",
            f"Ignorados: {summary.skipped}",
            f"Erros: {summary.errors}",
        ]
        if summary.cancelled:
            lines.append(f"Cancelados: {summary.cancelled}")
        lines.append(f"Tempo total: {summary.elapsed_s:.1f} s")

        self.statusBar().showMessage(
            f"{summary.converted} convertido(s), {summary.skipped} ignorado(s), "
            f"{summary.errors} erro(s)."
        )

        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning if summary.errors else QMessageBox.Icon.Information)
        box.setText(f"{title}!")
        box.setInformativeText("\n".join(lines))
        report_button = box.addButton("Ver relatório", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Fechar", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is report_button:
            self._show_report()

    @Slot()
    def _show_report(self) -> None:
        if not self._results:
            QMessageBox.information(
                self, "Relatório", "Nenhuma conversão foi executada nesta sessão."
            )
            return
        ReportDialog(self._results, self).exec()

    # ==================================================================
    # Estado da interface
    # ==================================================================
    def _is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _set_running(self, running: bool) -> None:
        for widget in (
            self._add_files_button,
            self._add_folder_button,
            self._remove_button,
            self._clear_button,
            self._output_edit,
            self._output_button,
            self._keep_structure_check,
            self._settings_panel,
        ):
            widget.setEnabled(not running)
        self._convert_button.setEnabled(not running and not self._model.is_empty())
        self._cancel_button.setEnabled(running)
        self.menuBar().setEnabled(not running)

    def _update_actions(self) -> None:
        has_files = not self._model.is_empty()
        self._convert_button.setEnabled(has_files and not self._is_running())
        self._remove_button.setEnabled(has_files)
        self._clear_button.setEnabled(has_files)

    def _reset_progress(self) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._files_label.setText("0 / 0 arquivos")
        self._current_label.setText("Arquivo atual: —")
        self._state_label.setText("Status: pronto")

    # ==================================================================
    # Menu Ajuda
    # ==================================================================
    @Slot()
    def _open_logs(self) -> None:
        directory = default_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    @Slot()
    def _show_about(self) -> None:
        try:
            import rawpy

            libraw = ".".join(str(part) for part in rawpy.libraw_version)
            rawpy_version = rawpy.__version__
        except Exception:
            libraw = rawpy_version = "indisponível"

        QMessageBox.about(
            self,
            f"Sobre o {APP_NAME}",
            f"<b>{APP_NAME}</b> {__version__}<br><br>"
            "Conversor local de arquivos Canon RAW (.CR2) para JPEG.<br>"
            "Funciona totalmente offline.<br><br>"
            f"rawpy {rawpy_version} · LibRaw {libraw}",
        )

    # ==================================================================
    # Encerramento
    # ==================================================================
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._is_running():
            answer = QMessageBox.question(
                self,
                "Conversão em andamento",
                "Uma conversão está em andamento.\n"
                "Deseja cancelá-la e sair? Os arquivos já convertidos são mantidos.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._stop_worker()

        self._preview.shutdown()
        self._flush_settings()  # grava agora, sem esperar o temporizador
        event.accept()

    def _stop_worker(self) -> None:
        """Cancela o lote e espera a thread terminar de forma segura."""
        if self._worker is not None:
            # RuntimeError: o objeto C++ já foi removido (lote recém-terminado).
            with suppress(RuntimeError):
                self._worker.cancel()
        thread = self._thread
        if thread is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            thread.quit()
            if not thread.wait(_THREAD_STOP_TIMEOUT_MS):
                _log.warning("A thread de conversão não terminou dentro do tempo esperado.")
        finally:
            QApplication.restoreOverrideCursor()
