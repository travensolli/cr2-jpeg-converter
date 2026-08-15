"""Configuração central de logging.

Regras adotadas:

* ``print()`` não é usado como mecanismo de log em lugar nenhum do projeto;
* o arquivo é rotacionado para não crescer indefinidamente em lotes grandes;
* o handler de console só é adicionado quando existe um ``sys.stderr`` real —
  em builds ``--windowed`` do PyInstaller ``sys.stderr`` é ``None`` e criar um
  ``StreamHandler`` sobre ele quebraria a aplicação no primeiro log.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from cr2_converter.utils.paths import default_log_dir, ensure_dir, is_frozen

__all__ = ["LOG_FILE_NAME", "setup_logging"]

LOG_FILE_NAME = "cr2_converter.log"

_FILE_FORMAT = "%(asctime)s | %(levelname)-7s | %(threadName)-14s | %(name)-38s | %(message)s"
_CONSOLE_FORMAT = "%(levelname)-7s | %(name)s | %(message)s"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 5


def setup_logging(
    *,
    level: int = logging.INFO,
    log_dir: Path | None = None,
    console: bool | None = None,
) -> Path:
    """Configura o logger raiz e devolve o caminho do arquivo de log.

    A função é idempotente: chamadas repetidas substituem os handlers
    anteriores em vez de duplicá-los (importante para testes).
    """
    directory = ensure_dir(Path(log_dir) if log_dir else default_log_dir())
    log_path = directory / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)

    if console is None:
        console = not is_frozen()
    if console and sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
        root.addHandler(stream_handler)

    # PIL emite muitos DEBUG irrelevantes ao salvar cada arquivo.
    logging.getLogger("PIL").setLevel(logging.WARNING)
    return log_path
