"""Planejamento do lote: de arquivos de origem para pares origem → destino.

Separar o planejamento da execução resolve dois problemas de uma vez:

* **conflitos** com arquivos já existentes podem ser resolvidos na thread da
  interface, antes de começar, sem que uma thread de trabalho precise parar
  para perguntar algo ao usuário (o que exigiria sincronização delicada);
* **colisões dentro do próprio lote** ficam visíveis: com "manter estrutura de
  subpastas" desligada, ``Casamento/IMG_001.CR2`` e ``Festa/IMG_001.CR2``
  disputariam o mesmo ``IMG_001.jpg``. O planejador desempata com sufixos
  ``(1)``, ``(2)``… em vez de deixar um arquivo sobrescrever o outro.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from cr2_converter.core.types import ConversionJob
from cr2_converter.utils.filesystem import SourceFile, path_key, unique_path

__all__ = [
    "JPEG_SUFFIX",
    "destination_for",
    "existing_destinations",
    "jpeg_name",
    "plan_jobs",
]

_log = logging.getLogger(__name__)

JPEG_SUFFIX = ".jpg"


def jpeg_name(source: Path) -> str:
    """``IMG_0001.CR2`` → ``IMG_0001.jpg`` (sempre em minúsculas)."""
    return source.stem + JPEG_SUFFIX


def destination_for(
    source: Path,
    root: Path | None,
    output_dir: Path,
    *,
    keep_structure: bool,
) -> Path:
    """Calcula o caminho de saída de um arquivo, sem tratar colisões."""
    if keep_structure and root is not None:
        try:
            relative = source.parent.relative_to(root)
        except ValueError:
            _log.debug("%s está fora da raiz %s; usando a pasta de saída direta.", source, root)
            relative = Path()
        return output_dir / relative / jpeg_name(source)
    return output_dir / jpeg_name(source)


def plan_jobs(
    items: Sequence[SourceFile],
    output_dir: Path,
    *,
    keep_structure: bool = False,
    overwrite: bool = False,
    rows: Sequence[int] | None = None,
) -> list[ConversionJob]:
    """Monta a lista de trabalhos a executar.

    :param rows: linhas correspondentes na lista da interface (mesma ordem de
        ``items``). Quando omitido, usa a própria posição do item.
    """
    base = Path(output_dir).expanduser()
    jobs: list[ConversionJob] = []
    taken: set[str] = set()

    for index, item in enumerate(items):
        destination = destination_for(
            item.path, item.root, base, keep_structure=keep_structure
        )
        # check_disk=False: arquivos já existentes são decididos pela política
        # de conflito; aqui só evitamos que dois arquivos do lote gravem no
        # mesmo destino.
        resolved = unique_path(destination, taken, check_disk=False)
        if resolved != destination:
            _log.info(
                "Colisão de nomes no lote: %s será gravado como %s",
                item.path.name,
                resolved.name,
            )
        taken.add(path_key(resolved))
        jobs.append(
            ConversionJob(
                source=item.path,
                destination=resolved,
                overwrite=overwrite,
                row=rows[index] if rows is not None else index,
            )
        )
    return jobs


def existing_destinations(jobs: Sequence[ConversionJob]) -> list[ConversionJob]:
    """Trabalhos cujo JPEG de destino já existe em disco."""
    found: list[ConversionJob] = []
    for job in jobs:
        try:
            if job.destination.exists():
                found.append(job)
        except OSError as exc:  # pragma: no cover - caminho inacessível
            _log.warning("Não foi possível verificar %s: %s", job.destination, exc)
    return found
