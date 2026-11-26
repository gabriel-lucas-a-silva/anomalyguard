param(
    [string]$Distro = "Ubuntu-22.04",
    [switch]$Tudo
)

$ErrorActionPreference = "Continue"
$raiz = Split-Path $PSScriptRoot -Parent
$demoCompose = "docker compose --env-file .env --env-file .env.override -f compose.yaml -f compose.observability.yaml -f compose.extras.yaml -f compose.anomalyguard.yaml"

function Passo($texto) { Write-Host "==> $texto" -ForegroundColor Cyan }

docker info *> $null
$dockerLigado = ($LASTEXITCODE -eq 0)

Passo "Site"
$site = Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($site) { Stop-Process -Id $site.OwningProcess -Force; Write-Host "site parado" } else { Write-Host "site já estava parado" }

if ($dockerLigado) {
    Passo "Falhas simuladas e Alertmanager"
    $wslRaiz = (wsl -d $Distro -- wslpath -a "$raiz").Trim()
    foreach ($falha in "paymentFailure", "productCatalogFailure", "productCatalogLockContention") {
        wsl -d $Distro -- python3 "$wslRaiz/deploy/demo/set_flag.py" $falha off
    }
    wsl -d $Distro -- env "AG_V2=$wslRaiz" bash "$wslRaiz/deploy/demo/restore_alertmanager.sh"

    Passo "Back-end e banco de dados"
    Push-Location $raiz
    try { docker compose down } finally { Pop-Location }

    Passo "OpenTelemetry Demo"
    wsl -d $Distro -- bash -lc "cd ~/otel-demo && $demoCompose down"
} else {
    Write-Host "O Docker já estava desligado."
}

if ($Tudo) {
    Passo "Docker Desktop e WSL"
    Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
    wsl --shutdown
}

Write-Host ""
Write-Host "Parado. Os dados do histórico continuam guardados no volume do PostgreSQL." -ForegroundColor Green
if (-not $Tudo) { Write-Host "Para fechar também o Docker Desktop e o WSL: scripts\parar.ps1 -Tudo" }
