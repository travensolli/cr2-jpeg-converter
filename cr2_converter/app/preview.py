"""Painel de pré-visualização.

Regras que mantêm o painel barato mesmo com milhares de arquivos na lista:

* apenas **um** arquivo é lido por vez (pool com uma única thread);
* a seleção é filtrada por um temporizador — navegar com as setas do teclado
  não dispara uma leitura por linha percorrida;
* respostas atrasadas são descartadas comparando o id da requisição, o que
  evita que a imagem de um arquivo antigo apareça sobre o atual.

A leitura usa a miniatura embutida no CR2 (ver
:func:`cr2_converter.core.rawio.render_preview`), não a revelação completa.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import QGroupBox, QLabel, QSizePolicy, QVBoxLayout, QWidget

from cr2_converter.app.workers import PreviewSignals, PreviewTask
from cr2_converter.core.rawio import RawInfo
from cr2_converter.utils.filesystem import human_size

__all__ = ["PreviewPanel"]

_DEBOUNCE_MS = 180
_PLACEHOLDER = "Selecione um arquivo da lista\npara ver a pré-visualização"


class PreviewPanel(QGroupBox):
    """Mostra a miniatura e os dados técnicos do arquivo selecionado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Pré-visualização", parent)

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = PreviewSignals(self)
        self._signals.ready.connect(self._on_ready)
        self._signals.failed.connect(self._on_failed)

        self._request_id = 0
        self._pending: tuple[Path, int] | None = None
        self._pixmap: QPixmap | None = None
        self._current_name = ""
        self._size_bytes = 0

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._start_pending)

        self._image = QLabel(_PLACEHOLDER, self)
        self._image.setObjectName("previewImage")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumHeight(200)
        self._image.setMinimumWidth(120)
        # Ignored evita que o pixmap redimensionado force o layout a crescer,
        # o que geraria um laço de redimensionamento.
        self._image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._image.setWordWrap(True)

        self._info = QLabel("", self)
        self._info.setObjectName("previewInfo")
        self._info.setWordWrap(True)
        self._info.setTextFormat(Qt.TextFormat.RichText)
        self._info.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._info.setMinimumHeight(72)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(self._image, stretch=1)
        layout.addWidget(self._info)

    # ------------------------------------------------------------------
    def load(self, path: Path, size_bytes: int) -> None:
        """Agenda a pré-visualização de ``path`` (com atraso anti-repetição)."""
        self._pending = (path, size_bytes)
        self._current_name = path.name
        self._size_bytes = size_bytes
        self._image.setText("Carregando…")
        self._image.setPixmap(QPixmap())
        self._pixmap = None
        self._info.setText(f"<b>{html.escape(path.name)}</b>")
        self._timer.start()

    def clear(self) -> None:
        """Volta ao estado inicial e invalida requisições em andamento."""
        self._timer.stop()
        self._pending = None
        self._request_id += 1
        self._pixmap = None
        self._image.setPixmap(QPixmap())
        self._image.setText(_PLACEHOLDER)
        self._info.setText("")

    def shutdown(self, timeout_ms: int = 4000) -> None:
        """Espera as tarefas pendentes antes da janela ser destruída.

        Sem isso, uma tarefa poderia emitir um sinal para um objeto Qt já
        removido durante o fechamento da aplicação.
        """
        self._timer.stop()
        self._pool.clear()
        self._pool.waitForDone(timeout_ms)

    # ------------------------------------------------------------------
    def _start_pending(self) -> None:
        if self._pending is None:
            return
        path, _size_bytes = self._pending
        self._pending = None
        self._request_id += 1
        self._pool.start(PreviewTask(self._request_id, path, self._signals))

    def _on_ready(self, request_id: int, data: object, info: object) -> None:
        if request_id != self._request_id:
            return  # resposta obsoleta
        pixmap = QPixmap()
        if not isinstance(data, (bytes, bytearray)) or not pixmap.loadFromData(bytes(data), "JPEG"):
            self._image.setText("Não foi possível exibir a imagem")
            return
        self._pixmap = pixmap
        self._image.setText("")
        self._apply_pixmap()
        if isinstance(info, RawInfo):
            self._info.setText(self._describe(info))

    def _on_failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self._pixmap = None
        self._image.setPixmap(QPixmap())
        self._image.setText(f"Não foi possível ler o arquivo:\n{message}")

    def _describe(self, info: RawInfo) -> str:
        lines: list[str] = [f"<b>{html.escape(self._current_name)}</b>"]
        if info.camera:
            lines.append(html.escape(info.camera))
        if info.lens:
            lines.append(html.escape(info.lens))

        third: list[str] = []
        if info.dimensions_text:
            third.append(info.dimensions_text)
        if self._size_bytes:
            third.append(human_size(self._size_bytes))
        if third:
            lines.append(" · ".join(third))
        if info.exposure_text:
            lines.append(html.escape(info.exposure_text))
        return "<br>".join(lines)

    # ------------------------------------------------------------------
    def _apply_pixmap(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        target = self._image.size()
        if target.width() <= 1 or target.height() <= 1:
            return
        self._image.setPixmap(
            self._pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_pixmap()
