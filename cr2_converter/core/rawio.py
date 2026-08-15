"""Acesso ao LibRaw via rawpy: abertura de arquivos, informações e preview.

Concentrar aqui todo o contato com o rawpy tem duas vantagens: o restante do
núcleo fica testável com objetos falsos e os detalhes chatos da biblioteca
(codificação de caminhos no Windows, rotação do sensor, miniaturas ausentes)
ficam em um lugar só.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from cr2_converter.core import metadata

try:  # rawpy é opcional em tempo de import para permitir testes sem LibRaw
    import rawpy
except ImportError:  # pragma: no cover - ambiente sem rawpy
    rawpy = None  # type: ignore[assignment]

__all__ = [
    "PREVIEW_MAX_EDGE",
    "RawInfo",
    "RawUnavailableError",
    "open_raw",
    "read_raw_info",
    "render_preview",
]

_log = logging.getLogger(__name__)

PREVIEW_MAX_EDGE = 1400
"""Maior dimensão da pré-visualização, em pixels."""

#: Rotação a aplicar na miniatura embutida conforme ``sizes.flip`` do LibRaw.
#: O ``postprocess`` já aplica essa rotação sozinho; a miniatura, não.
#: (flip 5 corresponde a Orientation EXIF 8, flip 6 a Orientation 6.)
_FLIP_TRANSPOSE = {
    3: Image.Transpose.ROTATE_180,
    5: Image.Transpose.ROTATE_90,
    6: Image.Transpose.ROTATE_270,
}

#: Valores de ``flip`` que trocam largura por altura na imagem final.
_FLIP_SWAPS_AXES = frozenset({5, 6})


class RawUnavailableError(RuntimeError):
    """rawpy/LibRaw não está disponível no ambiente."""


def _require_rawpy() -> None:
    if rawpy is None:  # pragma: no cover - depende do ambiente
        raise RawUnavailableError(
            "A biblioteca rawpy não está instalada. "
            "Instale as dependências com: pip install -r requirements.txt"
        )


def _open_errors() -> tuple[type[BaseException], ...]:
    """Exceções do rawpy que indicam falha ao *abrir* o arquivo."""
    if rawpy is None:  # pragma: no cover - ambiente sem rawpy
        return ()
    return (rawpy.LibRawFileUnsupportedError, rawpy.LibRawIOError)


def _open_raw_handle(path: Path) -> tuple[Any, Any]:
    """Abre o RAW devolvendo ``(raw, arquivo_aberto_ou_None)``.

    O caminho normal usa ``LibRaw::open_file``, que é o mais eficiente: o
    LibRaw lê o arquivo sob demanda, sem carregá-lo inteiro na memória.

    O rawpy 0.27 (LibRaw 0.22) abre corretamente caminhos com acentos no
    Windows — isso foi verificado com ``C:\\…\\Ensaio Café São Paulo\\IMG_ação.CR2``.
    Versões mais antigas, porém, repassavam o caminho como ``const char*``
    interpretado na página de código ANSI e falhavam nesses casos. Por isso a
    tentativa por objeto de arquivo (que usa ``open_buffer``) existe apenas
    como plano B para caminhos não-ASCII: ela funciona sempre, mas mantém o
    CR2 inteiro em memória e não deve ser o caminho padrão.
    """
    path_text = str(path)
    try:
        return rawpy.imread(path_text), None
    except _open_errors():
        if path_text.isascii():
            raise
        _log.debug("Reabrindo %s via buffer (caminho não-ASCII).", path)

    handle = path.open("rb")
    try:
        return rawpy.imread(handle), handle
    except BaseException:
        handle.close()
        raise


@contextmanager
def open_raw(path: Path) -> Iterator[Any]:
    """Abre um arquivo RAW e garante a liberação dos buffers do LibRaw.

    A abertura fica fora do ``try`` do ``yield`` de propósito: se o consumidor
    levantar uma exceção do LibRaw dentro do ``with`` (por exemplo, durante o
    ``postprocess``), ela não deve ser confundida com uma falha de abertura.
    """
    _require_rawpy()
    raw, handle = _open_raw_handle(path)
    try:
        yield raw
    finally:
        try:
            raw.close()
        finally:
            if handle is not None:
                handle.close()


@dataclass(frozen=True, slots=True)
class RawInfo:
    """Informações exibidas no painel de pré-visualização."""

    width: int = 0
    height: int = 0
    camera: str = ""
    lens: str = ""
    iso: float = 0.0
    aperture: float = 0.0
    shutter: float = 0.0
    focal: float = 0.0
    captured_at: datetime | None = None

    @property
    def dimensions_text(self) -> str:
        return f"{self.width} × {self.height}" if self.width and self.height else ""

    @property
    def exposure_text(self) -> str:
        """Linha compacta com ISO, abertura, velocidade e distância focal."""
        parts: list[str] = []
        if self.iso:
            parts.append(f"ISO {self.iso:.0f}")
        if self.aperture:
            parts.append(f"f/{self.aperture:.1f}")
        if self.shutter:
            parts.append(format_shutter(self.shutter))
        if self.focal:
            parts.append(f"{self.focal:.0f} mm")
        return " · ".join(parts)


def format_shutter(seconds: float) -> str:
    """``0.003125`` → ``1/320 s``; ``2.5`` → ``2.5 s``."""
    if seconds <= 0:
        return ""
    if seconds >= 1:
        return f"{seconds:.1f} s".replace(".0 ", " ")
    return f"1/{round(1 / seconds)} s"


def _oriented_size(sizes: Any) -> tuple[int, int]:
    """Dimensões finais considerando a rotação aplicada pelo LibRaw."""
    width, height = int(sizes.width), int(sizes.height)
    if int(getattr(sizes, "flip", 0)) in _FLIP_SWAPS_AXES:
        return height, width
    return width, height


def read_raw_info(raw: Any, path: Path) -> RawInfo:
    """Extrai metadados do arquivo aberto, tolerando campos ausentes.

    O rawpy não expõe fabricante/modelo da câmera, então esses dois campos vêm
    do EXIF lido pelo :mod:`cr2_converter.core.metadata`.
    """
    try:
        width, height = _oriented_size(raw.sizes)
    except Exception as exc:
        _log.debug("Dimensões indisponíveis para %s: %s", path, exc)
        width = height = 0

    other = getattr(raw, "other", None)
    lens_info = getattr(raw, "lens", None)
    tags = metadata.read_basic_tags(path)

    camera = " ".join(part for part in (tags.get("make", ""), tags.get("model", "")) if part)
    # Muitas câmeras repetem o fabricante no modelo ("Canon Canon EOS ...").
    make = tags.get("make", "")
    model = tags.get("model", "")
    if make and model.lower().startswith(make.lower()):
        camera = model

    return RawInfo(
        width=width,
        height=height,
        camera=camera.strip(),
        lens=str(getattr(lens_info, "model", "") or "").strip(),
        iso=float(getattr(other, "iso_speed", 0.0) or 0.0),
        aperture=float(getattr(other, "aperture", 0.0) or 0.0),
        shutter=float(getattr(other, "shutter_speed", 0.0) or 0.0),
        focal=float(getattr(other, "focal_length", 0.0) or 0.0),
        captured_at=getattr(other, "timestamp", None),
    )


def _thumbnail_image(raw: Any) -> Image.Image | None:
    """Miniatura embutida no RAW, já rotacionada; ``None`` se não existir."""
    try:
        thumb = raw.extract_thumb()
    except Exception as exc:
        _log.debug("Miniatura indisponível: %s: %s", type(exc).__name__, exc)
        return None

    try:
        if thumb.format == rawpy.ThumbFormat.JPEG:
            image = Image.open(io.BytesIO(thumb.data))
            image.load()
        else:
            image = Image.fromarray(thumb.data).copy()
    except Exception as exc:
        _log.debug("Miniatura ilegível: %s: %s", type(exc).__name__, exc)
        return None

    transpose = _FLIP_TRANSPOSE.get(int(getattr(raw.sizes, "flip", 0)))
    if transpose is not None:
        image = image.transpose(transpose)
    return image


def render_preview(path: Path, max_edge: int = PREVIEW_MAX_EDGE) -> tuple[bytes, RawInfo]:
    """Gera uma pré-visualização JPEG e as informações do arquivo.

    Usa a miniatura embutida no CR2 (praticamente instantânea) e só recorre à
    revelação em meia resolução quando o arquivo não tem miniatura utilizável.
    Devolve bytes JPEG para que a interface só precise de ``QPixmap.loadFromData``,
    sem lidar com buffers numpy nem com tempo de vida de memória.
    """
    with open_raw(path) as raw:
        info = read_raw_info(raw, path)
        image = _thumbnail_image(raw)
        if image is None:
            _log.debug("Usando revelação em meia resolução para o preview de %s", path)
            rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
            try:
                image = Image.fromarray(rgb).copy()
            finally:
                del rgb

        try:
            if image.mode != "RGB":
                # convert() devolve uma nova imagem; a anterior é fechada aqui
                # em vez de ficar dependendo do coletor de lixo.
                converted = image.convert("RGB")
                image.close()
                image = converted
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
        finally:
            image.close()

    return buffer.getvalue(), info
