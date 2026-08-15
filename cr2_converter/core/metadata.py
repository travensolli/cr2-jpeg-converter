"""Preservação de metadados EXIF do CR2 para o JPEG gerado.

Por que este módulo existe
--------------------------
O rawpy entrega apenas pixels: ele não expõe o bloco EXIF do arquivo. Como o
CR2 é internamente um TIFF, o ``piexif`` consegue lê-lo diretamente
(``piexif.load`` aceita TIFF) e reescrever o bloco dentro do JPEG de saída.

Cuidados obrigatórios (todos verificados contra arquivos CR2 reais)
-------------------------------------------------------------------
1. **Limite de 64 KB.** O EXIF vive em um segmento APP1 cujo tamanho é gravado
   em 2 bytes. ``piexif.insert`` monta ``struct.pack(">H", len(exif) + 2)``
   *sem verificar o limite*, então um EXIF grande gera ``struct.error`` ou um
   arquivo corrompido. Um CR2 comum já produz ~62 KB (a MakerNote da Canon
   sozinha passa de 44 KB), ou seja, o estouro é um caso real e não teórico.
   :func:`_dump_within_app1` descarta campos por ordem de importância até caber.

2. **Tags desconhecidas.** ``piexif.dump`` faz ``TAGS[ifd][key]`` e levanta
   ``KeyError`` para qualquer tag que não conheça (ex.: as tags de *padding*
   escritas por alguns softwares). Tudo que não estiver no dicionário do piexif
   é removido antes do dump.

3. **Orientação.** O LibRaw já entrega a imagem rotacionada. Copiar o
   ``Orientation`` original (ex.: 8 = retrato) faria o visualizador girar a foto
   uma segunda vez. A tag é reescrita como 1 (topo à esquerda).

4. **Tags estruturais.** O IFD0 de um CR2 descreve o *preview* JPEG embutido
   (``StripOffsets``, ``StripByteCounts``, ``Compression``…). Esses valores
   apontam para dentro do CR2 e não fazem sentido no JPEG de saída.

Limitação conhecida: a MakerNote da Canon usa deslocamentos absolutos relativos
ao arquivo original. Ao ser copiada para um novo arquivo, os ponteiros internos
deixam de bater. Campos EXIF padrão (data, ISO, abertura, lente, GPS) não são
afetados; leitores tolerantes como o ExifTool reconstroem a MakerNote, outros
podem ignorá-la. Preservar é melhor que descartar, então ela é mantida — exceto
quando precisa sair para respeitar o limite de 64 KB.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import piexif
from piexif import TYPES

from cr2_converter import APP_NAME, __version__

__all__ = [
    "APP1_MAX_PAYLOAD",
    "ExifCopyError",
    "build_exif_bytes",
    "copy_exif_to_jpeg",
    "embed_exif",
    "read_basic_tags",
]

_log = logging.getLogger(__name__)

APP1_MAX_PAYLOAD = 65_533
"""Bytes úteis de um segmento APP1 (65.535 − 2 do próprio campo de tamanho)."""

_IFDS = ("0th", "Exif", "GPS", "Interop")

# --- identificadores de tags usados abaixo (nomes explícitos > números soltos)
_TAG_PROCESSING_SOFTWARE = 11
_TAG_IMAGE_WIDTH = 256
_TAG_IMAGE_LENGTH = 257
_TAG_ORIENTATION = 274
_TAG_MAKE = 271
_TAG_MODEL = 272
_TAG_DATETIME = 306
_TAG_XMLPACKET = 700
_TAG_EXIF_POINTER = 34665
_TAG_GPS_POINTER = 34853
_TAG_MAKERNOTE = 37500
_TAG_USERCOMMENT = 37510
_TAG_INTEROP_POINTER = 40965
_TAG_PIXEL_X = 40962
_TAG_PIXEL_Y = 40963

#: Tags do IFD0 que descrevem o *preview* embutido no CR2 e não podem ser
#: copiadas para o JPEG (apontariam para deslocamentos inexistentes).
_STRUCTURAL_0TH = frozenset(
    {
        _TAG_IMAGE_WIDTH,
        _TAG_IMAGE_LENGTH,
        258,  # BitsPerSample
        259,  # Compression
        262,  # PhotometricInterpretation
        273,  # StripOffsets
        277,  # SamplesPerPixel
        278,  # RowsPerStrip
        279,  # StripByteCounts
        284,  # PlanarConfiguration
        330,  # SubIFDs
        513,  # JPEGInterchangeFormat
        514,  # JPEGInterchangeFormatLength
        _TAG_EXIF_POINTER,  # ponteiros são recalculados pelo piexif
        _TAG_GPS_POINTER,
    }
)

#: Candidatos a descarte quando o EXIF não cabe em 64 KB, do menos para o mais
#: valioso.
_DROPPABLE: tuple[tuple[str, int, str], ...] = (
    ("0th", _TAG_XMLPACKET, "XMP (XMLPacket)"),
    ("Exif", _TAG_USERCOMMENT, "UserComment"),
    ("Exif", _TAG_MAKERNOTE, "MakerNote"),
)

#: Conjunto essencial usado como último recurso quando nem o descarte acima
#: resolve (arquivos com EXIF fora do comum).
_ESSENTIAL: dict[str, frozenset[int]] = {
    "0th": frozenset({_TAG_PROCESSING_SOFTWARE, 270, _TAG_MAKE, _TAG_MODEL, _TAG_ORIENTATION,
                      282, 283, 296, 305, _TAG_DATETIME, 315, 33432}),
    "Exif": frozenset({33434, 33437, 34850, 34855, 34864, 34866, 36864, 36867, 36868,
                       37377, 37378, 37380, 37383, 37385, 37386, 37521, 40961,
                       _TAG_PIXEL_X, _TAG_PIXEL_Y, 41986, 41987, 41989, 42032, 42033,
                       42034, 42036, 42037}),
    "GPS": frozenset(),  # GPS é pequeno e inteiro: preservado por completo
    "Interop": frozenset(),
}

#: No conjunto essencial, nenhum campo isolado pode ocupar muito do orçamento.
_ESSENTIAL_MAX_VALUE = 8 * 1024

_INT_RANGES: dict[int, tuple[int, int]] = {
    TYPES.Byte: (0, 0xFF),
    TYPES.Short: (0, 0xFFFF),
    TYPES.Long: (0, 0xFFFFFFFF),
    TYPES.SByte: (-0x80, 0x7F),
    TYPES.SShort: (-0x8000, 0x7FFF),
    TYPES.SLong: (-0x8000_0000, 0x7FFF_FFFF),
}

_RATIONAL_RANGE = {
    TYPES.Rational: (0, 0xFFFFFFFF),
    TYPES.SRational: (-0x8000_0000, 0x7FFF_FFFF),
}

#: Bytes lidos do início do arquivo quando só interessam Make/Model/DateTime.
#: Evita carregar um CR2 de 25 MB inteiro só para preencher o painel de
#: pré-visualização. Não é usado na conversão, onde a fidelidade importa.
_HEADER_PROBE_BYTES = 512 * 1024


class ExifCopyError(RuntimeError):
    """Falha ao copiar os metadados (não impede a gravação do JPEG)."""


# --------------------------------------------------------------------------
# Validação de valores
# --------------------------------------------------------------------------
def _as_int_tuple(value: Any) -> tuple[int, ...] | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return (value,)
    if isinstance(value, (tuple, list)) and all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        return tuple(value)
    return None


def _valid_rational(value: Any, low: int, high: int) -> tuple | None:
    """Aceita ``(num, den)`` ou uma sequência de pares."""
    if not isinstance(value, (tuple, list)) or not value:
        return None
    if isinstance(value[0], int) and not isinstance(value[0], bool):
        pair = _as_int_tuple(value)
        if pair is None or len(pair) != 2:
            return None
        return pair if all(low <= n <= high for n in pair) else None

    pairs: list[tuple[int, int]] = []
    for item in value:
        pair = _as_int_tuple(item)
        if pair is None or len(pair) != 2 or not all(low <= n <= high for n in pair):
            return None
        pairs.append(pair)
    return tuple(pairs)


def _normalize_value(type_id: int, value: Any) -> Any | None:
    """Devolve o valor pronto para ``piexif.dump`` ou ``None`` para descartá-lo.

    O piexif levanta ``ValueError``/``UnboundLocalError``/``struct.error``
    conforme o tipo errado que receber; validar antes evita perder o EXIF
    inteiro por causa de uma única tag malformada.
    """
    if type_id == TYPES.Ascii:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("latin-1", errors="replace")
        return None

    if type_id in (TYPES.Undefined, TYPES.Byte, TYPES.SByte):
        if isinstance(value, bytes):
            return value
        if type_id != TYPES.Undefined:
            numbers = _as_int_tuple(value)
            low, high = _INT_RANGES[type_id]
            if numbers and all(low <= n <= high for n in numbers):
                return numbers
        return None

    if type_id in _INT_RANGES:
        numbers = _as_int_tuple(value)
        if numbers is None:
            return None
        low, high = _INT_RANGES[type_id]
        return numbers if all(low <= n <= high for n in numbers) else None

    if type_id in _RATIONAL_RANGE:
        low, high = _RATIONAL_RANGE[type_id]
        return _valid_rational(value, low, high)

    if type_id in (TYPES.Float, TYPES.DFloat):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, (tuple, list)) and all(
            isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
        ):
            return tuple(value)
        return None

    return None


# --------------------------------------------------------------------------
# Leitura e saneamento
# --------------------------------------------------------------------------
def _load_exif(path: Path) -> dict[str, Any]:
    """Lê o EXIF do CR2 (que é um TIFF) usando o piexif."""
    return piexif.load(str(path))


def _sanitize(exif: dict[str, Any], width: int, height: int) -> dict[str, dict[int, Any]]:
    """Filtra, corrige e complementa o EXIF lido do CR2."""
    clean: dict[str, dict[int, Any]] = {ifd: {} for ifd in _IFDS}

    for ifd in _IFDS:
        known = piexif.TAGS[ifd]
        source = exif.get(ifd) or {}
        target = clean[ifd]
        for tag, value in source.items():
            if not isinstance(tag, int) or tag not in known:
                continue  # piexif levantaria KeyError no dump
            if ifd == "0th" and tag in _STRUCTURAL_0TH:
                continue
            if ifd == "Exif" and tag == _TAG_INTEROP_POINTER:
                continue
            normalized = _normalize_value(known[tag]["type"], value)
            if normalized is not None:
                target[tag] = normalized

    # A imagem já sai rotacionada do LibRaw.
    clean["0th"][_TAG_ORIENTATION] = 1
    # Dimensões reais do JPEG gerado.
    clean["Exif"][_TAG_PIXEL_X] = int(width)
    clean["Exif"][_TAG_PIXEL_Y] = int(height)
    # Registra a ferramenta sem apagar o firmware da câmera (tag 305/Software).
    if _TAG_PROCESSING_SOFTWARE in piexif.TAGS["0th"]:
        clean["0th"][_TAG_PROCESSING_SOFTWARE] = f"{APP_NAME} {__version__}".encode("latin-1")

    return clean


def _dump_within_app1(exif: dict[str, dict[int, Any]]) -> bytes:
    """Serializa o EXIF garantindo que caiba no segmento APP1.

    Estratégia em três níveis: dump direto → descarte progressivo dos campos
    volumosos → conjunto essencial. Qualquer exceção do piexif é tratada da
    mesma forma, pois o objetivo é sempre degradar em vez de perder o EXIF.
    """
    candidate = {ifd: dict(values) for ifd, values in exif.items()}

    def _try_dump(data: dict[str, dict[int, Any]]) -> bytes | None:
        try:
            payload = piexif.dump(data)
        except Exception as exc:
            _log.debug("piexif.dump falhou: %s: %s", type(exc).__name__, exc)
            return None
        return payload if len(payload) <= APP1_MAX_PAYLOAD else None

    payload = _try_dump(candidate)
    if payload is not None:
        return payload

    for ifd, tag, name in _DROPPABLE:
        if candidate.get(ifd, {}).pop(tag, None) is None:
            continue
        _log.info("EXIF acima do limite de 64 KB: campo %s descartado.", name)
        payload = _try_dump(candidate)
        if payload is not None:
            return payload

    essential: dict[str, dict[int, Any]] = {}
    for ifd, values in candidate.items():
        allowed = _ESSENTIAL.get(ifd, frozenset())
        essential[ifd] = {
            tag: value
            for tag, value in values.items()
            # Um conjunto vazio significa "preservar o IFD inteiro" (GPS/Interop).
            if (not allowed or tag in allowed)
            and not (isinstance(value, bytes) and len(value) > _ESSENTIAL_MAX_VALUE)
        }
    payload = _try_dump(essential)
    if payload is not None:
        _log.info("EXIF reduzido ao conjunto essencial para caber no JPEG.")
        return payload

    raise ExifCopyError("não foi possível serializar o EXIF dentro do limite de 64 KB")


# --------------------------------------------------------------------------
# API pública
# --------------------------------------------------------------------------
def build_exif_bytes(source: Path, width: int, height: int) -> bytes:
    """Monta o bloco EXIF do JPEG a partir do CR2 de origem.

    :param width: largura final do JPEG (após rotação e redimensionamento).
    :param height: altura final do JPEG.
    :raises ExifCopyError: se o EXIF não puder ser lido ou serializado.
    """
    try:
        raw_exif = _load_exif(source)
    except Exception as exc:
        raise ExifCopyError(f"não foi possível ler o EXIF: {exc}") from exc
    return _dump_within_app1(_sanitize(raw_exif, width, height))


def embed_exif(jpeg_path: Path, exif_bytes: bytes) -> None:
    """Insere o bloco EXIF em um JPEG já gravado em disco."""
    if len(exif_bytes) > APP1_MAX_PAYLOAD:
        raise ExifCopyError("bloco EXIF maior que o limite do segmento APP1")
    try:
        piexif.insert(exif_bytes, str(jpeg_path))
    except Exception as exc:
        raise ExifCopyError(f"não foi possível gravar o EXIF: {exc}") from exc


def copy_exif_to_jpeg(source: Path, jpeg_path: Path, width: int, height: int) -> None:
    """Copia o EXIF do CR2 para o JPEG. Conveniência sobre as funções acima."""
    embed_exif(jpeg_path, build_exif_bytes(source, width, height))


def read_basic_tags(path: Path) -> dict[str, Any]:
    """Lê apenas ``Make``/``Model``/``DateTime`` para a pré-visualização.

    Lê no máximo :data:`_HEADER_PROBE_BYTES` do início do arquivo — o suficiente
    para o IFD0 de um CR2 — e só recorre ao arquivo inteiro se isso falhar.
    Esse atalho **não** é usado na conversão: um bloco truncado poderia cortar a
    MakerNote silenciosamente, o que é aceitável para exibir texto na tela, mas
    não para gravar metadados.
    """
    result: dict[str, Any] = {}
    try:
        with path.open("rb") as handle:
            head = handle.read(_HEADER_PROBE_BYTES)
        exif = piexif.load(head)
        if not exif.get("0th"):
            exif = _load_exif(path)
    except Exception:
        try:
            exif = _load_exif(path)
        except Exception as exc:
            _log.debug("EXIF indisponível para %s: %s", path, exc)
            return result

    first = exif.get("0th") or {}
    for key, tag in (("make", _TAG_MAKE), ("model", _TAG_MODEL), ("datetime", _TAG_DATETIME)):
        value = first.get(tag)
        if isinstance(value, bytes):
            result[key] = value.decode("latin-1", errors="replace").strip("\x00 ")
        elif value is not None:
            result[key] = str(value)
    orientation = first.get(_TAG_ORIENTATION)
    if isinstance(orientation, int):
        result["orientation"] = orientation
    return result
