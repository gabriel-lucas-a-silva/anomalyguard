param(
    [string]$Distro = "Ubuntu-22.04",
    [int]$Usuarios = 10,
    [switch]$SemSite
)

$ErrorActionPreference = "Continue"
$raiz = Split-Path $PSScriptRoot -Parent
$demoCompose = "docker compose --env-file .env --env-file .env.override -f compose.yaml -f compose.observability.yaml -f compose.extras.yaml -f compose.anomalyguard.yaml"

function Passo($texto) { Write-Host "==> $texto" -ForegroundColor Cyan }

function Esperar($descricao, $segundos, [scriptblock]$pronto) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        if (& $pronto) { return }
        Start-Sleep -Seconds 3
    }
    throw "Tempo esgotado esperando: $descricao"
}

function DockerPronto { docker info *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Test-Path (Join-Path $raiz ".env"))) {
    throw "Falta o arquivo .env na raiz. Copie o .env.example para .env e preencha as senhas (veja o README)."
}

Passo "Docker Desktop"
if (-not (DockerPronto)) {
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Esperar "o Docker Desktop ficar pronto" 240 { DockerPronto }
}

Passo "OpenTelemetry Demo (WSL, $Distro)"
wsl -d $Distro -- bash -lc "cd ~/otel-demo && $demoCompose up -d"
if ($LASTEXITCODE -ne 0) { throw "Não consegui subir o Demo. Confira se ~/otel-demo existe no $Distro." }

Passo "Carga do Demo ($Usuarios usuários)"
$cargaOk = $false
for ($tentativa = 0; $tentativa -lt 20 -and -not $cargaOk; $tentativa++) {
    python (Join-Path $raiz "deploy\demo\set_load.py") $Usuarios 2>$null
    if ($LASTEXITCODE -eq 0) { $cargaOk = $true } else { Start-Sleep -Seconds 6 }
}
if (-not $cargaOk) { Write-Warning "Não consegui ajustar a carga. Rode depois: python deploy\demo\set_load.py $Usuarios" }

Passo "Regras de alerta e Alertmanager"
$wslRaiz = (wsl -d $Distro -- wslpath -a "$raiz").Trim()
wsl -d $Distro -- env "AG_V2=$wslRaiz" bash "$wslRaiz/deploy/demo/install_rules.sh"
wsl -d $Distro -- env "AG_V2=$wslRaiz" bash "$wslRaiz/deploy/demo/use_gateway.sh"

Passo "Back-end e banco de dados"
Push-Location $raiz
try { docker compose up -d --build; if ($LASTEXITCODE -ne 0) { throw "O docker compose do back-end falhou." } } finally { Pop-Location }
Esperar "o back-end responder" 180 {
    try { (Invoke-RestMethod "http://127.0.0.1:8100/api/health" -TimeoutSec 3).status -eq "ok" } catch { $false }
}

if (-not $SemSite) {
    Passo "Site"
    $web = Join-Path $raiz "web"
    if (-not (Test-Path (Join-Path $web "node_modules"))) { Push-Location $web; try { npm install --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw "O npm install falhou." } } finally { Pop-Location } }
    $ocupada = Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue
    if (-not $ocupada) {
        Start-Process powershell -WorkingDirectory $web -WindowStyle Minimized -ArgumentList "-NoProfile", "-Command", "npx vite --host 127.0.0.1 --port 5174"
    }
    Esperar "o site responder" 60 {
        try { (Invoke-WebRequest "http://127.0.0.1:5174/" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false }
    }
}

$saude = Invoke-RestMethod "http://127.0.0.1:8100/api/health"
Write-Host ""
Write-Host "Tudo no ar." -ForegroundColor Green
Write-Host "  Site:      http://127.0.0.1:5174"
Write-Host "  API:       http://127.0.0.1:8100/api/health"
Write-Host "  Narrador:  $(if ($saude.narrator) { 'Gemini ligado' } else { 'sem chave (texto automático)' })"
Write-Host "  Simulação: $(if ($saude.demo_mode) { 'ligada (botão Simular incidente)' } else { 'desligada' })"
Write-Host ""
Write-Host "Aviso: nos primeiros minutos depois de subir o Demo aparecem alertas de ruído de partida. Para um resultado limpo, espere uns 15 minutos antes de simular."
