"""Dublês do rawpy para testar a conversão sem depender do LibRaw.

O :class:`~cr2_converter.core.converter.Cr2Converter` recebe o abridor de RAW
por injeção justamente para permitir isto: os testes exercitam todo o caminho
real (revelação → PIL → redimensionamento → gravação atômica → EXIF) trocando
apenas a origem dos pixels. Assim a suíte roda em qualquer máquina, sem
depender de arquivos CR2 pessoais.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

__all__ = ["FakeRaw", "FakeSizes", "fake_opener", "sample_pixels"]


class FakeSizes(NamedTuple):
    """Espelha os campos de ``rawpy.ImageSizes`` usados pelo projeto."""

    width: int
    height: int
    flip: int = 0


def sample_pixels(width: int, height: int, seed: int = 20240101) -> np.ndarray:
    """Imagem determinística com gradiente + ruído.

    O ruído é essencial: uma imagem lisa comprime para praticamente o mesmo
    tamanho em qualquer qualidade JPEG, o que tornaria impossível testar o
    efeito do parâmetro ``quality``.
    """
    rng = np.random.default_rng(seed)
    gradient_x = np.linspace(0, 255, width, dtype=np.float32)
    gradient_y = np.linspace(0, 255, height, dtype=np.float32)
    base = (gradient_x[None, :] * 0.5 + gradient_y[:, None] * 0.5)[:, :, None]
    noise = rng.integers(-60, 60, size=(height, width, 3))
    return np.clip(base + noise, 0, 255).astype(np.uint8)


class FakeRaw:
    """Objeto mínimo compatível com o que o projeto usa de ``rawpy.RawPy``."""

    def __init__(
        self,
        width: int = 120,
        height: int = 90,
        *,
        flip: int = 0,
        postprocess_error: BaseException | None = None,
        thumbnail: Any = None,
    ) -> None:
        self.sizes = FakeSizes(width=width, height=height, flip=flip)
        self._postprocess_error = postprocess_error
        self._thumbnail = thumbnail
        self.postprocess_calls: list[dict[str, Any]] = []
        self.closed = False

    def postprocess(self, **kwargs: Any) -> np.ndarray:
        self.postprocess_calls.append(dict(kwargs))
        if self._postprocess_error is not None:
            raise self._postprocess_error
        width, height = self.sizes.width, self.sizes.height
        if kwargs.get("half_size"):
            width, height = max(width // 2, 1), max(height // 2, 1)
        return sample_pixels(width, height)

    def extract_thumb(self) -> Any:
        if self._thumbnail is None:
            raise RuntimeError("sem miniatura")
        return self._thumbnail

    def close(self) -> None:
        self.closed = True


def fake_opener(
    *,
    raws: dict[Path, FakeRaw] | None = None,
    default: FakeRaw | None = None,
    open_error: BaseException | None = None,
    opened: list[Path] | None = None,
):
    """Cria um ``raw_opener`` para o :class:`Cr2Converter`.

    :param raws: mapa opcional de caminho → :class:`FakeRaw`.
    :param default: instância usada quando o caminho não está em ``raws``.
    :param open_error: exceção levantada na abertura (simula arquivo inválido).
    :param opened: lista onde os caminhos abertos são registrados.
    """

    @contextlib.contextmanager
    def _opener(path: Path) -> Iterator[FakeRaw]:
        if opened is not None:
            opened.append(path)
        if open_error is not None:
            raise open_error
        raw = (raws or {}).get(path) or default or FakeRaw()
        try:
            yield raw
        finally:
            raw.close()

    return _opener
