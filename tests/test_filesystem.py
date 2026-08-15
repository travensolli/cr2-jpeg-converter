"""Testes de descoberta de arquivos e utilitários de caminho."""

from __future__ import annotations

from pathlib import Path

from cr2_converter.utils.filesystem import (
    collect_sources,
    human_size,
    is_cr2,
    iter_cr2_files,
    path_key,
    prepare_output_dir,
    unique_path,
)


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestDiscovery:
    def test_encontra_maiusculas_e_minusculas(self, tmp_path: Path) -> None:
        _touch(tmp_path / "A.CR2")
        _touch(tmp_path / "b.cr2")
        _touch(tmp_path / "c.Cr2")

        found = list(iter_cr2_files(tmp_path))

        assert sorted(p.name for p in found) == ["A.CR2", "b.cr2", "c.Cr2"]

    def test_nao_duplica_no_windows(self, tmp_path: Path) -> None:
        """No Windows o glob é case-insensitive; a varredura não pode duplicar."""
        _touch(tmp_path / "IMG_0001.CR2")

        found = list(iter_cr2_files(tmp_path))

        assert len(found) == 1

    def test_ignora_outras_extensoes(self, tmp_path: Path) -> None:
        _touch(tmp_path / "foto.jpg")
        _touch(tmp_path / "foto.nef")
        _touch(tmp_path / "foto.cr3")
        _touch(tmp_path / "certo.CR2")

        assert [p.name for p in iter_cr2_files(tmp_path)] == ["certo.CR2"]

    def test_recursivo_por_padrao(self, tmp_path: Path) -> None:
        _touch(tmp_path / "raiz.CR2")
        _touch(tmp_path / "Casamento" / "a.CR2")
        _touch(tmp_path / "Casamento" / "Detalhes" / "b.CR2")

        assert len(list(iter_cr2_files(tmp_path))) == 3

    def test_nao_recursivo(self, tmp_path: Path) -> None:
        _touch(tmp_path / "raiz.CR2")
        _touch(tmp_path / "sub" / "a.CR2")

        found = list(iter_cr2_files(tmp_path, recursive=False))

        assert [p.name for p in found] == ["raiz.CR2"]

    def test_ordem_deterministica(self, tmp_path: Path) -> None:
        for name in ("c.CR2", "a.CR2", "b.CR2"):
            _touch(tmp_path / name)

        assert [p.name for p in iter_cr2_files(tmp_path)] == ["a.CR2", "b.CR2", "c.CR2"]

    def test_pasta_vazia(self, tmp_path: Path) -> None:
        assert list(iter_cr2_files(tmp_path)) == []


class TestCollectSources:
    def test_pasta_define_raiz(self, tmp_path: Path) -> None:
        _touch(tmp_path / "Casamento" / "a.CR2")

        sources = collect_sources([tmp_path])

        assert len(sources) == 1
        assert sources[0].root == tmp_path

    def test_arquivo_solto_nao_tem_raiz(self, tmp_path: Path) -> None:
        arquivo = _touch(tmp_path / "a.CR2")

        sources = collect_sources([arquivo])

        assert sources[0].root is None

    def test_remove_duplicatas(self, tmp_path: Path) -> None:
        arquivo = _touch(tmp_path / "a.CR2")

        sources = collect_sources([arquivo, tmp_path, arquivo])

        assert len(sources) == 1

    def test_ignora_caminho_inexistente(self, tmp_path: Path) -> None:
        assert collect_sources([tmp_path / "nao_existe"]) == []

    def test_ignora_arquivo_nao_cr2(self, tmp_path: Path) -> None:
        arquivo = _touch(tmp_path / "foto.jpg")

        assert collect_sources([arquivo]) == []


class TestHelpers:
    def test_is_cr2(self) -> None:
        assert is_cr2("a.CR2")
        assert is_cr2("a.cr2")
        assert not is_cr2("a.jpg")

    def test_human_size(self) -> None:
        assert human_size(0) == "0 B"
        assert human_size(512) == "512 B"
        assert human_size(1024) == "1.0 KB"
        assert human_size(25_690_112) == "24.5 MB"

    def test_path_key_ignora_caixa_no_windows(self, tmp_path: Path) -> None:
        import os

        a = tmp_path / "Foto.CR2"
        b = tmp_path / "foto.cr2"
        if os.name == "nt":
            assert path_key(a) == path_key(b)
        else:
            assert path_key(a) != path_key(b)

    def test_unique_path_livre(self, tmp_path: Path) -> None:
        destino = tmp_path / "a.jpg"

        assert unique_path(destino) == destino

    def test_unique_path_com_arquivo_existente(self, tmp_path: Path) -> None:
        destino = _touch(tmp_path / "a.jpg")

        assert unique_path(destino).name == "a (1).jpg"

    def test_unique_path_ignora_disco_quando_pedido(self, tmp_path: Path) -> None:
        destino = _touch(tmp_path / "a.jpg")

        assert unique_path(destino, check_disk=False) == destino

    def test_unique_path_respeita_reservados(self, tmp_path: Path) -> None:
        destino = tmp_path / "a.jpg"
        reservados = {path_key(destino), path_key(tmp_path / "a (1).jpg")}

        assert unique_path(destino, reservados, check_disk=False).name == "a (2).jpg"


class TestPrepareOutputDir:
    def test_texto_vazio_e_recusado(self) -> None:
        pasta, erro = prepare_output_dir("")

        assert pasta is None
        assert "Selecione a pasta" in erro

    def test_apenas_espacos_e_recusado(self) -> None:
        assert prepare_output_dir("   ")[0] is None

    def test_cria_pasta_inexistente(self, tmp_path: Path) -> None:
        destino = tmp_path / "nova" / "subpasta"

        pasta, erro = prepare_output_dir(str(destino))

        assert pasta == destino
        assert erro == ""
        assert destino.is_dir()

    def test_aceita_pasta_existente(self, tmp_path: Path) -> None:
        assert prepare_output_dir(str(tmp_path)) == (tmp_path, "")

    def test_remove_aspas_do_caminho_colado(self, tmp_path: Path) -> None:
        """Copiar caminho no Explorer do Windows inclui aspas."""
        pasta, _erro = prepare_output_dir(f'"{tmp_path}"')

        assert pasta == tmp_path

    def test_caminho_bloqueado_por_arquivo(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "sou_um_arquivo"
        arquivo.write_bytes(b"x")

        pasta, erro = prepare_output_dir(str(arquivo / "sub"))

        assert pasta is None
        assert erro
