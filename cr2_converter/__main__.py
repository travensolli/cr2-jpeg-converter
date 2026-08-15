"""Ponto de entrada da aplicação (``python -m cr2_converter``)."""

from __future__ import annotations

import logging
import sys
from types import TracebackType

from cr2_converter import APP_NAME, APP_SLUG, __version__
from cr2_converter.utils.logger import setup_logging

__all__ = ["main"]

_log = logging.getLogger(__name__)

_MISSING_RAWPY = (
    "A biblioteca rawpy (LibRaw) não pôde ser carregada, e sem ela não é "
    "possível ler arquivos CR2.\n\n"
    "Ative o ambiente virtual e instale as dependências:\n"
    "    pip install -r requirements.txt\n\n"
    "Detalhe técnico: {error}"
)


def _install_excepthook(window_title: str) -> None:
    """Registra exceções não tratadas e avisa o usuário em vez de sumir."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    def _hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):  # pragma: no cover
            sys.__excepthook__(exc_type, exc, tb)
            return
        _log.critical("Exceção não tratada", exc_info=(exc_type, exc, tb))
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None,
                window_title,
                "Ocorreu um erro inesperado.\n\n"
                f"{exc_type.__name__}: {exc}\n\n"
                "Os detalhes foram registrados no arquivo de log.",
            )

    sys.excepthook = _hook


def _check_rawpy() -> str | None:
    """Devolve uma mensagem de erro se o rawpy não puder ser importado."""
    try:
        import rawpy  # noqa: F401
    except Exception as exc:
        return _MISSING_RAWPY.format(error=f"{type(exc).__name__}: {exc}")
    return None


def main(argv: list[str] | None = None) -> int:
    """Inicializa o logging, a aplicação Qt e abre a janela principal."""
    log_path = setup_logging()
    _log.info("Iniciando %s %s (log em %s)", APP_NAME, __version__, log_path)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from cr2_converter.app.main_window import MainWindow
    from cr2_converter.app.style import STYLESHEET

    # Precisa ser definido antes de instanciar o QApplication.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_SLUG)
    app.setStyleSheet(STYLESHEET)

    _install_excepthook(APP_NAME)

    error = _check_rawpy()
    if error:
        _log.error("rawpy indisponível: %s", error)
        QMessageBox.critical(None, APP_NAME, error)
        return 1

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
