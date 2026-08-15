# Arquivos de amostra para os testes de integração

Esta pasta está vazia de propósito: arquivos CR2 têm 20–30 MB cada e não devem
ir para o controle de versão.

## Como a suíte lida com isso

A estratégia de testes é dividida em duas camadas:

1. **Testes que não precisam de RAW** (a maioria). O
   `Cr2Converter` recebe o abridor de arquivos RAW por injeção de dependência,
   então `tests/fake_raw.py` fornece os pixels e todo o restante do caminho é
   exercitado de verdade: Pillow, redimensionamento, gravação atômica, cópia de
   EXIF e limpeza de temporários. Rodam em qualquer máquina, em ~1 segundo.

   O EXIF também é testado sem CR2: o `piexif` lê metadados de JPEG e de TIFF, e
   como o CR2 **é** um TIFF, as mesmas regras valem para os dois formatos.

2. **Testes de integração com CR2 reais** (`tests/test_real_cr2.py`). São
   pulados automaticamente quando não há amostras. Eles verificam o que só um
   arquivo real pode mostrar: se o LibRaw decodifica o arquivo, se a orientação
   sai correta, se a MakerNote da Canon cabe no limite de 64 KB do segmento
   APP1 e se o preview usa a miniatura embutida.

## Como ativar os testes de integração

Coloque um ou mais arquivos `.CR2` nesta pasta:

```text
tests/data/
├── README.md
└── IMG_0001.CR2
```

Ou aponte para uma pasta que você já tenha:

```powershell
$env:CR2_SAMPLE_DIR = "C:\Fotos\Amostras"
pytest tests/test_real_cr2.py -v
```

## Onde conseguir arquivos CR2 livres

Caso você não tenha uma câmera Canon à mão:

- **raw.pixls.us** — <https://raw.pixls.us/> — banco colaborativo de RAW de
  centenas de câmeras, com licenças permissivas (CC0 na maior parte).
  Filtre por fabricante "Canon" e formato "CR2".
- **RAW Samples Repository** — <https://raw.pixls.us/data/Canon/> — acesso
  direto às amostras Canon.
- **Signature Edits — Free RAW Photos** —
  <https://www.signatureedits.com/free-raw-photos/> — pacotes gratuitos para
  treino de edição, incluindo arquivos Canon.

Prefira amostras de câmeras variadas: corpos diferentes geram MakerNotes de
tamanhos bem distintos, que é justamente onde mora o risco do limite de 64 KB.

> Se você usar arquivos próprios, lembre-se de que eles não devem ser
> comitados — o `.gitignore` do projeto já bloqueia `tests/data/*.CR2`.
