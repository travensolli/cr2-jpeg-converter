# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
versionamento segue [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [1.0.0] — 2026-08-15

Primeira versão funcional.

### Adicionado

**Conversão**

- Conversão de arquivos Canon RAW (`.CR2`) para JPEG usando LibRaw via `rawpy`.
- Qualidade JPEG configurável de 1 a 100 (padrão 95), com croma 4:4:4 a partir
  de 90.
- Redimensionamento opcional por largura e altura máximas, mantendo a proporção
  e sem ampliar imagens menores que o limite.
- Balanço de branco da câmera (padrão), automático ou neutro.
- Correção de exposição de −2 a +2 EV.
- Preservação de EXIF: data/hora, câmera, lente, ISO, abertura, velocidade, GPS
  e MakerNote, com orientação e dimensões corrigidas para o arquivo gerado.
- Gravação atômica: o JPEG é escrito em um temporário e movido para o nome final
  apenas ao concluir.

**Lote**

- Conversão em segundo plano com paralelismo controlado, sem travar a interface.
- Barra de progresso, contador de arquivos e nome do arquivo atual.
- Cancelamento a qualquer momento, sem gerar arquivos corrompidos.
- Um arquivo com erro não interrompe o lote.
- Relatório final com arquivo, status, mensagem e data/hora, exportável em CSV.

**Interface**

- Seleção de arquivos avulsos, de pastas inteiras com subpastas ou por arrastar
  e soltar na janela.
- Lista com nome, caminho, tamanho e status de cada arquivo.
- Pré-visualização do arquivo selecionado a partir da miniatura embutida no CR2,
  com câmera, lente, dimensões, ISO, abertura e velocidade.
- Pasta de destino configurável, com opção de manter a estrutura de subpastas.
- Política para arquivos existentes: sobrescrever, ignorar (padrão) ou perguntar.
- Configurações persistidas entre sessões.

**Infraestrutura**

- Registro de operações em arquivos de log rotativos.
- 169 testes automatizados que rodam sem nenhum arquivo CR2, mais 9 testes de
  integração ativados quando há amostras disponíveis.
- Geração de executável Windows com PyInstaller, em modo janela e com as DLLs do
  LibRaw incluídas.

### Limitações conhecidas

- A pré-visualização mostra a miniatura gravada pela câmera e não simula as
  configurações de conversão escolhidas.
- A MakerNote da Canon usa deslocamentos absolutos, que deixam de ser válidos ao
  ser copiada para outro arquivo.
- O cancelamento não interrompe a revelação já em andamento; o arquivo atual
  termina ou é descartado antes da gravação.
- Apenas arquivos `.CR2` na entrada e JPEG na saída.

Consulte o `README.md` para a lista completa e o detalhamento.

[1.0.0]: https://semver.org/lang/pt-BR/
