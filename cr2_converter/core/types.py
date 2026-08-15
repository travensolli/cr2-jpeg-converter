"""Tipos de domínio compartilhados entre o núcleo e a interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

__all__ = [
    "BatchEvent",
    "BatchSummary",
    "ConflictPolicy",
    "ConversionJob",
    "ConversionResult",
    "FileFinished",
    "FileStarted",
    "FileStatus",
    "WhiteBalance",
]


class FileStatus(Enum):
    """Situação de um arquivo na lista de conversão."""

    PENDING = "Aguardando"
    RUNNING = "Convertendo"
    CONVERTED = "Convertido"
    SKIPPED = "Ignorado"
    ERROR = "Erro"
    CANCELLED = "Cancelado"

    @property
    def label(self) -> str:
        """Texto exibido ao usuário."""
        return self.value


class WhiteBalance(Enum):
    """Modos de balanço de branco suportados pelo LibRaw/rawpy."""

    CAMERA = "camera"
    AUTO = "auto"
    NEUTRAL = "neutral"

    @property
    def label(self) -> str:
        return _WB_LABELS[self]


_WB_LABELS = {
    WhiteBalance.CAMERA: "Da câmera (padrão)",
    WhiteBalance.AUTO: "Automático",
    WhiteBalance.NEUTRAL: "Neutro (sem ajuste)",
}


class ConflictPolicy(Enum):
    """O que fazer quando o JPEG de destino já existe."""

    OVERWRITE = "overwrite"
    SKIP = "skip"
    ASK = "ask"

    @property
    def label(self) -> str:
        return _CONFLICT_LABELS[self]


_CONFLICT_LABELS = {
    ConflictPolicy.OVERWRITE: "Sobrescrever",
    ConflictPolicy.SKIP: "Ignorar",
    ConflictPolicy.ASK: "Perguntar",
}


@dataclass(frozen=True, slots=True)
class ConversionJob:
    """Uma unidade de trabalho: um CR2 de origem e seu JPEG de destino.

    ``row`` guarda a linha correspondente na lista da interface, permitindo
    atualizar o status sem que o núcleo conheça o modelo da UI.
    """

    source: Path
    destination: Path
    overwrite: bool = False
    row: int = -1


@dataclass(slots=True)
class ConversionResult:
    """Resultado da conversão de um único arquivo."""

    job: ConversionJob
    status: FileStatus
    message: str = ""
    finished_at: datetime = field(default_factory=datetime.now)
    duration_s: float = 0.0

    @property
    def source(self) -> Path:
        return self.job.source

    @property
    def destination(self) -> Path:
        return self.job.destination

    @property
    def row(self) -> int:
        return self.job.row

    @property
    def ok(self) -> bool:
        return self.status is FileStatus.CONVERTED


@dataclass(slots=True)
class FileStarted:
    """Evento emitido quando um arquivo começa a ser processado."""

    job: ConversionJob


@dataclass(slots=True)
class FileFinished:
    """Evento emitido quando um arquivo termina (com sucesso, erro ou skip)."""

    result: ConversionResult


BatchEvent = FileStarted | FileFinished


@dataclass(slots=True)
class BatchSummary:
    """Contagens finais de um lote."""

    total: int = 0
    converted: int = 0
    skipped: int = 0
    errors: int = 0
    cancelled: int = 0
    elapsed_s: float = 0.0

    @property
    def processed(self) -> int:
        """Arquivos que chegaram a uma conclusão (exclui os cancelados)."""
        return self.converted + self.skipped + self.errors

    def add(self, status: FileStatus) -> None:
        """Contabiliza um resultado."""
        if status is FileStatus.CONVERTED:
            self.converted += 1
        elif status is FileStatus.SKIPPED:
            self.skipped += 1
        elif status is FileStatus.ERROR:
            self.errors += 1
        elif status is FileStatus.CANCELLED:
            self.cancelled += 1
