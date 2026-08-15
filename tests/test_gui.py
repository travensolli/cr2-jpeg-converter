"""Testes da camada de interface que não dependem de interação visual.

Rodam com ``QT_QPA_PLATFORM=offscreen`` (definido no ``conftest.py``), então
funcionam em máquinas sem ambiente gráfico. O objetivo é pegar erros de import,
sinais mal conectados e regressões no modelo da lista — não validar pixels.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from cr2_converter.app.models import FileListModel
from cr2_converter.app.settings_panel import SettingsPanel
from cr2_converter.core.settings import ConversionSettings, SettingsStore
from cr2_converter.core.types import ConflictPolicy, FileStatus, WhiteBalance
from cr2_converter.utils.filesystem import SourceFile


class TestFileListModel:
    def test_comeca_vazio(self, qapp) -> None:
        modelo = FileListModel()

        assert modelo.rowCount() == 0
        assert modelo.is_empty()

    def test_adiciona_e_conta(self, qapp, make_cr2) -> None:
        modelo = FileListModel()

        adicionados, duplicados = modelo.add_sources(
            [SourceFile(make_cr2("a.CR2")), SourceFile(make_cr2("b.CR2"))]
        )

        assert (adicionados, duplicados) == (2, 0)
        assert modelo.rowCount() == 2

    def test_ignora_duplicatas(self, qapp, make_cr2) -> None:
        modelo = FileListModel()
        arquivo = make_cr2("a.CR2")
        modelo.add_sources([SourceFile(arquivo)])

        adicionados, duplicados = modelo.add_sources([SourceFile(arquivo)])

        assert (adicionados, duplicados) == (0, 1)
        assert modelo.rowCount() == 1

    def test_colunas_exibidas(self, qapp, make_cr2) -> None:
        from PySide6.QtCore import Qt

        modelo = FileListModel()
        arquivo = make_cr2("IMG_0001.CR2", size=25_690_112)
        modelo.add_sources([SourceFile(arquivo)])

        def _texto(coluna: int) -> str:
            return modelo.data(modelo.index(0, coluna), Qt.ItemDataRole.DisplayRole)

        assert _texto(FileListModel.COLUMN_NAME) == "IMG_0001.CR2"
        assert _texto(FileListModel.COLUMN_PATH) == str(arquivo.parent)
        assert _texto(FileListModel.COLUMN_SIZE) == "24.5 MB"
        assert _texto(FileListModel.COLUMN_STATUS) == "Aguardando"

    def test_atualiza_status(self, qapp, make_cr2) -> None:
        from PySide6.QtCore import Qt

        modelo = FileListModel()
        modelo.add_sources([SourceFile(make_cr2("a.CR2"))])

        modelo.set_status(0, FileStatus.ERROR, "arquivo corrompido")

        indice = modelo.index(0, FileListModel.COLUMN_STATUS)
        assert modelo.data(indice, Qt.ItemDataRole.DisplayRole) == "Erro"
        assert modelo.data(indice, Qt.ItemDataRole.ToolTipRole) == "arquivo corrompido"

    def test_status_fora_da_faixa_e_ignorado(self, qapp) -> None:
        FileListModel().set_status(99, FileStatus.CONVERTED)  # não deve levantar

    def test_reset_de_status(self, qapp, make_cr2) -> None:
        modelo = FileListModel()
        modelo.add_sources([SourceFile(make_cr2("a.CR2"))])
        modelo.set_status(0, FileStatus.CONVERTED)

        modelo.reset_statuses()

        assert modelo.entry_at(0).status is FileStatus.PENDING

    def test_remove_linhas(self, qapp, make_cr2) -> None:
        modelo = FileListModel()
        modelo.add_sources([SourceFile(make_cr2(f"{n}.CR2")) for n in "abc"])

        modelo.remove_rows([0, 2])

        assert modelo.rowCount() == 1
        assert modelo.entry_at(0).path.name == "b.CR2"

    def test_remocao_libera_o_caminho_para_readicao(self, qapp, make_cr2) -> None:
        modelo = FileListModel()
        arquivo = make_cr2("a.CR2")
        modelo.add_sources([SourceFile(arquivo)])
        modelo.remove_rows([0])

        adicionados, _ = modelo.add_sources([SourceFile(arquivo)])

        assert adicionados == 1

    def test_limpar(self, qapp, make_cr2) -> None:
        modelo = FileListModel()
        modelo.add_sources([SourceFile(make_cr2("a.CR2"))])

        modelo.clear()

        assert modelo.is_empty()


class TestSettingsPanel:
    def test_ida_e_volta(self, qapp) -> None:
        painel = SettingsPanel()
        original = ConversionSettings(
            quality=42,
            resize_enabled=True,
            max_width=2048,
            max_height=1536,
            white_balance=WhiteBalance.AUTO,
            exposure_ev=-1.5,
            auto_brightness=False,
            preserve_exif=False,
            conflict_policy=ConflictPolicy.ASK,
            workers=3,
        )

        painel.apply(original)

        # keep_structure vive na seção "Destino", não neste painel.
        assert painel.settings() == replace(original, keep_structure=False)

    def test_campos_de_tamanho_seguem_o_modo(self, qapp) -> None:
        painel = SettingsPanel()

        painel.apply(ConversionSettings(resize_enabled=False))
        assert painel.width_spin.isEnabled() is False

        painel.apply(ConversionSettings(resize_enabled=True))
        assert painel.width_spin.isEnabled() is True

    def test_rotulo_de_exposicao(self, qapp) -> None:
        painel = SettingsPanel()

        painel.apply(ConversionSettings(exposure_ev=1.5))

        assert painel.exposure_value.text() == "+1.5 EV"

    def test_apply_nao_dispara_changed(self, qapp) -> None:
        painel = SettingsPanel()
        disparos: list[int] = []
        painel.changed.connect(lambda: disparos.append(1))

        painel.apply(ConversionSettings(quality=30))

        assert disparos == []

    def test_alteracao_do_usuario_dispara_changed(self, qapp) -> None:
        painel = SettingsPanel()
        disparos: list[int] = []
        painel.changed.connect(lambda: disparos.append(1))

        painel.quality_spin.setValue(55)

        assert disparos


class TestResolucaoDeConflitos:
    """As políticas não interativas resolvem tudo sem abrir diálogo."""

    def _jobs(self, tmp_path: Path) -> list:
        from cr2_converter.core.planner import plan_jobs

        return plan_jobs(
            [SourceFile(tmp_path / "a.CR2"), SourceFile(tmp_path / "b.CR2")],
            tmp_path / "out",
        )

    def test_sem_conflitos_devolve_tudo_inalterado(self, qapp, tmp_path: Path) -> None:
        from cr2_converter.app.dialogs import resolve_conflicts

        jobs = self._jobs(tmp_path)

        resultado = resolve_conflicts(None, jobs, ConflictPolicy.ASK, [])

        assert resultado == jobs

    def test_politica_sobrescrever(self, qapp, tmp_path: Path) -> None:
        from cr2_converter.app.dialogs import resolve_conflicts

        jobs = self._jobs(tmp_path)

        resultado = resolve_conflicts(None, jobs, ConflictPolicy.OVERWRITE, [jobs[0]])

        assert all(job.overwrite for job in resultado)

    def test_politica_ignorar_mantem_overwrite_falso(self, qapp, tmp_path: Path) -> None:
        """O conversor devolve "Ignorado" sozinho quando overwrite=False."""
        from cr2_converter.app.dialogs import resolve_conflicts

        jobs = self._jobs(tmp_path)

        resultado = resolve_conflicts(None, jobs, ConflictPolicy.SKIP, [jobs[0]])

        assert not any(job.overwrite for job in resultado)


class TestReportDialog:
    def test_monta_a_tabela(self, qapp, tmp_path: Path) -> None:
        from cr2_converter.app.dialogs import ReportDialog
        from cr2_converter.core.types import ConversionJob, ConversionResult

        resultados = [
            ConversionResult(
                job=ConversionJob(tmp_path / "a.CR2", tmp_path / "a.jpg"),
                status=FileStatus.CONVERTED,
            ),
            ConversionResult(
                job=ConversionJob(tmp_path / "b.CR2", tmp_path / "b.jpg"),
                status=FileStatus.ERROR,
                message="arquivo corrompido",
            ),
        ]

        dialogo = ReportDialog(resultados)
        try:
            assert dialogo._table.rowCount() == 2
            assert dialogo._table.item(1, 1).text() == "Erro"
            assert dialogo._table.item(1, 2).text() == "arquivo corrompido"
        finally:
            dialogo.close()

    def test_relatorio_vazio_nao_quebra(self, qapp) -> None:
        from cr2_converter.app.dialogs import ReportDialog

        dialogo = ReportDialog([])
        try:
            assert dialogo._table.rowCount() == 0
        finally:
            dialogo.close()


class TestMainWindow:
    def test_janela_abre_e_fecha(self, qapp, tmp_path: Path) -> None:
        from cr2_converter.app.main_window import MainWindow

        janela = MainWindow(SettingsStore(tmp_path / "settings.json"))
        try:
            assert janela._model.is_empty()
            assert janela._convert_button.isEnabled() is False
            assert janela._cancel_button.isEnabled() is False
        finally:
            janela.close()

    def test_adicionar_arquivos_habilita_a_conversao(
        self, qapp, tmp_path: Path, make_cr2
    ) -> None:
        from cr2_converter.app.main_window import MainWindow

        janela = MainWindow(SettingsStore(tmp_path / "settings.json"))
        try:
            janela._add_paths([make_cr2("a.CR2"), make_cr2("b.CR2")])

            assert janela._model.rowCount() == 2
            assert janela._convert_button.isEnabled() is True
        finally:
            janela.close()

    def test_configuracoes_persistem_entre_sessoes(self, qapp, tmp_path: Path) -> None:
        from cr2_converter.app.main_window import MainWindow

        caminho = tmp_path / "settings.json"
        primeira = MainWindow(SettingsStore(caminho))
        try:
            primeira._settings_panel.quality_spin.setValue(37)
            primeira._keep_structure_check.setChecked(True)
            primeira._output_edit.setText(str(tmp_path / "saida"))
            primeira._save_settings()
        finally:
            primeira.close()

        segunda = MainWindow(SettingsStore(caminho))
        try:
            assert segunda._settings_panel.quality_spin.value() == 37
            assert segunda._keep_structure_check.isChecked() is True
            assert segunda._output_edit.text() == str(tmp_path / "saida")
        finally:
            segunda.close()

    def test_conversao_bloqueada_sem_arquivos(self, qapp, tmp_path: Path) -> None:
        """Sem arquivos na lista, o botão principal fica desabilitado.

        A validação da pasta de destino é testada em ``test_filesystem.py``:
        ela vive em ``prepare_output_dir`` justamente para poder ser verificada
        sem abrir um diálogo modal (que travaria a suíte sem laço de eventos).
        """
        from cr2_converter.app.main_window import MainWindow

        janela = MainWindow(SettingsStore(tmp_path / "settings.json"))
        try:
            janela._start_conversion()  # não deve fazer nada nem travar

            assert janela._model.is_empty()
            assert janela._cancel_button.isEnabled() is False
        finally:
            janela.close()
