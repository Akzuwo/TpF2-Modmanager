[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Version = "2.0.1",

    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = $PSScriptRoot
Set-Location $projectDir

if ($Version -match '^\d+\.\d+$') {
    $Version = "$Version.0"
}
if ($Version -notmatch '^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$') {
    throw "Ungueltige Version '$Version'. Erwartet wird z. B. 2.0 oder 2.0.0."
}

foreach ($command in @("python", "node", "npm")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Das benoetigte Programm '$command' wurde nicht gefunden."
    }
}

Write-Host "Baue TpF2 Modmanager v$Version" -ForegroundColor Cyan

if (-not $SkipInstall) {
    Write-Host "Installiere Python-Abhaengigkeiten..."
    python -m pip install -r requirements.txt PyInstaller
    if ($LASTEXITCODE -ne 0) { throw "Installation der Python-Abhaengigkeiten fehlgeschlagen." }

    Write-Host "Installiere Node-Abhaengigkeiten..."
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "Installation der Node-Abhaengigkeiten fehlgeschlagen." }
}

if (-not (Test-Path node_modules)) {
    throw "node_modules fehlt. Starte das Skript ohne -SkipInstall."
}

Write-Host "Setze Paketversion auf $Version..."
npm version $Version --no-git-tag-version --allow-same-version
if ($LASTEXITCODE -ne 0) { throw "Setzen der Version fehlgeschlagen." }

Write-Host "Bereinige vorherige Build-Ausgaben..."
foreach ($directory in @("build", "dist", "dist-electron")) {
    $path = Join-Path $projectDir $directory
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

Write-Host "Erzeuge NSIS-Installer..."
npm run dist
if ($LASTEXITCODE -ne 0) { throw "Build fehlgeschlagen." }

$artifact = Join-Path $projectDir "dist-electron\TpF2-Modmanager-Setup-$Version.exe"
if (-not (Test-Path $artifact)) {
    throw "Build wurde beendet, aber das erwartete Artefakt fehlt: $artifact"
}

$file = Get-Item $artifact
$sizeMb = [Math]::Round($file.Length / 1MB, 1)
Write-Host "Build erfolgreich: $($file.FullName) ($sizeMb MB)" -ForegroundColor Green
