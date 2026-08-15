"""Testes do planejamento origem → destino."""

from __future__ import annotations

from pathlib import Path

from cr2_converter.core.planner import (
    destination_for,
    existing_destinations,
    jpeg_name,
    plan_jobs,
)
from cr2_converter.utils.filesystem import SourceFile


class TestNomeDeSaida:
    def test_troca_extensao_para_jpg(self) -> None:
        assert jpeg_name(Path("IMG_0001.CR2")) == "IMG_0001.jpg"

    def test_extensao_minuscula_tambem(self) -> None:
        assert jpeg_name(Path("IMG_0001.cr2")) == "IMG_0001.jpg"

    def test_preserva_pontos_no_nome(self) -> None:
        assert jpeg_name(Path("ensaio.final.v2.CR2")) == "ensaio.final.v2.jpg"


class TestDestino:
    def test_saida_plana(self, tmp_path: Path) -> None:
        origem = tmp_path / "Casamento" / "IMG_001.CR2"

        destino = destination_for(origem, tmp_path, tmp_path / "out", keep_structure=False)

        assert destino == tmp_path / "out" / "IMG_001.jpg"

    def test_preserva_estrutura(self, tmp_path: Path) -> None:
        origem = tmp_path / "Casamento" / "IMG_001.CR2"

        destino = destination_for(origem, tmp_path, tmp_path / "out", keep_structure=True)

        assert destino == tmp_path / "out" / "Casamento" / "IMG_001.jpg"

    def test_estrutura_aninhada(self, tmp_path: Path) -> None:
        origem = tmp_path / "2024" / "Casamento" / "Detalhes" / "IMG_001.CR2"

        destino = destination_for(origem, tmp_path, tmp_path / "out", keep_structure=True)

        assert destino == tmp_path / "out" / "2024" / "Casamento" / "Detalhes" / "IMG_001.jpg"

    def test_arquivo_na_propria_raiz(self, tmp_path: Path) -> None:
        origem = tmp_path / "IMG_001.CR2"

        destino = destination_for(origem, tmp_path, tmp_path / "out", keep_structure=True)

        assert destino == tmp_path / "out" / "IMG_001.jpg"

    def test_sem_raiz_vai_para_saida_direta(self, tmp_path: Path) -> None:
        origem = tmp_path / "Casamento" / "IMG_001.CR2"

        destino = destination_for(origem, None, tmp_path / "out", keep_structure=True)

        assert destino == tmp_path / "out" / "IMG_001.jpg"

    def test_origem_fora_da_raiz_nao_quebra(self, tmp_path: Path) -> None:
        origem = tmp_path / "outra" / "IMG_001.CR2"

        destino = destination_for(
            origem, tmp_path / "raiz", tmp_path / "out", keep_structure=True
        )

        assert destino == tmp_path / "out" / "IMG_001.jpg"


class TestPlanJobs:
    def test_estrutura_do_enunciado(self, tmp_path: Path) -> None:
        """Entrada/{Casamento,Festa} → Saída/{Casamento,Festa}."""
        entrada = tmp_path / "Entrada"
        itens = [
            SourceFile(entrada / "Casamento" / "IMG_001.CR2", entrada),
            SourceFile(entrada / "Casamento" / "IMG_002.CR2", entrada),
            SourceFile(entrada / "Festa" / "IMG_003.CR2", entrada),
            SourceFile(entrada / "Festa" / "IMG_004.CR2", entrada),
        ]
        saida = tmp_path / "Saida"

        jobs = plan_jobs(itens, saida, keep_structure=True)

        assert [job.destination.relative_to(saida).as_posix() for job in jobs] == [
            "Casamento/IMG_001.jpg",
            "Casamento/IMG_002.jpg",
            "Festa/IMG_003.jpg",
            "Festa/IMG_004.jpg",
        ]

    def test_colisao_no_lote_recebe_sufixo(self, tmp_path: Path) -> None:
        """Sem manter estrutura, nomes iguais de pastas diferentes colidiriam."""
        entrada = tmp_path / "Entrada"
        itens = [
            SourceFile(entrada / "Casamento" / "IMG_001.CR2", entrada),
            SourceFile(entrada / "Festa" / "IMG_001.CR2", entrada),
            SourceFile(entrada / "Aniversario" / "IMG_001.CR2", entrada),
        ]

        jobs = plan_jobs(itens, tmp_path / "out", keep_structure=False)

        assert [job.destination.name for job in jobs] == [
            "IMG_001.jpg",
            "IMG_001 (1).jpg",
            "IMG_001 (2).jpg",
        ]

    def test_sem_colisao_quando_estrutura_preservada(self, tmp_path: Path) -> None:
        entrada = tmp_path / "Entrada"
        itens = [
            SourceFile(entrada / "Casamento" / "IMG_001.CR2", entrada),
            SourceFile(entrada / "Festa" / "IMG_001.CR2", entrada),
        ]

        jobs = plan_jobs(itens, tmp_path / "out", keep_structure=True)

        assert [job.destination.name for job in jobs] == ["IMG_001.jpg", "IMG_001.jpg"]

    def test_arquivo_existente_nao_e_renomeado(self, tmp_path: Path) -> None:
        """Arquivo já em disco é decidido pela política de conflito, não aqui."""
        saida = tmp_path / "out"
        saida.mkdir()
        (saida / "IMG_001.jpg").write_bytes(b"antigo")
        itens = [SourceFile(tmp_path / "IMG_001.CR2", None)]

        jobs = plan_jobs(itens, saida)

        assert jobs[0].destination.name == "IMG_001.jpg"

    def test_propaga_linhas_da_interface(self, tmp_path: Path) -> None:
        itens = [
            SourceFile(tmp_path / "a.CR2", None),
            SourceFile(tmp_path / "b.CR2", None),
        ]

        jobs = plan_jobs(itens, tmp_path / "out", rows=[7, 9])

        assert [job.row for job in jobs] == [7, 9]

    def test_overwrite_propagado(self, tmp_path: Path) -> None:
        itens = [SourceFile(tmp_path / "a.CR2", None)]

        jobs = plan_jobs(itens, tmp_path / "out", overwrite=True)

        assert jobs[0].overwrite is True

    def test_lista_vazia(self, tmp_path: Path) -> None:
        assert plan_jobs([], tmp_path / "out") == []


class TestExistingDestinations:
    def test_detecta_existentes(self, tmp_path: Path) -> None:
        saida = tmp_path / "out"
        saida.mkdir()
        (saida / "a.jpg").write_bytes(b"x")
        itens = [
            SourceFile(tmp_path / "a.CR2", None),
            SourceFile(tmp_path / "b.CR2", None),
        ]
        jobs = plan_jobs(itens, saida)

        conflitos = existing_destinations(jobs)

        assert [job.destination.name for job in conflitos] == ["a.jpg"]

    def test_nenhum_conflito(self, tmp_path: Path) -> None:
        jobs = plan_jobs([SourceFile(tmp_path / "a.CR2", None)], tmp_path / "out")

        assert existing_destinations(jobs) == []
