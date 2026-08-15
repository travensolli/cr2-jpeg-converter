"""Conversão de um arquivo CR2 para JPEG.

Esta classe é deliberadamente sem estado mutável: uma única instância pode ser
usada por várias threads ao mesmo tempo. O LibRaw distribuído com o rawpy é a
build reentrante (``raw_r.dll``) e cada conversão trabalha sobre seu próprio
handle, então não há estado compartilhado a proteger.

Estratégia de gravação: o JPEG é escrito em um arquivo temporário na pasta de
destino e só então movido para o nome final com ``os.replace`` (operação
atômica). Assim, uma falha ou um cancelamento no meio do caminho nunca deixa um
JPEG truncado com o nome definitivo.
"""

from __future__ import annotations

import errno
import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from PIL import Image

from cr2_converter.core import rawio
from cr2_converter.core.metadata import ExifCopyError, copy_exif_to_jpeg
from cr2_converter.core.settings import ConversionSettings, postprocess_kwargs
from cr2_converter.core.types import ConversionJob, ConversionResult, FileStatus

__all__ = ["Cr2Converter", "RawOpener"]

_log = logging.getLogger(__name__)

RawOpener = Callable[[Path], AbstractContextManager[Any]]
"""Assinatura do abridor de RAW; injetável para permitir testes sem LibRaw."""

#: Mensagens amigáveis para as exceções do rawpy. A comparação é feita pelo
#: nome da classe para não obrigar o núcleo a importar o rawpy.
_RAW_ERROR_HINTS = {
    "LibRawFileUnsupportedError": "arquivo não reconhecido pelo LibRaw (CR2 inválido?)",
    "LibRawIOError": "falha de leitura do arquivo",
    "LibRawDataError": "dados corrompidos no arquivo RAW",
    "LibRawUnsufficientMemoryError": "memória insuficiente para revelar a imagem",
    "LibRawUnsupportedThumbnailError": "miniatura em formato não suportado",
    "LibRawNoThumbnailError": "o arquivo não contém miniatura",
    "LibRawTooBigError": "arquivo grande demais para o LibRaw",
    "LibRawOutOfOrderCallError": "erro interno do LibRaw",
    "LibRawUnspecifiedError": "erro não especificado do LibRaw",
    "LibRawNotImplementedError": "recurso não suportado pelo LibRaw para este arquivo",
    "LibRawInputClosedError": "o arquivo foi fechado antes do fim do processamento",
}

#: Acima desta qualidade a subamostragem de croma é desativada (4:4:4), evitando
#: perda de detalhe em cores saturadas — coerente com um conversor de RAW.
_SUBSAMPLING_THRESHOLD = 90


def describe_exception(exc: BaseException) -> str:
    """Traduz uma exceção em uma mensagem curta e compreensível."""
    hint = _RAW_ERROR_HINTS.get(type(exc).__name__)
    if hint:
        return hint
    if isinstance(exc, FileNotFoundError):
        return "arquivo não encontrado"
    if isinstance(exc, PermissionError):
        return "acesso negado (o arquivo pode estar aberto em outro programa)"
    if isinstance(exc, MemoryError):
        return "memória insuficiente"
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return "espaço insuficiente no disco de destino"
        if exc.errno == errno.EACCES:
            return "acesso negado ao gravar o arquivo"
        return f"erro de sistema de arquivos: {exc.strerror or exc}"
    return f"{type(exc).__name__}: {exc}"


class Cr2Converter:
    """Converte arquivos CR2 em JPEG conforme :class:`ConversionSettings`."""

    def __init__(
        self,
        settings: ConversionSettings,
        *,
        raw_opener: RawOpener | None = None,
    ) -> None:
        self._settings = settings.normalized()
        self._raw_opener: RawOpener = raw_opener or rawio.open_raw
        self._postprocess_kwargs = postprocess_kwargs(self._settings)

    @property
    def settings(self) -> ConversionSettings:
        return self._settings

    # ------------------------------------------------------------------
    def convert(
        self,
        job: ConversionJob,
        cancel_event: threading.Event | None = None,
    ) -> ConversionResult:
        """Converte um arquivo e devolve o resultado.

        Não levanta exceções por falha de conversão: erros viram um
        :class:`ConversionResult` com status ``ERROR``, para que um arquivo
        problemático não interrompa o lote inteiro.
        """
        started = time.perf_counter()

        if _is_cancelled(cancel_event):
            return self._finish(job, FileStatus.CANCELLED, "Cancelado antes do início.", started)

        precondition = self._check_preconditions(job)
        if precondition is not None:
            status, message = precondition
            return self._finish(job, status, message, started)

        temp_path = job.destination.with_name(f"{job.destination.name}.{os.getpid()}.tmp")
        try:
            note = self._render_to_file(job, temp_path, cancel_event)
        except _Cancelled:
            _remove_quietly(temp_path)
            return self._finish(
                job, FileStatus.CANCELLED, "Cancelado durante a conversão.", started
            )
        except _DestinationAppeared:
            return self._finish(
                job, FileStatus.SKIPPED, "O JPEG passou a existir durante a conversão.", started
            )
        except BaseException as exc:
            _remove_quietly(temp_path)
            message = f"Falha na conversão: {describe_exception(exc)}."
            _log.exception("Erro ao converter %s", job.source)
            return self._finish(job, FileStatus.ERROR, message, started)

        elapsed = time.perf_counter() - started
        _log.info(
            "Convertido %s -> %s (%.2f s)%s",
            job.source,
            job.destination,
            elapsed,
            f" [{note}]" if note else "",
        )
        return self._finish(job, FileStatus.CONVERTED, note, started)

    # ------------------------------------------------------------------
    def _check_preconditions(self, job: ConversionJob) -> tuple[FileStatus, str] | None:
        """Valida origem e destino antes de gastar tempo revelando o RAW."""
        try:
            if not job.source.is_file():
                return FileStatus.ERROR, "Arquivo de origem não encontrado."
            if job.destination.exists() and not job.overwrite:
                return FileStatus.SKIPPED, "O JPEG já existe no destino."
            job.destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return FileStatus.ERROR, f"Falha ao preparar o destino: {describe_exception(exc)}."
        return None

    def _render_to_file(
        self,
        job: ConversionJob,
        temp_path: Path,
        cancel_event: threading.Event | None,
    ) -> str:
        """Revela o RAW, grava o JPEG temporário e o move para o destino.

        Devolve uma observação para o relatório (vazia em caso perfeito).
        """
        with self._raw_opener(job.source) as raw:
            rgb = raw.postprocess(**self._postprocess_kwargs)

        try:
            if _is_cancelled(cancel_event):
                raise _Cancelled
            # Image.fromarray não copia os pixels: o array precisa continuar
            # vivo até a gravação terminar.
            image = Image.fromarray(rgb)
            try:
                if self._settings.resize_enabled:
                    image.thumbnail(
                        (self._settings.max_width, self._settings.max_height),
                        Image.Resampling.LANCZOS,
                    )
                width, height = image.size
                self._save_jpeg(image, temp_path)
            finally:
                image.close()
        finally:
            del rgb  # libera ~72 MB por imagem de 24 MP imediatamente

        note = ""
        if self._settings.preserve_exif:
            try:
                copy_exif_to_jpeg(job.source, temp_path, width, height)
            except ExifCopyError as exc:
                note = f"Convertido sem EXIF ({exc})."
                _log.warning("EXIF não copiado para %s: %s", job.destination, exc)

        # Reduz a janela entre a checagem inicial e a gravação: se o arquivo
        # apareceu nesse meio tempo, ele não é sobrescrito silenciosamente.
        if not job.overwrite and job.destination.exists():
            _remove_quietly(temp_path)
            raise _DestinationAppeared

        os.replace(temp_path, job.destination)
        return note

    def _save_jpeg(self, image: Image.Image, path: Path) -> None:
        """Grava o JPEG.

        ``optimize=True`` é deliberadamente **não** usado. O Pillow dimensiona o
        buffer do codificador por heurística (``largura × altura`` bytes, o
        dobro a partir de qualidade 95) e, quando o arquivo resultante passa
        disso, a gravação falha com ``OSError: broken data stream``. Isso
        acontece de verdade com fotos granuladas (ISO alto) em qualidade 90–94
        combinada com croma 4:4:4 — foi reproduzido em 300×200, 800×600 e
        2000×1500. O ganho de tamanho seria de apenas ~6%, e o custo seria
        transformar fotos ruidosas em erros no meio do lote.
        """
        quality = self._settings.quality
        image.save(
            path,
            format="JPEG",
            quality=quality,
            subsampling=0 if quality >= _SUBSAMPLING_THRESHOLD else 2,
        )

    def _finish(
        self,
        job: ConversionJob,
        status: FileStatus,
        message: str,
        started: float,
    ) -> ConversionResult:
        return ConversionResult(
            job=job,
            status=status,
            message=message,
            duration_s=time.perf_counter() - started,
        )


# As duas exceções abaixo são sinais de fluxo interno, não falhas — daí não
# terminarem em "Error" (o que sugeriria um problema para quem lê o código).
class _Cancelled(Exception):  # noqa: N818
    """Sinaliza cancelamento no meio do processamento (uso interno)."""


class _DestinationAppeared(Exception):  # noqa: N818
    """O destino passou a existir durante a conversão (uso interno)."""


def _is_cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _remove_quietly(path: Path) -> None:
    """Remove um arquivo temporário ignorando falhas."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - depende do sistema de arquivos
        _log.warning("Não foi possível remover o temporário %s: %s", path, exc)
