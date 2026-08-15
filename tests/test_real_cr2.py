"""Testes de integração com arquivos CR2 reais.

São **pulados automaticamente** quando não há amostras disponíveis, para que a
suíte continue rodando em qualquer máquina. Para ativá-los, coloque um ou mais
``.CR2`` em ``tests/data/`` ou aponte a variável de ambiente ``CR2_SAMPLE_DIR``
para uma pasta com amostras:

    set CR2_SAMPLE_DIR=C:\\Fotos\\Amostras
    pytest tests/test_real_cr2.py -v

Consulte ``tests/data/README.md`` para fontes de arquivos CR2 livres.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("rawpy")

import piexif
from PIL import Image

from cr2_converter.core.converter import Cr2Converter
from cr2_converter.core.planner import plan_jobs
from cr2_converter.core.rawio import open_raw, render_preview
from cr2_converter.core.settings import ConversionSettings
from cr2_converter.core.types import ConversionJob, FileStatus
from cr2_converter.utils.filesystem import SourceFile

_SAMPLE_DIR = Path(
    os.environ.get("CR2_SAMPLE_DIR") or (Path(__file__).parent / "data")
)


def _samples() -> list[Path]:
    if not _SAMPLE_DIR.is_dir():
        return []
    return sorted(p for p in _SAMPLE_DIR.iterdir() if p.suffix.lower() == ".cr2")


_SAMPLES = _samples()

pytestmark = pytest.mark.skipif(
    not _SAMPLES,
    reason=f"nenhum arquivo .CR2 em {_SAMPLE_DIR} (defina CR2_SAMPLE_DIR para ativar)",
)


@pytest.fixture(scope="module")
def sample() -> Path:
    return _SAMPLES[0]


def test_abre_e_le_dimensoes(sample: Path) -> None:
    with open_raw(sample) as raw:
        assert raw.sizes.width > 0
        assert raw.sizes.height > 0


def test_conversao_completa(sample: Path, tmp_path: Path) -> None:
    destino = tmp_path / "saida.jpg"
    settings = ConversionSettings(quality=90, preserve_exif=True)

    resultado = Cr2Converter(settings).convert(
        ConversionJob(source=sample, destination=destino)
    )

    assert resultado.status is FileStatus.CONVERTED, resultado.message
    assert destino.stat().st_size > 0
    with Image.open(destino) as imagem:
        imagem.load()
        assert imagem.format == "JPEG"
        assert imagem.size[0] > 100


def test_orientacao_corrigida_no_exif(sample: Path, tmp_path: Path) -> None:
    """O LibRaw já rotaciona a imagem: o EXIF de saída precisa dizer 'sem giro'."""
    destino = tmp_path / "saida.jpg"
    Cr2Converter(ConversionSettings(preserve_exif=True)).convert(
        ConversionJob(source=sample, destination=destino)
    )

    exif = piexif.load(str(destino))

    assert exif["0th"].get(274, 1) == 1


def test_dimensoes_do_exif_batem_com_o_arquivo(sample: Path, tmp_path: Path) -> None:
    destino = tmp_path / "saida.jpg"
    Cr2Converter(ConversionSettings(preserve_exif=True)).convert(
        ConversionJob(source=sample, destination=destino)
    )

    exif = piexif.load(str(destino))
    with Image.open(destino) as imagem:
        largura, altura = imagem.size

    assert exif["Exif"][40962] == largura
    assert exif["Exif"][40963] == altura


def test_exif_cabe_no_segmento_app1(sample: Path, tmp_path: Path) -> None:
    """A MakerNote da Canon passa de 40 KB; o limite do APP1 é 64 KB."""
    from cr2_converter.core.metadata import APP1_MAX_PAYLOAD, build_exif_bytes

    payload = build_exif_bytes(sample, 1000, 800)

    assert len(payload) <= APP1_MAX_PAYLOAD


def test_camera_identificada(sample: Path, tmp_path: Path) -> None:
    destino = tmp_path / "saida.jpg"
    Cr2Converter(ConversionSettings(preserve_exif=True)).convert(
        ConversionJob(source=sample, destination=destino)
    )

    exif = piexif.load(str(destino))

    assert exif["0th"].get(272), "modelo da câmera não preservado"


def test_redimensionamento_real(sample: Path, tmp_path: Path) -> None:
    destino = tmp_path / "saida.jpg"
    settings = ConversionSettings(
        resize_enabled=True, max_width=800, max_height=800, preserve_exif=True
    )

    Cr2Converter(settings).convert(ConversionJob(source=sample, destination=destino))

    with Image.open(destino) as imagem:
        assert max(imagem.size) == 800


def test_preview_usa_miniatura_embutida(sample: Path) -> None:
    dados, info = render_preview(sample, max_edge=600)

    assert dados.startswith(b"\xff\xd8")  # JPEG
    assert info.width > 0 and info.height > 0
    with Image.open(__import__("io").BytesIO(dados)) as imagem:
        assert max(imagem.size) <= 600


def test_lote_com_varios_arquivos(tmp_path: Path) -> None:
    if len(_SAMPLES) < 2:
        pytest.skip("são necessários pelo menos 2 arquivos de amostra")

    from cr2_converter.core.batch import BatchRunner
    from cr2_converter.core.types import FileFinished

    jobs = plan_jobs([SourceFile(p) for p in _SAMPLES[:3]], tmp_path / "out")
    runner = BatchRunner(jobs, ConversionSettings(quality=80, workers=2))

    resultados = [e.result for e in runner.run() if isinstance(e, FileFinished)]

    assert len(resultados) == len(jobs)
    assert all(r.status is FileStatus.CONVERTED for r in resultados), [
        r.message for r in resultados
    ]
    assert list(tmp_path.rglob("*.tmp")) == []
