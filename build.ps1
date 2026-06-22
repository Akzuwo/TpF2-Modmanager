[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Version = "2.0.0",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

if ($Version -match '^\d+\.\d+$') { $Version = "$Version.0" }
if ($Version -notmatch '^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$') {
    throw "Ungueltige Version '$Version'. Erwartet wird z. B. 2.0 oder 2.0.0."
}
foreach ($command in @("node", "npm")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Das benoetigte Programm '$command' wurde nicht gefunden." }
}

Write-Host "Baue TpF2 Modmanager v$Version (Electron/JavaScript)" -ForegroundColor Cyan
if (-not $SkipInstall) {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "Installation der Node-Abhaengigkeiten fehlgeschlagen." }
}
if (-not (Test-Path node_modules)) { throw "node_modules fehlt. Starte das Skript ohne -SkipInstall." }

npm version $Version --no-git-tag-version --allow-same-version
if ($LASTEXITCODE -ne 0) { throw "Setzen der Version fehlgeschlagen." }

foreach ($directory in @("dist-electron")) {
    $target = Join-Path $PSScriptRoot $directory
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
}

npm run dist
if ($LASTEXITCODE -ne 0) { throw "Build fehlgeschlagen." }

$artifact = Join-Path $PSScriptRoot "dist-electron\TpF2-Modmanager-Setup-$Version.exe"
if (-not (Test-Path $artifact)) { throw "Das erwartete Artefakt fehlt: $artifact" }
$sizeMb = [Math]::Round((Get-Item $artifact).Length / 1MB, 1)
Write-Host "Build erfolgreich: $artifact ($sizeMb MB)" -ForegroundColor Green
