<#
.SYNOPSIS
    Gera o executável CR2Converter.exe com PyInstaller.

.DESCRIPTION
    Verifica o ambiente, instala o PyInstaller se necessário, limpa builds
    anteriores e executa a receita definida em CR2Converter.spec.

.EXAMPLE
    .\build_exe.ps1
    .\build_exe.ps1 -SkipTests
#>

[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Ambiente virtual não encontrado em .venv" -ForegroundColor Red
    Write-Host "Crie-o antes de continuar:" -ForegroundColor Yellow
    Write-Host "    python -m venv .venv"
    Write-Host "    .venv\Scripts\activate"
    Write-Host "    pip install -r requirements-dev.txt"
    exit 1
}

Write-Host "==> Verificando dependências" -ForegroundColor Cyan
& $python -c "import rawpy, PySide6, PIL, piexif"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dependências faltando. Rode: pip install -r requirements-dev.txt" -ForegroundColor Red
    exit 1
}

& $python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> Instalando PyInstaller" -ForegroundColor Cyan
    & $python -m pip install "pyinstaller>=6.0"
}

if (-not $SkipTests) {
    Write-Host "==> Rodando os testes" -ForegroundColor Cyan
    & $python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Testes falharam; build interrompido. Use -SkipTests para ignorar." -ForegroundColor Red
        exit 1
    }
}

Write-Host "==> Limpando builds anteriores" -ForegroundColor Cyan
foreach ($dir in @("build", "dist")) {
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
}

Write-Host "==> Gerando o executável" -ForegroundColor Cyan
& $python -m PyInstaller CR2Converter.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Host "Falha ao gerar o executável." -ForegroundColor Red
    exit 1
}

$exe = Get-ChildItem -Path "dist" -Filter "CR2Converter.exe" -Recurse | Select-Object -First 1
if ($exe) {
    $sizeMb = [math]::Round($exe.Length / 1MB, 1)
    Write-Host ""
    Write-Host "Pronto: $($exe.FullName)  ($sizeMb MB)" -ForegroundColor Green
    Write-Host "Teste o executável antes de distribuir: abra-o e converta um arquivo." -ForegroundColor Yellow
} else {
    Write-Host "Build terminou, mas CR2Converter.exe não foi encontrado em dist/." -ForegroundColor Red
    exit 1
}
