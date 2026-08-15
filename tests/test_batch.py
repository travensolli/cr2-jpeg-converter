"""Testes da execução em lote e do cancelamento."""

from __future__ import annotations

import threading
from pathlib import Path

from fake_raw import FakeRaw, fake_opener

from cr2_converter.core.batch import BatchRunner
from cr2_converter.core.converter import Cr2Converter
from cr2_converter.core.settings import ConversionSettings
from cr2_converter.core.types import (
    ConversionJob,
    ConversionResult,
    FileFinished,
    FileStarted,
    FileStatus,
)


def _jobs(sources: list[Path], out: Path) -> list[ConversionJob]:
    return [
        ConversionJob(source=path, destination=out / f"{path.stem}.jpg", row=index)
        for index, path in enumerate(sources)
    ]


def _runner(jobs, settings, raws=None, default=None) -> BatchRunner:
    opener = fake_opener(raws=raws or {}, default=default or FakeRaw(60, 40))
    return BatchRunner(jobs, settings, converter=Cr2Converter(settings, raw_opener=opener))


def _drain(runner: BatchRunner) -> tuple[list[FileStarted], list[ConversionResult]]:
    started: list[FileStarted] = []
    results: list[ConversionResult] = []
    for event in runner.run():
        if isinstance(event, FileStarted):
            started.append(event)
        elif isinstance(event, FileFinished):
            results.append(event.result)
    return started, results


class TestExecucao:
    def test_converte_todos(self, tmp_path: Path, settings, make_cr2) -> None:
        origens = [make_cr2(f"IMG_{i}.CR2") for i in range(5)]
        jobs = _jobs(origens, tmp_path / "out")

        started, results = _drain(_runner(jobs, settings))

        assert len(started) == 5
        assert len(results) == 5
        assert all(r.status is FileStatus.CONVERTED for r in results)
        assert len(list((tmp_path / "out").glob("*.jpg"))) == 5

    def test_um_evento_de_fim_por_arquivo(self, tmp_path: Path, settings, make_cr2) -> None:
        origens = [make_cr2(f"IMG_{i}.CR2") for i in range(4)]

        _started, results = _drain(_runner(_jobs(origens, tmp_path / "out"), settings))

        assert sorted(r.row for r in results) == [0, 1, 2, 3]

    def test_lista_vazia_nao_emite_eventos(self, settings) -> None:
        started, results = _drain(_runner([], settings))

        assert started == []
        assert results == []

    def test_paralelismo_nao_perde_arquivos(self, tmp_path: Path, make_cr2) -> None:
        settings = ConversionSettings(workers=4, preserve_exif=False)
        origens = [make_cr2(f"IMG_{i:03d}.CR2") for i in range(20)]

        _started, results = _drain(_runner(_jobs(origens, tmp_path / "out"), settings))

        assert len(results) == 20
        assert {r.status for r in results} == {FileStatus.CONVERTED}

    def test_workers_limitado_ao_numero_de_arquivos(self, tmp_path: Path, make_cr2) -> None:
        settings = ConversionSettings(workers=8, preserve_exif=False)
        jobs = _jobs([make_cr2("IMG_0.CR2")], tmp_path / "out")

        _started, results = _drain(_runner(jobs, settings))

        assert len(results) == 1


class TestFalhas:
    def test_erro_em_um_arquivo_nao_para_o_lote(
        self, tmp_path: Path, settings, make_cr2
    ) -> None:
        origens = [make_cr2(f"IMG_{i}.CR2") for i in range(4)]
        raws = {origens[2]: FakeRaw(60, 40, postprocess_error=ValueError("corrompido"))}

        _started, results = _drain(
            _runner(_jobs(origens, tmp_path / "out"), settings, raws=raws)
        )

        por_linha = {r.row: r.status for r in results}
        assert por_linha[0] is FileStatus.CONVERTED
        assert por_linha[1] is FileStatus.CONVERTED
        assert por_linha[2] is FileStatus.ERROR
        assert por_linha[3] is FileStatus.CONVERTED

    def test_conversor_que_explode_ainda_gera_evento_de_fim(
        self, tmp_path: Path, settings, make_cr2
    ) -> None:
        """Sem essa garantia o consumidor esperaria para sempre."""

        class ConversorQuebrado(Cr2Converter):
            def convert(self, job, cancel_event=None):
                raise RuntimeError("falha inesperada")

        jobs = _jobs([make_cr2("a.CR2"), make_cr2("b.CR2")], tmp_path / "out")
        runner = BatchRunner(jobs, settings, converter=ConversorQuebrado(settings))

        _started, results = _drain(runner)

        assert len(results) == 2
        assert all(r.status is FileStatus.ERROR for r in results)

    def test_arquivos_ja_existentes_sao_ignorados(
        self, tmp_path: Path, settings, make_cr2
    ) -> None:
        saida = tmp_path / "out"
        saida.mkdir()
        (saida / "IMG_1.jpg").write_bytes(b"antigo")
        origens = [make_cr2(f"IMG_{i}.CR2") for i in range(3)]

        _started, results = _drain(_runner(_jobs(origens, saida), settings))

        por_linha = {r.row: r.status for r in results}
        assert por_linha[1] is FileStatus.SKIPPED
        assert (saida / "IMG_1.jpg").read_bytes() == b"antigo"


class TestCancelamento:
    def test_cancelar_antes_de_iniciar(self, tmp_path: Path, settings, make_cr2) -> None:
        origens = [make_cr2(f"IMG_{i}.CR2") for i in range(5)]
        runner = _runner(_jobs(origens, tmp_path / "out"), settings)
        runner.cancel()

        started, results = _drain(runner)

        assert started == []
        assert len(results) == 5
        assert all(r.status is FileStatus.CANCELLED for r in results)
        assert list((tmp_path / "out").glob("*.jpg")) == []

    def test_cancelar_no_meio_encerra_o_restante(
        self, tmp_path: Path, settings, make_cr2
    ) -> None:
        origens = [make_cr2(f"IMG_{i:02d}.CR2") for i in range(12)]
        runner = _runner(_jobs(origens, tmp_path / "out"), settings)

        results: list[ConversionResult] = []
        for event in runner.run():
            if isinstance(event, FileFinished):
                results.append(event.result)
                if len(results) == 3:
                    runner.cancel()

        # Todo arquivo produz exatamente um resultado, mesmo cancelado.
        assert len(results) == 12
        assert any(r.status is FileStatus.CONVERTED for r in results)
        assert any(r.status is FileStatus.CANCELLED for r in results)

    def test_cancelamento_nao_deixa_temporarios(
        self, tmp_path: Path, settings, make_cr2
    ) -> None:
        origens = [make_cr2(f"IMG_{i:02d}.CR2") for i in range(10)]
        runner = _runner(_jobs(origens, tmp_path / "out"), settings)

        for index, _event in enumerate(runner.run()):
            if index == 2:
                runner.cancel()

        assert list(tmp_path.rglob("*.tmp")) == []

    def test_abandonar_o_gerador_encerra_as_threads(
        self, tmp_path: Path, settings, make_cr2
    ) -> None:
        """Fechar a janela no meio não pode deixar threads órfãs."""
        origens = [make_cr2(f"IMG_{i:02d}.CR2") for i in range(20)]
        runner = _runner(_jobs(origens, tmp_path / "out"), settings)

        gerador = runner.run()
        next(gerador)
        gerador.close()  # dispara o finally do gerador

        assert runner.is_cancelled is True
        assert threading.active_count() < 20
