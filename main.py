"""Inicia o CR2 Converter.

    python main.py

Equivale a ``python -m cr2_converter``; existe como arquivo separado por ser o
ponto de entrada usado pelo PyInstaller e o caminho mais óbvio para quem abre o
projeto pela primeira vez.
"""

from __future__ import annotations

import sys

from cr2_converter.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
