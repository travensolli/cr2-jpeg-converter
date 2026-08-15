"""Execução do lote com paralelismo controlado.

Desenho de concorrência
-----------------------
``run()`` é um **gerador**: as threads do pool apenas produzem eventos em uma
fila e quem consome o gerador (a thread de trabalho do Qt) é o único a emitir
sinais. Isso elimina a principal fonte de condição de corrida em aplicações Qt
— atualizar a interface a partir de várias threads — sem precisar de locks, e
ainda deixa o lote testável sem nenhuma dependência de GUI.

Sobre o número de workers
-------------------------
O LibRaw empacotado com o rawpy é compilado com OpenMP e já usa vários núcleos
dentro de um único ``postprocess``. O ganho de threads Python adicionais vem
principalmente de sobrepor leitura de disco e codificação JPEG de um arquivo
com a revelação de outro. Por isso o padrão é baixo (ver
:func:`cr2_converter.core.settings.default_worker_count`) — subir demais
multiplica o uso de memória (cada imagem de 24 MP ocupa ~72 MB) sem acelerar.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor

from cr2_converter.core.converter import Cr2Converter, describe_exception
from cr2_converter.core.settings import ConversionSettings
from cr2_converter.core.types import (
    BatchEvent,
    ConversionJob,
    ConversionResult,
    FileFinished,
    FileStarted,
    FileStatus,
)

__all__ = ["BatchRunner"]

_log = logging.getLogger(__name__)


class BatchRunner:
    """Processa uma lista de :class:`ConversionJob` emitindo eventos."""

    def __init__(
        self,
        jobs: Sequence[ConversionJob],
        settings: ConversionSettings,
        *,
        converter: Cr2Converter | None = None,
    ) -> None:
        self._jobs = list(jobs)
        self._settings = settings.normalized()
        self._converter = converter or Cr2Converter(self._settings)
        self._cancel = threading.Event()

    # ------------------------------------------------------------------
    @property
    def total(self) -> int:
        return len(self._jobs)

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        """Pede o cancelamento; seguro para chamar de qualquer thread.

        Arquivos ainda não iniciados são descartados imediatamente; o que já
        está sendo revelado termina de gravar (ou é abortado antes da gravação),
        nunca deixando um JPEG pela metade.
        """
        if not self._cancel.is_set():
            _log.info("Cancelamento solicitado pelo usuário.")
        self._cancel.set()

    # ------------------------------------------------------------------
    def run(self) -> Iterator[BatchEvent]:
        """Executa o lote, produzindo :class:`FileStarted`/:class:`FileFinished`.

        Garante exatamente um ``FileFinished`` por trabalho, mesmo diante de
        falhas inesperadas — é isso que impede o consumidor de travar esperando
        um evento que nunca chegaria.
        """
        total = len(self._jobs)
        if total == 0:
            return

        events: queue.Queue[BatchEvent] = queue.Queue()
        workers = max(1, min(self._settings.workers, total))
        _log.info("Iniciando lote com %d arquivo(s) e %d thread(s).", total, workers)

        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cr2-worker")
        finished = 0
        try:
            for job in self._jobs:
                executor.submit(self._process, job, events)
            while finished < total:
                event = events.get()
                if isinstance(event, FileFinished):
                    finished += 1
                yield event
        finally:
            if finished < total:
                # O consumidor desistiu (fechou a janela, erro na UI…):
                # não deixe threads revelando imagens sem ninguém escutando.
                self._cancel.set()
            executor.shutdown(wait=True, cancel_futures=True)
            _log.info("Lote encerrado (%d de %d arquivos processados).", finished, total)

    # ------------------------------------------------------------------
    def _process(self, job: ConversionJob, events: queue.Queue[BatchEvent]) -> None:
        """Executa um trabalho em uma thread do pool.

        Nunca propaga exceções: o contrato com :meth:`run` é sempre publicar um
        ``FileFinished``.
        """
        try:
            if self._cancel.is_set():
                result = ConversionResult(
                    job=job,
                    status=FileStatus.CANCELLED,
                    message="Cancelado pelo usuário.",
                )
            else:
                events.put(FileStarted(job))
                result = self._converter.convert(job, self._cancel)
        except BaseException as exc:
            _log.exception("Falha inesperada ao processar %s", job.source)
            result = ConversionResult(
                job=job,
                status=FileStatus.ERROR,
                message=f"Falha inesperada: {describe_exception(exc)}.",
            )
        events.put(FileFinished(result))
