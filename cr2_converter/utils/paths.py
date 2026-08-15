"""Localização dos diretórios usados pela aplicação.

O comportamento muda conforme a aplicação esteja rodando a partir do código
fonte ou de um executável gerado pelo PyInstaller:

* **código fonte** — os logs ficam em ``<raiz do projeto>/logs`` (conforme
  solicitado no projeto), o que facilita o desenvolvimento;
* **executável** — a pasta do ``.exe`` pode ser somente leitura (ex.:
  ``C:\\Program Files``), então os logs vão para a pasta de dados do usuário.

As configurações ficam sempre na pasta de dados do usuário, para não sujar
o repositório e para funcionarem igual nos dois modos.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cr2_converter import APP_SLUG

__all__ = [
    "app_data_dir",
    "default_log_dir",
    "ensure_dir",
    "is_frozen",
    "project_root",
    "settings_file",
]


def is_frozen() -> bool:
    """Indica se estamos rodando dentro de um executável PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Raiz do projeto (pasta que contém o pacote ``cr2_converter``)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    """Pasta de dados do usuário, específica por plataforma."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_SLUG


def default_log_dir() -> Path:
    """Pasta padrão dos arquivos ``.log``."""
    if is_frozen():
        return app_data_dir() / "logs"
    return project_root() / "logs"


def settings_file() -> Path:
    """Caminho do arquivo JSON de configurações."""
    return app_data_dir() / "settings.json"


def ensure_dir(path: Path) -> Path:
    """Cria o diretório (e os pais) se necessário e o devolve."""
    path.mkdir(parents=True, exist_ok=True)
    return path
