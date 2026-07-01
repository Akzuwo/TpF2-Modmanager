[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Version = "",
    [switch]$SkipInstall,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$packageFile = Join-Path $PSScriptRoot "package.json"
$lockFile = Join-Path $PSScriptRoot "package-lock.json"
$originalPackage = Get-Content -LiteralPath $packageFile -Raw
$originalLock = Get-Content -LiteralPath $lockFile -Raw
$packageVersion = ($originalPackage | ConvertFrom-Json).version
$originalCodeSigning = $env:CSC_IDENTITY_AUTO_DISCOVERY

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $packageVersion
}
if ($Version -match '^\d+\.\d+$') { $Version = "$Version.0" }
if ($Version -notmatch '^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$') {
    throw "Ungueltige Version '$Version'. Erwartet wird z. B. 2.0 oder 2.0.0."
}
foreach ($command in @("node", "npm")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Das benoetigte Programm '$command' wurde nicht gefunden." }
}

Write-Host "Baue TpF2 Modmanager v$Version (Electron/JavaScript)" -ForegroundColor Cyan
if (-not $SkipInstall) {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Installation der Node-Abhaengigkeiten fehlgeschlagen." }
}
if (-not (Test-Path node_modules)) { throw "node_modules fehlt. Starte das Skript ohne -SkipInstall." }

try {
    if ($Version -ne $packageVersion) {
        & npm.cmd version $Version --no-git-tag-version --allow-same-version
        if ($LASTEXITCODE -ne 0) { throw "Setzen der Version fehlgeschlagen." }
    }

    if (-not $NoClean) {
        $target = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "dist-electron"))
        $workspace = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
        if (-not $target.StartsWith("$workspace$([IO.Path]::DirectorySeparatorChar)", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unsicherer Build-Ausgabepfad: $target"
        }
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    }

    $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
    & npm.cmd run dist
    if ($LASTEXITCODE -ne 0) { throw "Build fehlgeschlagen." }
}
finally {
    if ($null -eq $originalCodeSigning) { Remove-Item Env:CSC_IDENTITY_AUTO_DISCOVERY -ErrorAction SilentlyContinue }
    else { $env:CSC_IDENTITY_AUTO_DISCOVERY = $originalCodeSigning }
    if ($Version -ne $packageVersion) {
        Set-Content -LiteralPath $packageFile -Value $originalPackage -NoNewline
        Set-Content -LiteralPath $lockFile -Value $originalLock -NoNewline
    }
}

$artifact = Join-Path $PSScriptRoot "dist-electron\TpF2-Modmanager-Setup-$Version.exe"
if (-not (Test-Path $artifact)) { throw "Das erwartete Artefakt fehlt: $artifact" }
$file = Get-Item $artifact
$sizeMb = [Math]::Round($file.Length / 1MB, 1)
$hash = (Get-FileHash $file.FullName -Algorithm SHA256).Hash
Write-Host "Build erfolgreich: $($file.FullName) ($sizeMb MB)" -ForegroundColor Green
Write-Host "SHA-256: $hash" -ForegroundColor Green
Write-Host "Update-Metadaten: $(Join-Path $PSScriptRoot 'dist-electron\latest.yml')" -ForegroundColor DarkGreen
Write-Host "Start: .\build.ps1  |  eigene Version: .\build.ps1 2.1.0" -ForegroundColor DarkGray
