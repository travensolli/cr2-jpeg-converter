# CR2 Converter

Aplicação desktop para converter fotos **Canon RAW (`.CR2`)** em **JPEG**, com
interface gráfica em português, conversão em lote e funcionamento **totalmente
offline**. Nenhum arquivo sai do seu computador.

Feita em Python com [rawpy](https://github.com/letmaik/rawpy) (LibRaw),
[Pillow](https://python-pillow.org/), [PySide6](https://doc.qt.io/qtforpython-6/)
e [piexif](https://github.com/hMatoba/Piexif).

---

## Índice

- [Recursos](#recursos)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Como usar](#como-usar)
- [As configurações, uma a uma](#as-configurações-uma-a-uma)
- [Testes](#testes)
- [Gerando o executável Windows](#gerando-o-executável-windows)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Decisões técnicas](#decisões-técnicas)
- [Limitações conhecidas](#limitações-conhecidas)
- [Solução de problemas](#solução-de-problemas)

---

## Recursos

- Seleção de **arquivos avulsos**, de uma **pasta inteira** (com subpastas) ou
  por **arrastar e soltar** na janela.
- Lista com **nome, caminho, tamanho e status** de cada arquivo.
- **Pré-visualização** do arquivo selecionado, com câmera, lente, dimensões,
  ISO, abertura e velocidade.
- Pasta de destino configurável, com opção de **manter a estrutura de subpastas**.
- **Qualidade JPEG** de 1 a 100, **redimensionamento** com proporção preservada,
  **balanço de branco** e **correção de exposição**.
- **Preservação do EXIF** (data, câmera, lente, ISO, abertura, velocidade, GPS).
- Política clara para arquivos existentes: **sobrescrever, ignorar ou perguntar**
  — nunca sobrescreve em silêncio.
- Conversão **em segundo plano** com barra de progresso, arquivo atual e
  **cancelamento** a qualquer momento.
- Um arquivo com problema **não interrompe o lote**: ao final há um
  **relatório** com arquivo, status, mensagem e data/hora, exportável em CSV.
- Registro de operações em **arquivos de log** rotativos.

---

## Requisitos

| Item | Versão |
|---|---|
| Python | 3.12 ou superior |
| Sistema | Windows 10 / 11 (também roda em Linux) |
| Espaço em disco | ~400 MB para o ambiente virtual (o Qt é grande) |
| Memória | 4 GB são suficientes; veja [Desempenho](#desempenho-e-memória) |

Não é preciso instalar o LibRaw separadamente: ele vem dentro do pacote `rawpy`.

---

## Instalação

```powershell
# 1. Entre na pasta do projeto
cd cr2-jpeg-converter

# 2. Crie o ambiente virtual
python -m venv .venv

# 3. Ative o ambiente
.venv\Scripts\activate

# 4. Instale as dependências
pip install -r requirements.txt

# 5. Execute
python main.py
```

No Linux, troque o passo 3 por `source .venv/bin/activate`.

Para desenvolver (testes e empacotamento), use `requirements-dev.txt` no lugar
de `requirements.txt`.

### Verificando a instalação

```powershell
python -c "import rawpy; print('LibRaw', rawpy.libraw_version)"
```

---

## Como usar

1. **Adicione os arquivos.** Use `Adicionar arquivos` para escolher CR2
   específicos, `Selecionar pasta` para varrer uma pasta inteira (incluindo
   subpastas) ou simplesmente **arraste arquivos e pastas para a janela**.
2. **Escolha a pasta de destino** na seção *Destino*. Marque
   *Manter estrutura de subpastas* se quiser reproduzir a hierarquia original.
3. **Ajuste as configurações** no painel à direita (os valores padrão já são
   adequados para a maioria dos casos).
4. **Clique em `Converter`.** Acompanhe o progresso; a interface continua
   respondendo e o botão `Cancelar` fica disponível.
5. **Confira o resultado.** Ao final aparece um resumo; `Ver relatório` mostra
   o detalhe de cada arquivo e permite salvar um CSV.

As configurações são salvas automaticamente e restauradas na próxima abertura.

### Estrutura de subpastas

Com a opção marcada, esta entrada:

```text
Entrada/
├── Casamento/
│   ├── IMG_001.CR2
│   └── IMG_002.CR2
└── Festa/
    ├── IMG_003.CR2
    └── IMG_004.CR2
```

produz esta saída:

```text
Saída/
├── Casamento/
│   ├── IMG_001.jpg
│   └── IMG_002.jpg
└── Festa/
    ├── IMG_003.jpg
    └── IMG_004.jpg
```

Com a opção **desmarcada**, todos os JPEG vão para a pasta raiz de saída. Se dois
arquivos de pastas diferentes tiverem o mesmo nome, o segundo recebe um sufixo
(`IMG_001 (1).jpg`) — nenhum arquivo do lote sobrescreve outro.

---

## As configurações, uma a uma

### Qualidade JPEG (1–100, padrão 95)

Controla a compressão. A partir de 90 a subamostragem de croma é desativada
(4:4:4), preservando detalhes em cores saturadas — o que faz sentido para quem
está partindo de um RAW.

### Resolução

*Manter resolução original* usa o tamanho que o LibRaw entrega.
*Redimensionar* define uma **largura e altura máximas**: a imagem é reduzida
mantendo a proporção e **nunca é ampliada** — uma foto menor que o limite passa
intacta.

### Balanço de branco

| Opção | O que faz | Parâmetro do LibRaw |
|---|---|---|
| Da câmera (padrão) | Usa os multiplicadores gravados na foto | `use_camera_wb=True` |
| Automático | O LibRaw calcula a partir da imagem | `use_auto_wb=True` |
| Neutro | Nenhuma correção | (nenhum dos dois) |

O modo *Neutro* costuma gerar dominante de cor; existe para casos específicos.

### Exposição (−2 a +2 EV, padrão 0)

Correção aplicada pelo LibRaw antes da interpolação. Internamente o LibRaw usa
escala **linear**, não EV — a conversão `2 ** EV` é feita pela aplicação
(+1 EV = 2,0; −2 EV = 0,25).

Quando há correção manual, o **brilho automático é desligado automaticamente**:
os dois atuam sobre a mesma escala e o ajuste automático normalizaria o
histograma, anulando parte do efeito pedido.

### Preservar EXIF

Copia os metadados do CR2 para o JPEG. Veja
[Metadados](#metadados-o-que-é-preservado) para o detalhe do que é mantido,
ajustado ou descartado.

### Se o JPEG já existir

*Sobrescrever*, *Ignorar* (padrão) ou *Perguntar*. Na opção *Perguntar*, a
pergunta é feita **antes** de o lote começar, com atalhos "para todos" — a
conversão nunca para no meio esperando resposta.

### Conversões simultâneas (1–8)

Quantos arquivos são revelados ao mesmo tempo. Veja
[Desempenho](#desempenho-e-memória) antes de aumentar.

---

## Testes

```powershell
# Suíte completa (roda em qualquer máquina, ~2 segundos)
pytest

# Com detalhes
pytest -v

# Só um arquivo
pytest tests/test_converter.py
```

A suíte tem **169 testes** que rodam sem precisar de nenhum arquivo CR2, mais
9 testes de integração que são pulados automaticamente quando não há amostras.

### Como isso é possível

O `Cr2Converter` recebe o abridor de arquivos RAW por **injeção de dependência**.
Nos testes, `tests/fake_raw.py` fornece os pixels e todo o restante do caminho é
o código real: Pillow, redimensionamento, gravação atômica, cópia de EXIF e
limpeza de temporários. Os pixels falsos têm gradiente **e ruído**, porque uma
imagem lisa comprimiria igual em qualquer qualidade e esconderia regressões.

O EXIF também é testado sem CR2: o `piexif` lê metadados de JPEG e de TIFF, e
como o CR2 **é** um TIFF, as mesmas regras valem para ambos.

### Testes com arquivos CR2 reais

`tests/test_real_cr2.py` verifica o que só um arquivo real revela: decodificação
pelo LibRaw, orientação, tamanho da MakerNote e uso da miniatura embutida. Eles
são **pulados automaticamente** quando não há amostras. Para ativá-los:

```powershell
# Opção A: coloque arquivos .CR2 em tests/data/
# Opção B: aponte para uma pasta existente
$env:CR2_SAMPLE_DIR = "C:\Fotos\Amostras"
pytest tests/test_real_cr2.py -v
```

Arquivos CR2 livres podem ser obtidos em <https://raw.pixls.us/> — veja
`tests/data/README.md` para mais fontes e recomendações.

---

## Gerando o executável Windows

### Caminho rápido

```powershell
.venv\Scripts\activate
pip install -r requirements-dev.txt
.\build_exe.ps1
```

O script confere as dependências, roda os testes, limpa builds anteriores e
gera o executável. Use `.\build_exe.ps1 -SkipTests` para pular os testes.

### Manualmente

```powershell
pip install pyinstaller
pyinstaller CR2Converter.spec
```

O resultado fica em `dist\CR2Converter\CR2Converter.exe`.

### Um único arquivo `.exe`

Abra `CR2Converter.spec` e mude a primeira opção:

```python
ONEFILE = True
```

Isso gera `dist\CR2Converter.exe` sozinho — mais fácil de enviar para alguém,
porém cada execução extrai ~150 MB do Qt para uma pasta temporária, o que
adiciona alguns segundos à abertura. Por isso o padrão é a pasta.

### Detalhes do empacotamento

- **`--windowed` já está configurado** (`console=False` no spec): nenhuma janela
  de terminal aparece junto da aplicação.
- **As DLLs do LibRaw são incluídas explicitamente.** O rawpy distribui
  `raw_r.dll` e `vcomp140.dll` dentro do próprio pacote; sem elas o executável
  abriria e falharia no primeiro arquivo. O spec usa `collect_dynamic_libs` e
  ainda cobre o layout alternativo `rawpy.libs`.
- **UPX está desligado de propósito.** O ganho de tamanho é pequeno e
  executáveis comprimidos com UPX são frequentemente marcados como falso
  positivo por antivírus.
- **Ícone:** salve um `.ico` no projeto e ajuste `ICON = "assets/icon.ico"` no
  spec.
- Sempre **teste o executável gerado** convertendo ao menos um arquivo: erros de
  empacotamento só aparecem em tempo de execução.

---

## Estrutura do projeto

```text
cr2-jpeg-converter/
├── main.py                     Ponto de entrada
├── requirements.txt            Dependências de execução
├── requirements-dev.txt        Testes e empacotamento
├── pyproject.toml              Metadados, pytest e ruff
├── CR2Converter.spec           Receita do PyInstaller
├── build_exe.ps1               Script de build
│
├── cr2_converter/
│   ├── app/                    ← Interface (PySide6)
│   │   ├── main_window.py        Janela principal e orquestração
│   │   ├── models.py             Modelo da lista de arquivos
│   │   ├── settings_panel.py     Painel de configurações
│   │   ├── preview.py            Painel de pré-visualização
│   │   ├── dialogs.py            Conflitos e relatório
│   │   ├── workers.py            Pontes QThread/QRunnable
│   │   └── style.py              Folha de estilo
│   │
│   ├── core/                   ← Regras de negócio (sem Qt)
│   │   ├── converter.py          Conversão de um arquivo
│   │   ├── batch.py              Execução do lote
│   │   ├── planner.py            Origem → destino, colisões
│   │   ├── metadata.py           EXIF
│   │   ├── rawio.py              Acesso ao rawpy/LibRaw
│   │   ├── settings.py           Configurações e persistência
│   │   └── types.py              Tipos de domínio
│   │
│   └── utils/                  ← Utilitários
│       ├── filesystem.py         Descoberta de arquivos
│       ├── logger.py             Configuração de logging
│       └── paths.py              Pastas de dados e logs
│
└── tests/                      169 testes + 9 de integração opcional
```

A separação é estrita: **`core` nunca importa PySide6**. Isso mantém a lógica
testável sem interface e impede que regras de negócio se misturem com widgets.

---

## Decisões técnicas

### Threads: por que um gerador, e não sinais de várias threads

O `BatchRunner.run()` é um **gerador**. As threads do pool apenas colocam
eventos em uma fila; quem consome o gerador — uma única `QThread` — é o único
a emitir sinais Qt. Isso elimina a principal fonte de condição de corrida em
aplicações Qt (atualizar a interface a partir de várias threads) sem precisar de
locks, e deixa o lote testável sem GUI nenhuma.

O contrato central é: **cada arquivo produz exatamente um evento de conclusão**,
mesmo diante de falhas inesperadas. É isso que garante que o consumidor nunca
fique esperando um evento que jamais chegaria.

### Desempenho e memória

O LibRaw que acompanha o rawpy é compilado com **OpenMP** (`vcomp140.dll`) e já
usa vários núcleos dentro de um único `postprocess`. O ganho de threads Python
adicionais vem de sobrepor leitura de disco e codificação JPEG de um arquivo com
a revelação de outro — não de paralelizar a revelação em si.

Medições nesta máquina (Canon EOS Rebel T5, 18 MP, arquivos de ~21 MB):

| Cenário | Tempo |
|---|---|
| 1 arquivo, qualidade 95, com EXIF | ~2,1 s |
| 3 arquivos, 1 thread (estimado) | ~6,3 s |
| 3 arquivos, 2 threads (medido) | ~4,0 s |

Ou seja: 2 threads dão cerca de **1,5×**, não 2×. Por isso o padrão é
conservador (`min(4, núcleos / 2)`).

O custo de memória é o motivo real para não exagerar: o buffer RGB de uma
imagem de 18 MP ocupa **54 MB** (uma de 24 MP passa de 70 MB), e cada thread
mantém o seu, além dos buffers internos do LibRaw. O array é liberado
explicitamente logo após a gravação, e os arquivos são processados um a um —
nada é acumulado em memória entre as conversões.

### Gravação atômica

O JPEG é escrito em um arquivo temporário na pasta de destino e só então movido
para o nome final com `os.replace`. Uma falha, um cancelamento ou uma queda de
energia no meio do processo nunca deixam um JPEG truncado com o nome definitivo.
Os temporários são removidos em qualquer caminho de erro.

Imediatamente antes da gravação final, a existência do destino é verificada de
novo: se o arquivo apareceu durante a conversão, ele **não** é sobrescrito.

### Metadados: o que é preservado

O rawpy entrega apenas pixels — ele não expõe o bloco EXIF. Como o CR2 é
internamente um TIFF, o `piexif` consegue lê-lo diretamente e reescrever os
metadados dentro do JPEG.

**Preservado:** fabricante e modelo da câmera, data/hora original, lente, ISO,
abertura, velocidade, distância focal, modo de exposição, GPS, número de série
do corpo e a MakerNote da Canon.

**Ajustado de propósito:**

- **Orientação → 1.** O LibRaw já entrega a imagem rotacionada. Copiar o valor
  original (por exemplo, 8 para retrato) faria o visualizador girar a foto uma
  segunda vez.
- **Dimensões em pixels** passam a refletir o JPEG gerado, não o RAW.
- Uma tag `ProcessingSoftware` registra a ferramenta **sem apagar** o campo
  `Software`, onde a Canon grava a versão do firmware.

**Descartado:**

- Tags estruturais do IFD0 (`StripOffsets`, `StripByteCounts`, `Compression`…):
  descrevem o *preview* embutido no CR2 e apontariam para posições inexistentes
  dentro do JPEG.
- A miniatura embutida: ela ficaria de lado depois da correção de orientação.

**O limite de 64 KB.** O EXIF vive em um segmento APP1 cujo tamanho é gravado em
2 bytes — ou seja, no máximo 65.533 bytes de conteúdo. Um CR2 comum já chega a
~62 KB, com a MakerNote da Canon sozinha passando de 44 KB. Além disso, o
`piexif.insert` monta o cabeçalho do segmento **sem verificar esse limite**.
A aplicação, então, mede o bloco e descarta campos por ordem de importância
(XMP → UserComment → MakerNote) até caber, registrando o que foi removido no
log. Em um arquivo real desta máquina o bloco final ficou em **53.855 bytes**,
com a MakerNote preservada.

### Descoberta de arquivos no Windows

No Windows, `Path.glob("*.CR2")` é *case-insensitive*: varrer `*.CR2` e `*.cr2`
separadamente retornaria cada arquivo **duas vezes**. A varredura é feita uma
única vez comparando a extensão em minúsculas, o que funciona igual nos dois
sistemas operacionais.

### Por que `optimize=True` não é usado ao salvar o JPEG

O Pillow dimensiona o buffer do codificador por heurística (largura × altura
bytes; o dobro a partir da qualidade 95). Quando o JPEG resultante passa desse
tamanho, a gravação falha com `OSError: broken data stream`. Isso acontece de
verdade com **fotos granuladas (ISO alto) em qualidade 90–94 com croma 4:4:4** —
foi reproduzido aqui em 300×200, 800×600 e 2000×1500. O ganho de tamanho seria
de apenas ~6%, e o custo seria transformar fotos ruidosas em erros no meio do
lote. Há um teste de regressão cobrindo toda a faixa de qualidade.

### Onde ficam logs e configurações

| | Rodando do código-fonte | Executável (PyInstaller) |
|---|---|---|
| Logs | `logs/` na raiz do projeto | `%LOCALAPPDATA%\CR2Converter\logs` |
| Configurações | `%LOCALAPPDATA%\CR2Converter\settings.json` | (o mesmo) |

Os logs são rotativos (5 arquivos de 2 MB) e podem ser abertos pelo menu
*Ajuda → Abrir pasta de logs*. Em builds `--windowed` o `sys.stderr` não existe,
e o logging trata esse caso — um `StreamHandler` sobre ele quebraria a aplicação
no primeiro registro.

---

## Limitações conhecidas

- **A pré-visualização não reflete as configurações.** Ela usa a miniatura JPEG
  que a câmera já gravou dentro do CR2 — por isso é praticamente instantânea.
  Ela mostra o *arquivo*, não uma simulação do resultado com o balanço de
  branco e a exposição escolhidos. Revelar cada preview em tempo real custaria
  ~1 segundo por clique.
- **MakerNote da Canon.** Ela usa deslocamentos absolutos relativos ao arquivo
  original; ao ser copiada para um novo arquivo, os ponteiros internos deixam de
  bater. Campos EXIF padrão (data, ISO, abertura, lente, GPS) não são afetados.
  Leitores tolerantes como o ExifTool reconstroem a MakerNote; outros podem
  ignorá-la. Preservar ainda é melhor que descartar.
- **Somente `.CR2`.** O LibRaw lê muitos outros formatos RAW (NEF, ARW, CR3), mas
  o escopo desta versão é CR2, e a validação reflete isso.
- **Somente JPEG na saída.** O seletor de formato existe e tem uma única opção.
- **Dimensões ligeiramente diferentes do software da Canon.** O LibRaw entrega
  alguns pixels a mais que o recorte oficial (5202×3464 contra 5184×3456 no
  arquivo testado), porque usa uma área útil do sensor um pouco maior.
- **Caminhos acima de 260 caracteres** podem falhar no Windows se o suporte a
  caminhos longos não estiver habilitado no sistema.
- **O cancelamento não interrompe a revelação em andamento.** A chamada ao
  LibRaw não é interrompível; o arquivo atual termina (ou é descartado antes da
  gravação) e os demais são cancelados imediatamente. Isso é intencional: mata a
  possibilidade de gerar arquivo corrompido.
- **Não há edição por arquivo.** As configurações valem para o lote inteiro.

---

## Solução de problemas

### "A biblioteca rawpy não pôde ser carregada"

O ambiente virtual não está ativo ou as dependências não foram instaladas:

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

Se persistir, instale o
[Visual C++ Redistributable 2015-2022](https://aka.ms/vs/17/release/vc_redist.x64.exe):
o LibRaw é uma DLL nativa e depende dele.

### "arquivo não reconhecido pelo LibRaw"

O arquivo está corrompido, truncado (download incompleto) ou não é realmente um
CR2. Os demais arquivos do lote continuam normalmente; o `Ver relatório` mostra
exatamente quais falharam.

### Todos os arquivos aparecem como "Ignorado"

Os JPEG já existem na pasta de destino e a política está em *Ignorar* (o
padrão). Mude para *Sobrescrever* ou *Perguntar* na seção
*Se o JPEG já existir*.

### "acesso negado" ao gravar

O JPEG de destino está aberto em outro programa (visualizador, editor) ou a
pasta exige permissão de administrador. Feche o arquivo ou escolha outra pasta.

### A conversão está lenta

Cada arquivo leva 1 a 3 segundos, e isso é dominado pela revelação do RAW. Você
pode aumentar *Conversões simultâneas*, mas leia
[Desempenho](#desempenho-e-memória) antes: o ganho é bem menor que proporcional
e o consumo de memória cresce por thread.

### As cores ficaram diferentes do software da Canon

Esperado. O LibRaw e o Canon DPP usam algoritmos de interpolação e perfis de cor
diferentes. Experimente o balanço de branco *Da câmera* (padrão) e mantenha o
brilho automático ligado.

### O executável não abre

Rode `dist\CR2Converter\CR2Converter.exe` a partir de um terminal para ver a
mensagem de erro, e confira o log em `%LOCALAPPDATA%\CR2Converter\logs`.

### Onde vejo o que aconteceu

Menu **Ajuda → Abrir pasta de logs**. Toda conversão, erro e decisão sobre
metadados é registrada lá.

---

## Licença

MIT.
