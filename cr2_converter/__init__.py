"""CR2 Converter — conversor desktop de arquivos RAW Canon (.CR2) para JPEG.

Este pacote é dividido em três camadas independentes:

``cr2_converter.core``
    Regras de negócio puras (conversão, metadados, planejamento, lote).
    Não importa PySide6 e pode ser testado sem interface gráfica.

``cr2_converter.app``
    Camada de interface (PySide6). Depende de ``core``, nunca o contrário.

``cr2_converter.utils``
    Utilitários genéricos (sistema de arquivos, logging, caminhos).
"""

from __future__ import annotations

__all__ = ["APP_NAME", "APP_SLUG", "__version__"]

__version__ = "1.0.0"

APP_NAME = "CR2 Converter"
"""Nome exibido ao usuário."""

APP_SLUG = "CR2Converter"
"""Nome usado em diretórios de dados e no executável."""
