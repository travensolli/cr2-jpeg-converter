"""Testes da cópia de metadados EXIF.

Não é preciso um CR2 aqui: o ``piexif`` lê EXIF de JPEG e de TIFF (o CR2 é um
TIFF), e as regras exercitadas — filtragem de tags, correção de orientação,
limite de 64 KB do segmento APP1 — são as mesmas nos dois casos.
"""

from __future__ import annotations

from pathlib import Path

import piexif
import pytest
from PIL import Image

from cr2_converter.core.metadata import (
    APP1_MAX_PAYLOAD,
    ExifCopyError,
    _dump_within_app1,
    _sanitize,
    build_exif_bytes,
    copy_exif_to_jpeg,
    embed_exif,
    read_basic_tags,
)

_MAKE = 271
_MODEL = 272
_ORIENTATION = 274
_STRIP_OFFSETS = 273
_STRIP_BYTE_COUNTS = 279
_PROCESSING_SOFTWARE = 11
_MAKERNOTE = 37500
_USERCOMMENT = 37510
_XMLPACKET = 700
_PIXEL_X = 40962
_PIXEL_Y = 40963
_DATETIME_ORIGINAL = 36867


def _exif_de_camera() -> dict:
    """EXIF parecido com o de um CR2 real (inclusive as tags problemáticas)."""
    return {
        "0th": {
            256: 5184,  # ImageWidth do preview embutido
            257: 3456,  # ImageLength do preview embutido
            258: (8, 8, 8),  # BitsPerSample
            259: 6,  # Compression
            _STRIP_OFFSETS: 64600,
            _STRIP_BYTE_COUNTS: 988230,
            _MAKE: b"Canon",
            _MODEL: b"Canon EOS REBEL T5",
            _ORIENTATION: 8,  # retrato: o LibRaw já rotaciona a imagem
            306: b"2025:01:31 08:22:31",
        },
        "Exif": {
            33434: (1, 320),  # ExposureTime
            33437: (71, 10),  # FNumber
            34855: 100,  # ISO
            _DATETIME_ORIGINAL: b"2025:01:31 08:22:31",
            42036: b"EF-S55-250mm f/4-5.6 IS II",
            _PIXEL_X: 5184,
            _PIXEL_Y: 3456,
        },
        "GPS": {0: (2, 3, 0, 0)},
        "Interop": {1: b"R98"},
        "1st": {},
        "thumbnail": None,
    }


def _jpeg_com_exif(path: Path, exif: dict | None = None, size=(64, 48)) -> Path:
    """Cria um JPEG e insere o EXIF informado."""
    Image.new("RGB", size, (120, 90, 60)).save(path, "JPEG", quality=80)
    if exif is not None:
        piexif.insert(piexif.dump(exif), str(path))
    return path


class TestSanitize:
    def test_orientacao_zerada(self) -> None:
        """A imagem sai rotacionada do LibRaw; girar de novo seria erro."""
        limpo = _sanitize(_exif_de_camera(), 3464, 5202)

        assert limpo["0th"][_ORIENTATION] == 1

    def test_dimensoes_atualizadas(self) -> None:
        limpo = _sanitize(_exif_de_camera(), 3464, 5202)

        assert limpo["Exif"][_PIXEL_X] == 3464
        assert limpo["Exif"][_PIXEL_Y] == 5202

    def test_remove_tags_estruturais_do_preview(self) -> None:
        limpo = _sanitize(_exif_de_camera(), 100, 100)

        for tag in (256, 257, 258, 259, _STRIP_OFFSETS, _STRIP_BYTE_COUNTS):
            assert tag not in limpo["0th"], f"tag estrutural {tag} não removida"

    def test_preserva_identificacao_da_camera(self) -> None:
        limpo = _sanitize(_exif_de_camera(), 100, 100)

        assert limpo["0th"][_MAKE] == b"Canon"
        assert limpo["0th"][_MODEL] == b"Canon EOS REBEL T5"
        assert limpo["Exif"][_DATETIME_ORIGINAL] == b"2025:01:31 08:22:31"
        assert limpo["GPS"][0] == (2, 3, 0, 0)

    def test_registra_a_ferramenta(self) -> None:
        limpo = _sanitize(_exif_de_camera(), 100, 100)

        assert b"CR2 Converter" in limpo["0th"][_PROCESSING_SOFTWARE]

    def test_descarta_miniatura_do_original(self) -> None:
        """A miniatura embutida ficaria de lado após zerar a orientação."""
        exif = _exif_de_camera()
        exif["thumbnail"] = b"\xff\xd8" + b"\x00" * 500
        exif["1st"] = {513: 100, 514: 500}

        limpo = _sanitize(exif, 100, 100)

        assert "1st" not in limpo
        assert "thumbnail" not in limpo

    def test_descarta_tags_desconhecidas(self) -> None:
        """piexif.dump levantaria KeyError para tags que não conhece."""
        exif = _exif_de_camera()
        exif["0th"][0xEA1C] = b"padding da Microsoft"
        exif["Exif"][0xC640] = 3

        limpo = _sanitize(exif, 100, 100)

        assert 0xEA1C not in limpo["0th"]
        assert 0xC640 not in limpo["Exif"]

    def test_descarta_valores_com_tipo_errado(self) -> None:
        """Um único valor malformado não pode inviabilizar todo o EXIF."""
        exif = _exif_de_camera()
        exif["0th"][_MAKE] = 12345  # deveria ser Ascii
        exif["Exif"][33434] = "texto"  # deveria ser Rational

        limpo = _sanitize(exif, 100, 100)

        assert _MAKE not in limpo["0th"]
        assert 33434 not in limpo["Exif"]
        assert limpo["0th"][_MODEL] == b"Canon EOS REBEL T5"  # o resto sobrevive

    def test_converte_str_para_bytes(self) -> None:
        exif = _exif_de_camera()
        exif["0th"][_MAKE] = "Canon"

        assert _sanitize(exif, 100, 100)["0th"][_MAKE] == b"Canon"

    def test_descarta_valores_fora_da_faixa(self) -> None:
        exif = _exif_de_camera()
        exif["Exif"][34855] = 10**12  # ISO como Short: não cabe

        assert 34855 not in _sanitize(exif, 100, 100)["Exif"]


class TestLimiteApp1:
    def test_exif_normal_cabe(self) -> None:
        payload = _dump_within_app1(_sanitize(_exif_de_camera(), 100, 100))

        assert 0 < len(payload) <= APP1_MAX_PAYLOAD

    def test_makernote_gigante_e_descartada(self) -> None:
        """A MakerNote da Canon passa de 44 KB; alguns corpos estouram o limite."""
        exif = _exif_de_camera()
        exif["Exif"][_MAKERNOTE] = b"M" * 70_000

        payload = _dump_within_app1(_sanitize(exif, 100, 100))

        assert len(payload) <= APP1_MAX_PAYLOAD
        assert b"M" * 1000 not in payload
        assert b"Canon EOS REBEL T5" in payload  # o essencial permanece

    def test_descarta_xmp_antes_da_makernote(self) -> None:
        exif = _exif_de_camera()
        exif["0th"][_XMLPACKET] = tuple(b"<xmp/>" * 2000)
        exif["Exif"][_MAKERNOTE] = b"M" * 40_000

        payload = _dump_within_app1(_sanitize(exif, 100, 100))

        assert len(payload) <= APP1_MAX_PAYLOAD
        assert b"M" * 40_000 in payload  # a MakerNote foi preservada

    def test_conjunto_essencial_como_ultimo_recurso(self) -> None:
        exif = _exif_de_camera()
        exif["Exif"][_MAKERNOTE] = b"M" * 70_000
        exif["Exif"][_USERCOMMENT] = b"U" * 70_000
        exif["0th"][33432] = b"C" * 70_000  # Copyright absurdamente grande

        payload = _dump_within_app1(_sanitize(exif, 100, 100))

        assert len(payload) <= APP1_MAX_PAYLOAD
        assert b"Canon EOS REBEL T5" in payload

    def test_campo_isolado_gigante_e_descartado(self) -> None:
        """Nem no conjunto essencial um campo pode monopolizar o orçamento."""
        gigante = {
            "0th": {_MODEL: b"X" * 70_000, _MAKE: b"Canon"},
            "Exif": {},
            "GPS": {},
            "Interop": {},
        }

        payload = _dump_within_app1(gigante)

        assert len(payload) <= APP1_MAX_PAYLOAD
        assert b"Canon" in payload

    def test_erro_quando_o_piexif_nao_consegue_serializar(self, monkeypatch) -> None:
        """Último recurso: avisar em vez de gravar um JPEG corrompido."""

        def _falha(*_args, **_kwargs):
            raise ValueError("piexif indisponível")

        monkeypatch.setattr(piexif, "dump", _falha)

        with pytest.raises(ExifCopyError):
            _dump_within_app1(_sanitize(_exif_de_camera(), 100, 100))


class TestIntegracao:
    def test_copia_completa_para_jpeg(self, tmp_path: Path) -> None:
        origem = _jpeg_com_exif(tmp_path / "origem.jpg", _exif_de_camera())
        destino = _jpeg_com_exif(tmp_path / "destino.jpg", None, size=(120, 80))

        copy_exif_to_jpeg(origem, destino, 120, 80)

        lido = piexif.load(str(destino))
        assert lido["0th"][_MODEL] == b"Canon EOS REBEL T5"
        assert lido["0th"][_ORIENTATION] == 1
        assert lido["Exif"][_PIXEL_X] == 120
        assert lido["Exif"][_PIXEL_Y] == 80
        assert lido["Exif"][42036] == b"EF-S55-250mm f/4-5.6 IS II"

    def test_jpeg_continua_valido_depois_do_exif(self, tmp_path: Path) -> None:
        origem = _jpeg_com_exif(tmp_path / "origem.jpg", _exif_de_camera())
        destino = _jpeg_com_exif(tmp_path / "destino.jpg", None, size=(120, 80))

        copy_exif_to_jpeg(origem, destino, 120, 80)

        with Image.open(destino) as imagem:
            imagem.load()
            assert imagem.size == (120, 80)

    def test_origem_sem_exif_nao_quebra(self, tmp_path: Path) -> None:
        origem = _jpeg_com_exif(tmp_path / "origem.jpg", None)

        payload = build_exif_bytes(origem, 50, 40)

        assert payload.startswith(b"Exif\x00\x00")

    def test_origem_invalida_levanta_erro_tratavel(self, tmp_path: Path) -> None:
        invalido = tmp_path / "lixo.CR2"
        invalido.write_bytes(b"nem TIFF nem JPEG")

        with pytest.raises(ExifCopyError):
            build_exif_bytes(invalido, 10, 10)

    def test_embed_recusa_bloco_grande_demais(self, tmp_path: Path) -> None:
        destino = _jpeg_com_exif(tmp_path / "destino.jpg", None)

        with pytest.raises(ExifCopyError):
            embed_exif(destino, b"Exif\x00\x00" + b"X" * APP1_MAX_PAYLOAD)


class TestReadBasicTags:
    def test_le_camera(self, tmp_path: Path) -> None:
        origem = _jpeg_com_exif(tmp_path / "origem.jpg", _exif_de_camera())

        tags = read_basic_tags(origem)

        assert tags["make"] == "Canon"
        assert tags["model"] == "Canon EOS REBEL T5"
        assert tags["orientation"] == 8

    def test_arquivo_sem_exif_devolve_vazio(self, tmp_path: Path) -> None:
        origem = _jpeg_com_exif(tmp_path / "origem.jpg", None)

        assert read_basic_tags(origem) == {}

    def test_arquivo_invalido_nao_levanta(self, tmp_path: Path) -> None:
        invalido = tmp_path / "lixo.CR2"
        invalido.write_bytes(b"nao e imagem")

        assert read_basic_tags(invalido) == {}
