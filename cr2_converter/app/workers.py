"""Pontes entre o núcleo (Python puro) e o Qt.

Duas cargas de trabalho rodam fora da thread da interface:

``ConversionWorker``
    Vive em uma ``QThread`` dedicada e consome o gerador do
    :class:`~cr2_converter.core.batch.BatchRunner`. Como só ele emite sinais,
    todas as atualizações da interface partem de uma única thread — o Qt as
    entrega na thread principal por conexão enfileirada.

``PreviewTask``
    ``QRunnable`` curto para gerar a pré-visualização sem travar a interface.
    O objeto de sinais é fornecido pelo chamador de propósito: um ``QRunnable``
    com ``autoDelete`` é destruído logo após ``run()``, e sinais pertencentes a
    ele poderiam ser emitidos sobre um objeto C++ já removido.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from cr2_converter.core.batch import BatchRunner
from cr2_converter.core.converter import describe_exception
from cr2_converter.core.rawio import PREVIEW_MAX_EDGE, render_preview
from cr2_converter.core.settings import ConversionSettings
from cr2_converter.core.types import BatchSummary, ConversionJob, FileStarted

__all__ = ["ConversionWorker", "PreviewSignals", "PreviewTask"]

_log = logging.getLogger(__name__)


class ConversionWorker(QObject):
    """Executa o lote em uma ``QThread`` e reporta o progresso por sinais."""

    file_started = Signal(int, str)
    """(linha, nome do arquivo)"""

    file_finished = Signal(int, object)
    """(linha, :class:`~cr2_converter.core.types.ConversionResult`)"""

    progress = Signal(int, int)
    """(concluídos, total)"""

    finished = Signal(object)
    """(:class:`~cr2_converter.core.types.BatchSummary`) — sempre emitido."""

    def __init__(
        self,
        jobs: list[ConversionJob],
        settings: ConversionSettings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._runner = BatchRunner(jobs, settings)

    def cancel(self) -> None:
        """Pode ser chamado da thread da interface com segurança."""
        self._runner.cancel()

    @Slot()
    def run(self) -> None:
        """Ponto de entrada disparado por ``QThread.started``."""
        summary = BatchSummary(total=self._runner.total)
        started = time.perf_counter()
        completed = 0
        try:
            for event in self._runner.run():
                if isinstance(event, FileStarted):
                    self.file_started.emit(event.job.row, event.job.source.name)
                    continue
                result = event.result
                summary.add(result.status)
                completed += 1
                self.file_finished.emit(result.row, result)
                self.progress.emit(completed, summary.total)
        except BaseException:
            _log.exception("Falha inesperada durante o lote")
        finally:
            summary.elapsed_s = time.perf_counter() - started
            self.finished.emit(summary)


class PreviewSignals(QObject):
    """Sinais de pré-visualização, de posse de quem agenda as tarefas."""

    ready = Signal(int, object, object)
    """(id da requisição, bytes JPEG, :class:`~cr2_converter.core.rawio.RawInfo`)"""

    failed = Signal(int, str)
    """(id da requisição, mensagem)"""


class PreviewTask(QRunnable):
    """Gera a pré-visualização de um arquivo em uma thread do pool."""

    def __init__(
        self,
        request_id: int,
        path: Path,
        signals: PreviewSignals,
        max_edge: int = PREVIEW_MAX_EDGE,
    ) -> None:
        super().__init__()
        self._request_id = request_id
        self._path = path
        self._signals = signals
        self._max_edge = max_edge

    @Slot()
    def run(self) -> None:
        try:
            data, info = render_preview(self._path, self._max_edge)
        except BaseException as exc:
            _log.debug("Falha ao gerar pré-visualização de %s: %s", self._path, exc)
            self._signals.failed.emit(self._request_id, describe_exception(exc))
        else:
            self._signals.ready.emit(self._request_id, data, info)
