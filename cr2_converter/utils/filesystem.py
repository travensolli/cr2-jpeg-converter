"""Descoberta de arquivos CR2 e utilitários de caminho.

Detalhe importante no Windows: ``Path.glob("*.CR2")`` é *case-insensitive*,
então varrer ``*.CR2`` e ``*.cr2`` separadamente retornaria cada arquivo duas
vezes. Aqui a varredura é feita uma única vez comparando a extensão em minúsculas,
o que funciona igual no Windows e no Linux (onde o glob é *case-sensitive*).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

__all__ = [
    "CR2_SUFFIX",
    "SourceFile",
    "collect_sources",
    "human_size",
    "is_cr2",
    "iter_cr2_files",
    "path_key",
    "prepare_output_dir",
    "safe_size",
    "unique_path",
]

_log = logging.getLogger(__name__)

CR2_SUFFIX = ".cr2"
"""Única extensão aceita. LibRaw lê outros RAW, mas o escopo aqui é CR2."""

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def is_cr2(path: Path | str) -> bool:
    """Verifica se o caminho aparenta ser um arquivo CR2 (por extensão)."""
    return str(path).lower().endswith(CR2_SUFFIX)


def path_key(path: Path) -> str:
    """Chave de comparação de caminhos, tolerante a maiúsculas no Windows.

    Usada para detectar duplicatas na lista de origem e colisões de destino.
    """
    return os.path.normcase(os.path.abspath(str(path)))


def safe_size(path: Path) -> int:
    """Tamanho do arquivo em bytes; ``0`` se não for possível ler."""
    try:
        return path.stat().st_size
    except OSError as exc:
        _log.warning("Não foi possível obter o tamanho de %s: %s", path, exc)
        return 0


def human_size(size: int) -> str:
    """Formata bytes de forma legível (ex.: ``24.5 MB``)."""
    value = float(max(size, 0))
    index = 0
    while value >= 1024.0 and index < len(_SIZE_UNITS) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value)} {_SIZE_UNITS[index]}"
    return f"{value:.1f} {_SIZE_UNITS[index]}"


def iter_cr2_files(root: Path, *, recursive: bool = True) -> Iterator[Path]:
    """Percorre ``root`` devolvendo os arquivos CR2 em ordem determinística.

    Diretórios ilegíveis são registrados no log e ignorados, para que uma
    subpasta sem permissão não interrompa a varredura inteira.
    Links simbólicos de diretório não são seguidos (evita laços infinitos).
    """

    def _on_error(exc: OSError) -> None:
        _log.warning("Não foi possível ler o diretório %s: %s", getattr(exc, "filename", "?"), exc)

    for dirpath, dirnames, filenames in os.walk(root, onerror=_on_error, followlinks=False):
        dirnames.sort(key=str.lower)
        for name in sorted(filenames, key=str.lower):
            if name.lower().endswith(CR2_SUFFIX):
                yield Path(dirpath) / name
        if not recursive:
            break


class SourceFile:
    """Arquivo de origem e a pasta-raiz de onde ele veio.

    ``root`` é ``None`` quando o arquivo foi adicionado individualmente pelo
    explorador de arquivos; nesse caso não há estrutura de subpastas a preservar.
    """

    __slots__ = ("path", "root")

    def __init__(self, path: Path, root: Path | None = None) -> None:
        self.path = path
        self.root = root

    def __repr__(self) -> str:  # pragma: no cover - apoio a depuração
        return f"SourceFile(path={self.path!r}, root={self.root!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SourceFile):
            return NotImplemented
        return path_key(self.path) == path_key(other.path) and self.root == other.root


def collect_sources(paths: Iterable[Path], *, recursive: bool = True) -> list[SourceFile]:
    """Expande uma lista mista de arquivos e pastas em arquivos CR2.

    Pastas viram a ``root`` dos arquivos encontrados dentro delas, o que permite
    reproduzir a estrutura de subpastas no destino. Arquivos soltos ficam sem
    ``root``. Duplicatas são removidas mantendo a primeira ocorrência.
    """
    found: list[SourceFile] = []
    seen: set[str] = set()

    for raw_path in paths:
        path = Path(raw_path)
        try:
            is_dir = path.is_dir()
        except OSError as exc:
            _log.warning("Caminho inacessível ignorado: %s (%s)", path, exc)
            continue

        if is_dir:
            for file_path in iter_cr2_files(path, recursive=recursive):
                key = path_key(file_path)
                if key not in seen:
                    seen.add(key)
                    found.append(SourceFile(file_path, path))
        elif is_cr2(path) and path.is_file():
            key = path_key(path)
            if key not in seen:
                seen.add(key)
                found.append(SourceFile(path, None))
    return found


def prepare_output_dir(text: str) -> tuple[Path | None, str]:
    """Valida e cria a pasta de destino.

    Devolve ``(pasta, "")`` em caso de sucesso ou ``(None, motivo)`` quando não
    é possível usá-la. A função é pura em relação à interface — quem chama
    decide como mostrar o erro —, o que a torna testável sem abrir diálogos.
    """
    cleaned = (text or "").strip().strip('"')
    if not cleaned:
        return None, "Selecione a pasta onde os arquivos JPEG serão gravados."

    directory = Path(cleaned).expanduser()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, f"Não foi possível usar a pasta de destino:\n{directory}\n\n{exc}"

    if not os.access(directory, os.W_OK):
        return None, f"Sem permissão de gravação em:\n{directory}"
    return directory, ""


def unique_path(path: Path, taken: set[str] | None = None, *, check_disk: bool = True) -> Path:
    """Devolve um caminho livre acrescentando ``(1)``, ``(2)``… ao nome.

    ``taken`` são caminhos já reservados no lote atual. ``check_disk=False``
    ignora arquivos existentes em disco — usado pelo planejador, onde arquivos
    já existentes são tratados pela política de conflito e não devem ser
    silenciosamente renomeados.
    """
    reserved = taken if taken is not None else set()

    def _is_free(candidate: Path) -> bool:
        if path_key(candidate) in reserved:
            return False
        return not (check_disk and candidate.exists())

    if _is_free(path):
        return path

    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if _is_free(candidate):
            return candidate
        counter += 1
