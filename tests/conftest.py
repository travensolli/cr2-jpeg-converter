"""Configuração compartilhada dos testes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Precisa ser definido antes de qualquer import do Qt: permite construir
# widgets em máquinas sem servidor gráfico (CI, terminal remoto).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cr2_converter.core.settings import ConversionSettings
from cr2_converter.utils.filesystem import SourceFile


@pytest.fixture
def settings() -> ConversionSettings:
    """Configurações previsíveis: sem EXIF, sem redimensionar, 1 thread."""
    return ConversionSettings(
        quality=90,
        preserve_exif=False,
        resize_enabled=False,
        workers=1,
    )


@pytest.fixture
def make_cr2(tmp_path: Path):
    """Cria arquivos ``.CR2`` de mentira (o conteúdo é irrelevante nos testes).

    O conversor recebe os pixels do :mod:`tests.fake_raw`, então o que importa
    aqui é apenas o caminho existir com o tamanho e a extensão certos.
    """

    def _make(relative: str, size: int = 2048) -> Path:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x49\x49\x2a\x00" + b"\x00" * max(size - 4, 0))
        return path

    return _make


@pytest.fixture
def sources(make_cr2):
    """Três arquivos em uma pasta, com raiz definida."""

    def _sources(*names: str, root: Path | None = None) -> list[SourceFile]:
        return [SourceFile(make_cr2(name), root) for name in names]

    return _sources


@pytest.fixture(scope="session")
def qapp():
    """``QApplication`` única para os testes de interface."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    # Não encerra o app: o Qt não suporta recriar QApplication no mesmo processo.
