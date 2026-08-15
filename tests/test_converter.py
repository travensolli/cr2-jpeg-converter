"""Testes da conversão de um arquivo.

Os pixels vêm do :mod:`tests.fake_raw`, mas todo o resto do caminho é o código
real: PIL, redimensionamento, gravação atômica, cópia de EXIF e limpeza de
temporários.
"""

from __future__ import annotations

import threading
from pathlib import Path

import piexif
import pytest
from fake_raw import FakeRaw, fake_opener
from PIL import Image

from cr2_converter.core.converter import Cr2Converter, describe_exception
from cr2_converter.core.settings import ConversionSettings
from cr2_converter.core.types import ConversionJob, FileStatus


def _job(source: Path, destination: Path, overwrite: bool = False) -> ConversionJob:
    return ConversionJob(source=source, destination=destination, overwrite=overwrite)


def _converter(settings: ConversionSettings, raw: FakeRaw | None = None) -> Cr2Converter:
    return Cr2Converter(settings, raw_opener=fake_opener(default=raw or FakeRaw(120, 90)))


def _sem_temporarios(directory: Path) -> bool:
    return not list(directory.rglob("*.tmp"))


class TestConversaoBasica:
    def test_gera_jpeg_valido(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        destino = tmp_path / "out" / "IMG_0001.jpg"

        resultado = _converter(settings).convert(_job(origem, destino))

        assert resultado.status is FileStatus.CONVERTED
        assert destino.is_file()
        with Image.open(destino) as imagem:
            imagem.load()
            assert imagem.format == "JPEG"
            assert imagem.size == (120, 90)

    def test_cria_pasta_de_destino(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        destino = tmp_path / "a" / "b" / "c" / "IMG_0001.jpg"

        resultado = _converter(settings).convert(_job(origem, destino))

        assert resultado.status is FileStatus.CONVERTED
        assert destino.parent.is_dir()

    def test_mede_duracao(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")

        resultado = _converter(settings).convert(_job(origem, tmp_path / "a.jpg"))

        assert resultado.duration_s >= 0

    def test_nao_deixa_temporarios(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")

        _converter(settings).convert(_job(origem, tmp_path / "out" / "a.jpg"))

        assert _sem_temporarios(tmp_path)

    def test_fecha_o_arquivo_raw(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        raw = FakeRaw(60, 40)

        _converter(settings, raw).convert(_job(origem, tmp_path / "a.jpg"))

        assert raw.closed is True


class TestQualidade:
    @pytest.mark.parametrize("qualidade", [1, 50, 89, 90, 94, 95, 100])
    def test_grava_em_qualquer_qualidade(
        self, tmp_path: Path, make_cr2, qualidade: int
    ) -> None:
        """Regressão: imagens ruidosas (ISO alto) travavam a gravação.

        Com ``optimize=True``, o buffer que o Pillow reserva (largura × altura)
        era menor que o JPEG gerado em qualidade 90–94 com croma 4:4:4, e a
        gravação falhava com ``broken data stream``.
        """
        origem = make_cr2("IMG_0001.CR2")
        destino = tmp_path / f"q{qualidade}.jpg"
        settings = ConversionSettings(quality=qualidade, preserve_exif=False)

        resultado = Cr2Converter(
            settings, raw_opener=fake_opener(default=FakeRaw(400, 300))
        ).convert(_job(origem, destino))

        assert resultado.status is FileStatus.CONVERTED, resultado.message
        with Image.open(destino) as imagem:
            imagem.load()

    def test_qualidade_afeta_o_tamanho(self, tmp_path: Path, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        raw = FakeRaw(240, 180)

        tamanhos = {}
        for qualidade in (20, 95):
            destino = tmp_path / f"q{qualidade}.jpg"
            settings = ConversionSettings(quality=qualidade, preserve_exif=False)
            Cr2Converter(settings, raw_opener=fake_opener(default=raw)).convert(
                _job(origem, destino)
            )
            tamanhos[qualidade] = destino.stat().st_size

        assert tamanhos[20] < tamanhos[95]


class TestRedimensionamento:
    def test_reduz_mantendo_proporcao(self, tmp_path: Path, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        settings = ConversionSettings(
            resize_enabled=True, max_width=400, max_height=400, preserve_exif=False
        )

        Cr2Converter(
            settings, raw_opener=fake_opener(default=FakeRaw(800, 600))
        ).convert(_job(origem, tmp_path / "a.jpg"))

        with Image.open(tmp_path / "a.jpg") as imagem:
            assert imagem.size == (400, 300)

    def test_nao_amplia_imagens_menores(self, tmp_path: Path, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        settings = ConversionSettings(
            resize_enabled=True, max_width=4000, max_height=4000, preserve_exif=False
        )

        Cr2Converter(
            settings, raw_opener=fake_opener(default=FakeRaw(100, 80))
        ).convert(_job(origem, tmp_path / "a.jpg"))

        with Image.open(tmp_path / "a.jpg") as imagem:
            assert imagem.size == (100, 80)

    def test_desligado_mantem_resolucao(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")

        _converter(settings, FakeRaw(300, 200)).convert(_job(origem, tmp_path / "a.jpg"))

        with Image.open(tmp_path / "a.jpg") as imagem:
            assert imagem.size == (300, 200)


class TestParametrosDoLibRaw:
    def test_repassa_configuracoes_para_o_postprocess(
        self, tmp_path: Path, make_cr2
    ) -> None:
        origem = make_cr2("IMG_0001.CR2")
        raw = FakeRaw(60, 40)
        settings = ConversionSettings(exposure_ev=1.0, preserve_exif=False)

        Cr2Converter(settings, raw_opener=fake_opener(default=raw)).convert(
            _job(origem, tmp_path / "a.jpg")
        )

        assert len(raw.postprocess_calls) == 1
        kwargs = raw.postprocess_calls[0]
        assert kwargs["use_camera_wb"] is True
        assert kwargs["output_bps"] == 8
        assert kwargs["exp_shift"] == 2.0
        assert kwargs["no_auto_bright"] is True


class TestArquivoExistente:
    def test_ignora_quando_ja_existe(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        destino = tmp_path / "a.jpg"
        destino.write_bytes(b"conteudo antigo")

        resultado = _converter(settings).convert(_job(origem, destino))

        assert resultado.status is FileStatus.SKIPPED
        assert destino.read_bytes() == b"conteudo antigo"

    def test_sobrescreve_quando_autorizado(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        destino = tmp_path / "a.jpg"
        destino.write_bytes(b"conteudo antigo")

        resultado = _converter(settings).convert(_job(origem, destino, overwrite=True))

        assert resultado.status is FileStatus.CONVERTED
        assert destino.read_bytes() != b"conteudo antigo"

    def test_destino_criado_durante_a_conversao_nao_e_sobrescrito(
        self, tmp_path: Path, settings, make_cr2
    ) -> None:
        """Fecha a janela entre a verificação inicial e a gravação final."""
        origem = make_cr2("IMG_0001.CR2")
        destino = tmp_path / "a.jpg"

        class RawQueCriaODestino(FakeRaw):
            def postprocess(self, **kwargs):
                destino.write_bytes(b"criado por outro programa")
                return super().postprocess(**kwargs)

        resultado = _converter(settings, RawQueCriaODestino(60, 40)).convert(
            _job(origem, destino)
        )

        assert resultado.status is FileStatus.SKIPPED
        assert destino.read_bytes() == b"criado por outro programa"
        assert _sem_temporarios(tmp_path)


class TestErros:
    def test_origem_inexistente(self, tmp_path: Path, settings) -> None:
        resultado = _converter(settings).convert(
            _job(tmp_path / "nao_existe.CR2", tmp_path / "a.jpg")
        )

        assert resultado.status is FileStatus.ERROR
        assert "não encontrado" in resultado.message

    def test_falha_ao_abrir_o_raw(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        opener = fake_opener(open_error=OSError("arquivo corrompido"))

        resultado = Cr2Converter(settings, raw_opener=opener).convert(
            _job(origem, tmp_path / "out" / "a.jpg")
        )

        assert resultado.status is FileStatus.ERROR
        assert not (tmp_path / "out" / "a.jpg").exists()
        assert _sem_temporarios(tmp_path)

    def test_falha_na_revelacao(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        raw = FakeRaw(60, 40, postprocess_error=MemoryError())

        resultado = _converter(settings, raw).convert(_job(origem, tmp_path / "out" / "a.jpg"))

        assert resultado.status is FileStatus.ERROR
        assert "memória" in resultado.message
        assert _sem_temporarios(tmp_path)

    def test_destino_impossivel(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        bloqueio = tmp_path / "bloqueio"
        bloqueio.write_bytes(b"sou um arquivo, nao uma pasta")

        resultado = _converter(settings).convert(_job(origem, bloqueio / "a.jpg"))

        assert resultado.status is FileStatus.ERROR

    def test_um_erro_nao_impede_o_proximo(self, tmp_path: Path, settings, make_cr2) -> None:
        bom = make_cr2("bom.CR2")
        ruim = make_cr2("ruim.CR2")
        raws = {ruim: FakeRaw(60, 40, postprocess_error=ValueError("corrompido"))}
        opener = fake_opener(raws=raws, default=FakeRaw(60, 40))
        conversor = Cr2Converter(settings, raw_opener=opener)

        r1 = conversor.convert(_job(ruim, tmp_path / "out" / "ruim.jpg"))
        r2 = conversor.convert(_job(bom, tmp_path / "out" / "bom.jpg"))

        assert r1.status is FileStatus.ERROR
        assert r2.status is FileStatus.CONVERTED


class TestCancelamento:
    def test_cancelado_antes_de_comecar(self, tmp_path: Path, settings, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")
        evento = threading.Event()
        evento.set()

        resultado = _converter(settings).convert(_job(origem, tmp_path / "a.jpg"), evento)

        assert resultado.status is FileStatus.CANCELLED
        assert not (tmp_path / "a.jpg").exists()

    def test_cancelado_durante_a_revelacao(self, tmp_path: Path, settings, make_cr2) -> None:
        """Cancelar antes da gravação não pode deixar arquivo pela metade."""
        origem = make_cr2("IMG_0001.CR2")
        evento = threading.Event()

        class RawQueCancela(FakeRaw):
            def postprocess(self, **kwargs):
                evento.set()
                return super().postprocess(**kwargs)

        resultado = _converter(settings, RawQueCancela(60, 40)).convert(
            _job(origem, tmp_path / "a.jpg"), evento
        )

        assert resultado.status is FileStatus.CANCELLED
        assert not (tmp_path / "a.jpg").exists()
        assert _sem_temporarios(tmp_path)


class TestExif:
    def _origem_com_exif(self, path: Path) -> Path:
        """Um JPEG com EXIF faz as vezes do CR2: o abridor de RAW é falso."""
        Image.new("RGB", (32, 24), (10, 20, 30)).save(path, "JPEG")
        exif = {
            "0th": {271: b"Canon", 272: b"Canon EOS 80D", 274: 8},
            "Exif": {34855: 400, 36867: b"2024:05:01 10:00:00"},
            "GPS": {},
            "1st": {},
            "thumbnail": None,
        }
        piexif.insert(piexif.dump(exif), str(path))
        return path

    def test_preserva_exif(self, tmp_path: Path, make_cr2) -> None:
        origem = self._origem_com_exif(make_cr2("IMG_0001.CR2"))
        destino = tmp_path / "a.jpg"
        settings = ConversionSettings(preserve_exif=True)

        resultado = _converter(settings, FakeRaw(120, 90)).convert(_job(origem, destino))

        assert resultado.status is FileStatus.CONVERTED
        exif = piexif.load(str(destino))
        assert exif["0th"][272] == b"Canon EOS 80D"
        assert exif["Exif"][34855] == 400
        assert exif["0th"][274] == 1  # orientação corrigida
        assert exif["Exif"][40962] == 120  # dimensões do JPEG gerado
        assert exif["Exif"][40963] == 90

    def test_sem_exif_quando_desligado(self, tmp_path: Path, make_cr2) -> None:
        origem = self._origem_com_exif(make_cr2("IMG_0001.CR2"))
        destino = tmp_path / "a.jpg"
        settings = ConversionSettings(preserve_exif=False)

        _converter(settings, FakeRaw(60, 40)).convert(_job(origem, destino))

        assert piexif.load(str(destino))["0th"] == {}

    def test_exif_ilegivel_nao_impede_a_conversao(self, tmp_path: Path, make_cr2) -> None:
        origem = make_cr2("IMG_0001.CR2")  # conteúdo não é uma imagem válida
        destino = tmp_path / "a.jpg"
        settings = ConversionSettings(preserve_exif=True)

        resultado = _converter(settings, FakeRaw(60, 40)).convert(_job(origem, destino))

        assert resultado.status is FileStatus.CONVERTED
        assert "sem EXIF" in resultado.message
        assert destino.is_file()


class TestDescricaoDeErros:
    @pytest.mark.parametrize(
        ("excecao", "trecho"),
        [
            (FileNotFoundError(), "não encontrado"),
            (PermissionError(), "Acesso negado".lower()),
            (MemoryError(), "memória"),
        ],
    )
    def test_mensagens_amigaveis(self, excecao: BaseException, trecho: str) -> None:
        assert trecho.lower() in describe_exception(excecao).lower()

    def test_excecoes_do_rawpy_por_nome(self) -> None:
        class LibRawDataError(Exception):
            pass

        assert "corrompidos" in describe_exception(LibRawDataError())
