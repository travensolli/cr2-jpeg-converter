"""Painel de configurações de conversão.

O painel só conhece widgets: ele lê e escreve um
:class:`~cr2_converter.core.settings.ConversionSettings` e não executa nenhuma
regra de negócio. Toda a tradução para parâmetros do LibRaw acontece no núcleo.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cr2_converter.core.settings import (
    MAX_DIMENSION,
    MAX_QUALITY,
    MAX_WORKERS,
    MIN_QUALITY,
    ConversionSettings,
)
from cr2_converter.core.types import ConflictPolicy, WhiteBalance

__all__ = ["SettingsPanel"]

_EXPOSURE_STEPS_PER_EV = 10  # o slider trabalha em décimos de EV


class SettingsPanel(QGroupBox):
    """Seção "Configurações" da janela principal."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Configurações", parent)
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self._build_format(layout)
        self._build_resolution(layout)
        self._build_development(layout)
        self._build_metadata(layout)
        self._build_conflict(layout)
        self._build_performance(layout)
        layout.addStretch(1)

        self._connect_signals()
        self._update_resize_enabled()

    # -- construção ----------------------------------------------------
    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setContentsMargins(0, 8, 0, 2)
        return label

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    @staticmethod
    def _form() -> QFormLayout:
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return form

    def _build_format(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._section("Formato"))

        self.format_combo = QComboBox()
        self.format_combo.addItem("JPEG (.jpg)")
        self.format_combo.setToolTip("Nesta versão o único formato de saída é o JPEG.")

        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(MIN_QUALITY, MAX_QUALITY)
        self.quality_slider.setToolTip(
            "1 = menor arquivo e mais perda; 100 = máxima fidelidade.\n"
            "A partir de 90 a subamostragem de croma é desativada (4:4:4)."
        )
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(MIN_QUALITY, MAX_QUALITY)
        self.quality_spin.setFixedWidth(64)

        quality_row = QHBoxLayout()
        quality_row.setContentsMargins(0, 0, 0, 0)
        quality_row.addWidget(self.quality_slider, stretch=1)
        quality_row.addWidget(self.quality_spin)

        form = self._form()
        form.addRow("Formato:", self.format_combo)
        form.addRow("Qualidade JPEG:", quality_row)
        layout.addLayout(form)

    def _build_resolution(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._separator())
        layout.addWidget(self._section("Resolução"))

        self.keep_resolution_radio = QRadioButton("Manter resolução original")
        self.resize_radio = QRadioButton("Redimensionar")
        self.resolution_group = QButtonGroup(self)
        self.resolution_group.addButton(self.keep_resolution_radio)
        self.resolution_group.addButton(self.resize_radio)
        self.keep_resolution_radio.setChecked(True)

        self.width_spin = QSpinBox()
        self.height_spin = QSpinBox()
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(16, MAX_DIMENSION)
            spin.setSuffix(" px")
            spin.setSingleStep(100)
            spin.setMaximumWidth(140)

        layout.addWidget(self.keep_resolution_radio)
        layout.addWidget(self.resize_radio)

        form = self._form()
        form.addRow("Largura máxima:", self.width_spin)
        form.addRow("Altura máxima:", self.height_spin)
        layout.addLayout(form)

        hint = QLabel("A proporção é mantida; imagens menores não são ampliadas.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _build_development(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._separator())
        layout.addWidget(self._section("Revelação do RAW"))

        self.wb_combo = QComboBox()
        for mode in (WhiteBalance.CAMERA, WhiteBalance.AUTO, WhiteBalance.NEUTRAL):
            self.wb_combo.addItem(mode.label, mode)
        self.wb_combo.setToolTip(
            "Da câmera: usa os multiplicadores gravados no arquivo (padrão).\n"
            "Automático: o LibRaw calcula o balanço a partir da imagem.\n"
            "Neutro: sem correção — resulta em dominante de cor na maioria dos casos."
        )

        self.exposure_slider = QSlider(Qt.Orientation.Horizontal)
        self.exposure_slider.setRange(-2 * _EXPOSURE_STEPS_PER_EV, 2 * _EXPOSURE_STEPS_PER_EV)
        self.exposure_slider.setTickInterval(_EXPOSURE_STEPS_PER_EV)
        self.exposure_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.exposure_slider.setToolTip(
            "Correção de exposição aplicada pelo LibRaw antes da interpolação."
        )
        self.exposure_value = QLabel("0.0 EV")
        self.exposure_value.setMinimumWidth(56)
        self.exposure_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        exposure_row = QHBoxLayout()
        exposure_row.setContentsMargins(0, 0, 0, 0)
        exposure_row.addWidget(self.exposure_slider, stretch=1)
        exposure_row.addWidget(self.exposure_value)

        form = self._form()
        form.addRow("Balanço de branco:", self.wb_combo)
        form.addRow("Exposição:", exposure_row)
        layout.addLayout(form)

        self.auto_brightness_check = QCheckBox("Brilho automático")
        self.auto_brightness_check.setToolTip(
            "Ajuste automático de brilho do LibRaw.\n"
            "É desativado automaticamente quando há correção de exposição manual,\n"
            "pois os dois atuam sobre a mesma escala e se anulam."
        )
        layout.addWidget(self.auto_brightness_check)

    def _build_metadata(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._separator())
        layout.addWidget(self._section("Metadados"))

        self.exif_check = QCheckBox("Preservar EXIF")
        self.exif_check.setToolTip(
            "Copia data/hora, câmera, lente, ISO, abertura, velocidade e GPS para o JPEG."
        )
        layout.addWidget(self.exif_check)

    def _build_conflict(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._separator())
        layout.addWidget(self._section("Se o JPEG já existir"))

        self.overwrite_radio = QRadioButton(ConflictPolicy.OVERWRITE.label)
        self.skip_radio = QRadioButton(ConflictPolicy.SKIP.label)
        self.ask_radio = QRadioButton(ConflictPolicy.ASK.label)
        self.conflict_group = QButtonGroup(self)
        self._conflict_buttons = {
            ConflictPolicy.OVERWRITE: self.overwrite_radio,
            ConflictPolicy.SKIP: self.skip_radio,
            ConflictPolicy.ASK: self.ask_radio,
        }
        for button in self._conflict_buttons.values():
            self.conflict_group.addButton(button)
            layout.addWidget(button)
        self.skip_radio.setChecked(True)

    def _build_performance(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._separator())
        layout.addWidget(self._section("Desempenho"))

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, MAX_WORKERS)
        self.workers_spin.setMaximumWidth(80)
        self.workers_spin.setToolTip(
            "Arquivos revelados ao mesmo tempo.\n"
            "O LibRaw já usa vários núcleos internamente, então valores altos\n"
            "aumentam o consumo de memória sem ganho proporcional de velocidade."
        )
        form = self._form()
        form.addRow("Conversões simultâneas:", self.workers_spin)
        layout.addLayout(form)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    # -- sinais --------------------------------------------------------
    def _connect_signals(self) -> None:
        self.quality_slider.valueChanged.connect(self.quality_spin.setValue)
        self.quality_spin.valueChanged.connect(self.quality_slider.setValue)
        self.exposure_slider.valueChanged.connect(self._update_exposure_label)
        self.resize_radio.toggled.connect(self._update_resize_enabled)

        for widget_signal in (
            self.quality_spin.valueChanged,
            self.width_spin.valueChanged,
            self.height_spin.valueChanged,
            self.workers_spin.valueChanged,
            self.exposure_slider.valueChanged,
            self.wb_combo.currentIndexChanged,
            self.auto_brightness_check.toggled,
            self.exif_check.toggled,
            self.resize_radio.toggled,
            self.overwrite_radio.toggled,
            self.skip_radio.toggled,
            self.ask_radio.toggled,
        ):
            widget_signal.connect(self._emit_changed)

    def _emit_changed(self, *_args: object) -> None:
        if not self._loading:
            self.changed.emit()

    def _update_exposure_label(self, value: int) -> None:
        ev = value / _EXPOSURE_STEPS_PER_EV
        self.exposure_value.setText(f"{ev:+.1f} EV" if ev else "0.0 EV")

    def _update_resize_enabled(self, *_args: object) -> None:
        enabled = self.resize_radio.isChecked()
        self.width_spin.setEnabled(enabled)
        self.height_spin.setEnabled(enabled)

    # -- leitura/escrita ------------------------------------------------
    def settings(self) -> ConversionSettings:
        """Monta um :class:`ConversionSettings` a partir dos widgets."""
        policy = ConflictPolicy.SKIP
        for candidate, button in self._conflict_buttons.items():
            if button.isChecked():
                policy = candidate
                break

        return ConversionSettings(
            quality=self.quality_spin.value(),
            resize_enabled=self.resize_radio.isChecked(),
            max_width=self.width_spin.value(),
            max_height=self.height_spin.value(),
            white_balance=self.wb_combo.currentData() or WhiteBalance.CAMERA,
            exposure_ev=self.exposure_slider.value() / _EXPOSURE_STEPS_PER_EV,
            auto_brightness=self.auto_brightness_check.isChecked(),
            preserve_exif=self.exif_check.isChecked(),
            conflict_policy=policy,
            workers=self.workers_spin.value(),
        ).normalized()

    def apply(self, settings: ConversionSettings) -> None:
        """Carrega os valores nos widgets sem disparar :attr:`changed`."""
        settings = settings.normalized()
        self._loading = True
        try:
            self.quality_spin.setValue(settings.quality)
            self.quality_slider.setValue(settings.quality)
            self.width_spin.setValue(settings.max_width)
            self.height_spin.setValue(settings.max_height)
            self.resize_radio.setChecked(settings.resize_enabled)
            self.keep_resolution_radio.setChecked(not settings.resize_enabled)
            index = self.wb_combo.findData(settings.white_balance)
            self.wb_combo.setCurrentIndex(max(index, 0))
            self.exposure_slider.setValue(
                round(settings.exposure_ev * _EXPOSURE_STEPS_PER_EV)
            )
            self.auto_brightness_check.setChecked(settings.auto_brightness)
            self.exif_check.setChecked(settings.preserve_exif)
            self._conflict_buttons[settings.conflict_policy].setChecked(True)
            self.workers_spin.setValue(settings.workers)
        finally:
            self._loading = False
        self._update_exposure_label(self.exposure_slider.value())
        self._update_resize_enabled()
