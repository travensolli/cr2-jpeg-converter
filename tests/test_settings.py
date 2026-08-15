"""Testes das configurações, da persistência e do mapeamento para o LibRaw."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cr2_converter.core.settings import (
    MAX_QUALITY,
    MAX_WORKERS,
    AppSettings,
    ConversionSettings,
    SettingsStore,
    default_worker_count,
    postprocess_kwargs,
)
from cr2_converter.core.types import ConflictPolicy, WhiteBalance


class TestPadroes:
    def test_valores_padrao_do_enunciado(self) -> None:
        settings = ConversionSettings()

        assert settings.quality == 95
        assert settings.resize_enabled is False
        assert settings.white_balance is WhiteBalance.CAMERA
        assert settings.exposure_ev == 0.0
        assert settings.preserve_exif is True
        assert settings.conflict_policy is ConflictPolicy.SKIP

    def test_workers_padrao_e_conservador(self) -> None:
        assert 1 <= default_worker_count() <= 4


class TestNormalizacao:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [(0, 1), (-10, 1), (101, MAX_QUALITY), (500, MAX_QUALITY), (95, 95)],
    )
    def test_qualidade_limitada(self, entrada: int, esperado: int) -> None:
        assert ConversionSettings(quality=entrada).normalized().quality == esperado

    @pytest.mark.parametrize(
        ("entrada", "esperado"), [(-9.0, -2.0), (9.0, 2.0), (1.5, 1.5)]
    )
    def test_exposicao_limitada(self, entrada: float, esperado: float) -> None:
        assert ConversionSettings(exposure_ev=entrada).normalized().exposure_ev == esperado

    def test_workers_limitado(self) -> None:
        assert ConversionSettings(workers=99).normalized().workers == MAX_WORKERS
        assert ConversionSettings(workers=0).normalized().workers == 1

    def test_dimensoes_limitadas(self) -> None:
        normalizado = ConversionSettings(max_width=0, max_height=10**9).normalized()

        assert normalizado.max_width == 16
        assert normalizado.max_height == 65_500


class TestSerializacao:
    def test_ida_e_volta(self) -> None:
        original = ConversionSettings(
            quality=72,
            resize_enabled=True,
            max_width=2000,
            max_height=1500,
            white_balance=WhiteBalance.AUTO,
            exposure_ev=-1.5,
            auto_brightness=False,
            preserve_exif=False,
            keep_structure=True,
            conflict_policy=ConflictPolicy.ASK,
            workers=3,
        )

        assert ConversionSettings.from_dict(original.to_dict()) == original

    def test_dicionario_e_serializavel_em_json(self) -> None:
        json.dumps(ConversionSettings().to_dict())

    def test_campos_invalidos_sao_ignorados(self) -> None:
        settings = ConversionSettings.from_dict(
            {"quality": "abc", "white_balance": "inexistente", "desconhecido": 1}
        )

        assert settings.quality == 95
        assert settings.white_balance is WhiteBalance.CAMERA

    def test_dicionario_vazio_devolve_padroes(self) -> None:
        assert ConversionSettings.from_dict({}) == ConversionSettings()


class TestSettingsStore:
    def test_arquivo_inexistente_devolve_padroes(self, tmp_path: Path) -> None:
        store = SettingsStore(tmp_path / "nao_existe.json")

        assert store.load() == AppSettings()

    def test_grava_e_le(self, tmp_path: Path) -> None:
        store = SettingsStore(tmp_path / "cfg" / "settings.json")
        original = AppSettings(
            conversion=ConversionSettings(quality=60),
            output_dir=str(tmp_path / "saida"),
        )

        assert store.save(original) is True
        assert store.load() == original

    def test_arquivo_corrompido_nao_derruba(self, tmp_path: Path) -> None:
        caminho = tmp_path / "settings.json"
        caminho.write_text("{isto não é json", encoding="utf-8")

        assert SettingsStore(caminho).load() == AppSettings()

    def test_nao_deixa_temporario(self, tmp_path: Path) -> None:
        caminho = tmp_path / "settings.json"
        SettingsStore(caminho).save(AppSettings())

        assert list(tmp_path.glob("*.tmp")) == []


class TestPostprocessKwargs:
    def test_balanco_da_camera(self) -> None:
        kwargs = postprocess_kwargs(ConversionSettings(white_balance=WhiteBalance.CAMERA))

        assert kwargs["use_camera_wb"] is True
        assert kwargs["use_auto_wb"] is False

    def test_balanco_automatico(self) -> None:
        kwargs = postprocess_kwargs(ConversionSettings(white_balance=WhiteBalance.AUTO))

        assert kwargs["use_camera_wb"] is False
        assert kwargs["use_auto_wb"] is True

    def test_balanco_neutro(self) -> None:
        kwargs = postprocess_kwargs(ConversionSettings(white_balance=WhiteBalance.NEUTRAL))

        assert kwargs["use_camera_wb"] is False
        assert kwargs["use_auto_wb"] is False

    def test_saida_sempre_8_bits(self) -> None:
        assert postprocess_kwargs(ConversionSettings())["output_bps"] == 8

    def test_sem_exposicao_nao_envia_exp_shift(self) -> None:
        assert "exp_shift" not in postprocess_kwargs(ConversionSettings(exposure_ev=0.0))

    @pytest.mark.parametrize(
        ("ev", "esperado"), [(1.0, 2.0), (2.0, 4.0), (-1.0, 0.5), (-2.0, 0.25)]
    )
    def test_exposicao_convertida_para_escala_linear(self, ev: float, esperado: float) -> None:
        """O LibRaw usa escala linear (2**EV), não EV."""
        assert postprocess_kwargs(ConversionSettings(exposure_ev=ev))["exp_shift"] == esperado

    def test_exp_shift_dentro_da_faixa_do_libraw(self) -> None:
        for ev in (-2.0, -1.0, 0.5, 2.0):
            valor = postprocess_kwargs(ConversionSettings(exposure_ev=ev))["exp_shift"]
            assert 0.25 <= valor <= 8.0

    def test_exposicao_desliga_brilho_automatico(self) -> None:
        """Auto-bright normaliza o histograma e anularia o ajuste manual."""
        kwargs = postprocess_kwargs(
            ConversionSettings(exposure_ev=1.0, auto_brightness=True)
        )

        assert kwargs["no_auto_bright"] is True

    def test_brilho_automatico_respeitado_sem_exposicao(self) -> None:
        ligado = postprocess_kwargs(ConversionSettings(auto_brightness=True))
        desligado = postprocess_kwargs(ConversionSettings(auto_brightness=False))

        assert ligado["no_auto_bright"] is False
        assert desligado["no_auto_bright"] is True
