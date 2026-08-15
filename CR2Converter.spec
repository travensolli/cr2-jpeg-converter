# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller para gerar o CR2Converter.exe.

Uso:
    pyinstaller CR2Converter.spec

Requer PyInstaller >= 6.0 (o formato de EXE/COLLECT abaixo é o da série 6.x).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

# ---------------------------------------------------------------------------
# Opções ajustáveis
# ---------------------------------------------------------------------------

ONEFILE = False
"""Como distribuir o programa.

``False`` (padrão) gera ``dist/CR2Converter/CR2Converter.exe`` junto de uma
pasta com as bibliotecas. Abre rápido, porque nada precisa ser extraído.

``True`` gera um único ``dist/CR2Converter.exe``, mais fácil de enviar para
alguém, mas cada execução extrai ~150 MB do Qt para uma pasta temporária, o
que adiciona alguns segundos à abertura.
"""

ICON: str | None = None
"""Caminho para um ``.ico`` opcional. Ex.: ``ICON = "assets/icon.ico"``."""

# ---------------------------------------------------------------------------
# DLLs nativas do rawpy (LibRaw)
# ---------------------------------------------------------------------------
# O rawpy distribui o LibRaw como DLL dentro do próprio pacote
# (``raw_r.dll`` = build reentrante, ``vcomp140.dll`` = runtime do OpenMP).
# Sem elas o executável abre e falha no primeiro arquivo aberto.
binaries = collect_dynamic_libs("rawpy")

# Em algumas plataformas o delvewheel/auditwheel coloca as bibliotecas em um
# diretório irmão ``rawpy.libs``, que a coleta acima não alcança.
try:
    import rawpy

    _package = Path(rawpy.__file__).resolve().parent
    _external = _package.parent / f"{_package.name}.libs"
    if _external.is_dir():
        binaries += [
            (str(item), ".")
            for item in _external.iterdir()
            if item.suffix.lower() in {".dll", ".so", ".dylib"} or ".so." in item.name
        ]
except ImportError:  # pragma: no cover - checado pelo build_exe.ps1
    raise SystemExit(
        "rawpy não está instalado no ambiente atual. "
        "Ative o venv e rode: pip install -r requirements-dev.txt"
    )

# ---------------------------------------------------------------------------
# Módulos que não fazem parte do programa e só aumentariam o executável
# ---------------------------------------------------------------------------
excludes = [
    "tkinter",
    "unittest",
    "pytest",
    "pydoc_data",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "PyQt5",
    "PyQt6",
    # Componentes pesados do Qt que a aplicação não usa.
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtTest",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

_common = dict(
    name="CR2Converter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX fica desligado de propósito: além de ganho pequeno, executáveis
    # comprimidos com UPX são frequentemente marcados como falso positivo por
    # antivírus, o que atrapalharia a distribuição.
    upx=False,
    console=False,  # equivalente a --windowed: nada de janela de terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **_common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_common)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="CR2Converter",
    )
