"""Configurações de conversão e persistência em disco.

O objeto :class:`ConversionSettings` é um dataclass simples, sem dependência de
Qt nem de rawpy — a tradução para os parâmetros do LibRaw é feita por
:func:`postprocess_kwargs`, o que permite testar o mapeamento sem ter o rawpy
instalado.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from cr2_converter.core.types import ConflictPolicy, WhiteBalance
from cr2_converter.utils.paths import ensure_dir, settings_file

__all__ = [
    "MAX_DIMENSION",
    "MAX_EXPOSURE_EV",
    "MAX_QUALITY",
    "MAX_WORKERS",
    "MIN_QUALITY",
    "AppSettings",
    "ConversionSettings",
    "SettingsStore",
    "default_worker_count",
    "postprocess_kwargs",
]

_log = logging.getLogger(__name__)

MIN_QUALITY = 1
MAX_QUALITY = 100
DEFAULT_QUALITY = 95

MIN_DIMENSION = 16
MAX_DIMENSION = 65_500  # limite do formato JPEG (65.535) com folga

MAX_EXPOSURE_EV = 2.0
MIN_EXPOSURE_EV = -2.0

MAX_WORKERS = 8

# Faixa aceita pelo LibRaw para exp_shift (escala linear, não em EV).
_EXP_SHIFT_MIN = 0.25
_EXP_SHIFT_MAX = 8.0


def default_worker_count() -> int:
    """Número padrão de conversões simultâneas.

    Mantido baixo de propósito: o LibRaw distribuído com o rawpy é compilado
    com OpenMP (``vcomp140.dll``) e já usa vários núcleos dentro de um único
    ``postprocess``. Threads Python demais apenas disputam CPU e multiplicam o
    consumo de memória (cada imagem de 24 MP ocupa ~72 MB só no buffer RGB).
    """
    cpus = os.cpu_count() or 2
    return max(1, min(4, cpus // 2))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class ConversionSettings:
    """Todas as opções que o usuário controla na aba de configurações."""

    quality: int = DEFAULT_QUALITY
    resize_enabled: bool = False
    max_width: int = 1920
    max_height: int = 1080
    white_balance: WhiteBalance = WhiteBalance.CAMERA
    exposure_ev: float = 0.0
    auto_brightness: bool = True
    preserve_exif: bool = True
    keep_structure: bool = False
    conflict_policy: ConflictPolicy = ConflictPolicy.SKIP
    workers: int = field(default_factory=default_worker_count)

    def normalized(self) -> ConversionSettings:
        """Devolve uma cópia com todos os valores dentro das faixas válidas."""
        return replace(
            self,
            quality=int(_clamp(self.quality, MIN_QUALITY, MAX_QUALITY)),
            max_width=int(_clamp(self.max_width, MIN_DIMENSION, MAX_DIMENSION)),
            max_height=int(_clamp(self.max_height, MIN_DIMENSION, MAX_DIMENSION)),
            exposure_ev=round(_clamp(self.exposure_ev, MIN_EXPOSURE_EV, MAX_EXPOSURE_EV), 2),
            workers=int(_clamp(self.workers, 1, MAX_WORKERS)),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["white_balance"] = self.white_balance.value
        data["conflict_policy"] = self.conflict_policy.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversionSettings:
        """Reconstrói a partir de um dicionário, ignorando campos inválidos."""
        settings = cls()
        for key, value in (data or {}).items():
            if not hasattr(settings, key):
                continue
            try:
                if key == "white_balance":
                    setattr(settings, key, WhiteBalance(value))
                elif key == "conflict_policy":
                    setattr(settings, key, ConflictPolicy(value))
                elif key in {"quality", "max_width", "max_height", "workers"}:
                    setattr(settings, key, int(value))
                elif key == "exposure_ev":
                    setattr(settings, key, float(value))
                else:
                    setattr(settings, key, bool(value))
            except (TypeError, ValueError) as exc:
                _log.warning("Configuração inválida ignorada (%s=%r): %s", key, value, exc)
        return settings.normalized()


def postprocess_kwargs(settings: ConversionSettings) -> dict[str, Any]:
    """Traduz as configurações para argumentos de ``rawpy.RawPy.postprocess``.

    Notas técnicas:

    * ``output_bps=8`` porque o JPEG é sempre 8 bits por canal — pedir 16 bits
      só gastaria memória e tempo;
    * ``exp_shift`` do LibRaw é **linear**, não em EV: ``2 ** EV``;
    * quando há correção de exposição manual, o brilho automático é desligado.
      Os dois atuam sobre a mesma escala e o auto-bright normaliza o histograma,
      anulando parcialmente o ajuste pedido pelo usuário;
    * o espaço de cor fica no padrão do rawpy (sRGB), adequado para JPEG.
    """
    kwargs: dict[str, Any] = {
        "output_bps": 8,
        "use_camera_wb": settings.white_balance is WhiteBalance.CAMERA,
        "use_auto_wb": settings.white_balance is WhiteBalance.AUTO,
        "no_auto_bright": not settings.auto_brightness,
    }
    if settings.exposure_ev:
        kwargs["exp_shift"] = _clamp(2.0**settings.exposure_ev, _EXP_SHIFT_MIN, _EXP_SHIFT_MAX)
        kwargs["no_auto_bright"] = True
    return kwargs


@dataclass(slots=True)
class AppSettings:
    """Configurações de conversão + estado da janela."""

    conversion: ConversionSettings = field(default_factory=ConversionSettings)
    output_dir: str = ""
    last_source_dir: str = ""
    window_geometry: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "conversion": self.conversion.to_dict(),
            "output_dir": self.output_dir,
            "last_source_dir": self.last_source_dir,
            "window_geometry": self.window_geometry,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        data = data or {}
        return cls(
            conversion=ConversionSettings.from_dict(data.get("conversion", {})),
            output_dir=str(data.get("output_dir", "") or ""),
            last_source_dir=str(data.get("last_source_dir", "") or ""),
            window_geometry=str(data.get("window_geometry", "") or ""),
        )


class SettingsStore:
    """Lê e grava :class:`AppSettings` em um arquivo JSON.

    Falhas de leitura nunca impedem a aplicação de abrir: um arquivo corrompido
    é registrado no log e substituído pelos valores padrão.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else settings_file()

    def load(self) -> AppSettings:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return AppSettings()
        except OSError as exc:
            _log.warning("Não foi possível ler as configurações (%s): %s", self.path, exc)
            return AppSettings()

        try:
            return AppSettings.from_dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            _log.warning("Arquivo de configurações inválido (%s): %s", self.path, exc)
            return AppSettings()

    def save(self, settings: AppSettings) -> bool:
        """Grava de forma atômica (arquivo temporário + ``os.replace``)."""
        try:
            ensure_dir(self.path.parent)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(
                json.dumps(settings.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temp, self.path)
            return True
        except OSError as exc:
            _log.warning("Não foi possível salvar as configurações: %s", exc)
            return False
