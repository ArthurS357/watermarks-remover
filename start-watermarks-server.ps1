<#
.SYNOPSIS
    Sobe, consulta ou encerra o servico HTTP local do watermarks-remover.

.DESCRIPTION
    Nao limpa nem processa nenhum arquivo -- so cuida do ciclo de vida do
    servico em http://127.0.0.1:8765. Todo o resto (inspect/clean/etc.) e
    feito pela skill.

    Modos (-Mode):

      start   (padrao) Roda o servidor em PRIMEIRO PLANO: stdout/stderr
              aparecem direto nesta console e o script fica vivo enquanto o
              servidor estiver rodando. Se o servico ja estiver no ar, avisa
              e sai com 0.

      wait    NAO inicia nada -- so aguarda o servico responder em /health,
              ate -TimeoutSeconds (padrao 30). Sai 0 quando responde, 1 no
              timeout. E a metade "espera" do `watermarks-server --wait`,
              que primeiro abre a janela do servidor e depois chama isto.

      status  Consulta uma vez e imprime "online" / "degraded" / "offline".
              Sai 0 quando o servico atende (online ou degraded -- degraded
              ainda limpa, so com menos ferramentas), 1 quando esta offline.

      stop    Encerra o servidor se estiver rodando. Idempotente: sai 0
              tambem quando nao havia nada para encerrar. Sai 1 quando
              RECUSA agir -- a porta/pid encontrados nao sao este servidor.

.EXAMPLE
    .\start-watermarks-server.ps1
    # primeiro plano, com logs (comportamento historico, inalterado)

.EXAMPLE
    watermarks-server --wait
    # comando global (ver watermarks-server.cmd): abre a janela de logs e
    # bloqueia ate o healthcheck passar

.EXAMPLE
    .\start-watermarks-server.ps1 -Mode status

.NOTES
    Para PARAR o modo start: Ctrl+C nesta console. O python compartilha o
    mesmo console, entao recebe o mesmo Ctrl+C e encerra junto.

    server.pid guarda o PID do processo que de fato escuta a porta 8765 (em
    alguns Pythons o .venv\Scripts\python.exe e um stub que reexecuta um
    filho, entao o PID e resolvido pela conexao TCP, nao pelo retorno do
    Start-Process). E o que -Mode stop usa.

    Funciona chamado de qualquer diretorio -- os caminhos saem de $PSScriptRoot.
#>

[CmdletBinding()]
param(
    [ValidateSet('start', 'wait', 'status', 'stop')]
    [string]$Mode = 'start',

    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 30,

    [ValidateRange(1, 65535)]
    [int]$Port = 8765,

    # -Mode wait: PID do processo que hospeda o servidor (a janela aberta pelo
    # watermarks-server.cmd). Zero = nao vigiar. Ver o bloco 'wait' abaixo.
    [int]$WatchPid = 0
)

$ErrorActionPreference = 'Stop'

$BaseUrl = "http://127.0.0.1:$Port"

# O pid file e por porta: uma instancia de teste em porta livre nao pode achar
# -- e matar -- o PID de um servidor real rodando na porta padrao.
$PidFile = Join-Path $PSScriptRoot $(if ($Port -eq 8765) { "server.pid" } else { "server.$Port.pid" })
$serverScript = Join-Path $PSScriptRoot "service\scripts\server.py"

# ---------------------------------------------------------------------------
# Sondas compartilhadas por todos os modos.
# ---------------------------------------------------------------------------

function Get-ServiceHealth {
    # $null quando o servico nao atende; senao o objeto de /health.
    try {
        return Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get -TimeoutSec 3
    }
    catch {
        return $null
    }
}

function Get-ServiceReadiness {
    # /readyz distingue "no ar e completo" de "no ar sem exiftool/qpdf/c2patool".
    # Servico antigo (sem /readyz) responde 404 -> tratamos como sem detalhe.
    try {
        return Invoke-RestMethod -Uri "$BaseUrl/readyz" -Method Get -TimeoutSec 3
    }
    catch {
        return $null
    }
}

function Wait-ForService {
    param([int]$Seconds, [System.Diagnostics.Process]$Process)

    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        # Um servidor que ja morreu nunca vai responder: falha na hora em vez
        # de queimar o timeout inteiro.
        # Uma ultima sondagem antes de desistir fecha a corrida em que o
        # /health subiu no mesmo instante em que o processo vigiado saiu.
        if ($Process -and $Process.HasExited) {
            $last = Get-ServiceHealth
            return [bool]($last -and $last.ok)
        }
        $health = Get-ServiceHealth
        if ($health -and $health.ok) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-ListeningPid {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty OwningProcess
    if ($listener) { return [int]$listener }
    return $null
}

function Test-IsServerProcess {
    # So o python rodando ESTE $serverScript (caminho absoluto, como o modo
    # start o lanca). O pid file pode estar velho (PID reciclado) e a porta
    # pode ser de outro programa (ex.: o proxy do Docker para o compose):
    # Stop-Process -Force neles perde trabalho alheio.
    param([int]$Id)
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $Id" -ErrorAction SilentlyContinue).CommandLine
    return [bool]($cmd -and $cmd.IndexOf($serverScript, [StringComparison]::OrdinalIgnoreCase) -ge 0)
}

# ---------------------------------------------------------------------------
# Modos que nao iniciam nada.
# ---------------------------------------------------------------------------

if ($Mode -eq 'status') {
    $health = Get-ServiceHealth
    if (-not $health -or -not $health.ok) {
        Write-Host "offline -- $BaseUrl nao respondeu." -ForegroundColor Yellow
        Write-Host "Para subir: watermarks-server --wait" -ForegroundColor Yellow
        exit 1
    }
    $ready = Get-ServiceReadiness
    if ($ready -and $ready.status -eq 'degraded') {
        $missing = @($ready.tools.PSObject.Properties |
                Where-Object { -not $_.Value.available } |
                ForEach-Object { $_.Name })
        Write-Host "degraded -- online em $BaseUrl (versao $($health.version)), sem: $($missing -join ', ')." -ForegroundColor Yellow
        Write-Host "Limpeza funciona; resultados de PDF/imagem ficam best-effort." -ForegroundColor Yellow
        exit 0
    }
    Write-Host "online -- $BaseUrl (versao $($health.version))." -ForegroundColor Green
    exit 0
}

if ($Mode -eq 'stop') {
    $target = Get-ListeningPid
    if (-not $target -and (Test-Path $PidFile)) {
        $recorded = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($recorded -match '^\d+$') { $target = [int]$recorded }
    }
    if ($target -and -not (Test-IsServerProcess $target)) {
        Write-Host "PID $target (porta $Port) nao e $serverScript; nada encerrado." -ForegroundColor Yellow
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        exit 1
    }
    if (-not $target) {
        Write-Host "Nada para encerrar: servico ja esta offline." -ForegroundColor Yellow
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        exit 0
    }
    Stop-Process -Id $target -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    Write-Host "Servidor encerrado (PID $target)." -ForegroundColor Yellow
    exit 0
}

function Show-SpawnDied {
    Write-Host "Erro: o servidor encerrou antes de responder em $BaseUrl." -ForegroundColor Red
    Write-Host "Rode em primeiro plano para ver a causa:" -ForegroundColor Red
    Write-Host ("  powershell -ExecutionPolicy Bypass -File " + '"' + "$PSCommandPath" + '"') -ForegroundColor Red
}

if ($Mode -eq 'wait') {
    # O servidor roda em OUTRA janela, entao este processo nao tem o handle
    # dele. -WatchPid traz o PID do cmd.exe que hospeda aquela janela: ele vive
    # exatamente enquanto o servidor viver, entao a saida dele e sinal de morte.
    # Pega python ausente, server.py faltando, porta ocupada e a recusa de bind
    # inseguro (exit 2) -- casos em que antes se esperava o timeout inteiro.
    $watched = $null
    if ($WatchPid -gt 0) {
        $watched = Get-Process -Id $WatchPid -ErrorAction SilentlyContinue
        if (-not $watched) {
            # Morreu antes mesmo de conseguirmos observar.
            $late = Get-ServiceHealth
            if ($late -and $late.ok) {
                Write-Host "Servico no ar em $BaseUrl (versao $($late.version))." -ForegroundColor Green
                exit 0
            }
            Show-SpawnDied
            exit 1
        }
    }

    if (Wait-ForService -Seconds $TimeoutSeconds -Process $watched) {
        $health = Get-ServiceHealth
        Write-Host "Servico no ar em $BaseUrl (versao $($health.version))." -ForegroundColor Green
        exit 0
    }

    if ($watched -and $watched.HasExited) {
        Show-SpawnDied
        exit 1
    }

    Write-Host "Erro: servico nao respondeu em $BaseUrl apos ${TimeoutSeconds}s." -ForegroundColor Red
    Write-Host "Veja a janela 'Watermarks Server' para o erro, ou rode em primeiro plano:" -ForegroundColor Red
    Write-Host "  powershell -ExecutionPolicy Bypass -File ""$PSCommandPath""" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Mode 'start' (padrao): servidor em primeiro plano nesta console.
# ---------------------------------------------------------------------------

$health = Get-ServiceHealth
if ($health -and $health.ok) {
    Write-Host "Servico ja esta em execucao em $BaseUrl (versao $($health.version))." -ForegroundColor Green
    exit 0
}

if (-not (Test-Path $serverScript)) {
    Write-Host "Erro: nao encontrei $serverScript." -ForegroundColor Red
    exit 1
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
}
else {
    $pythonExe = "python"
}

Write-Host "Iniciando servico com $pythonExe ..." -ForegroundColor Cyan

# -NoNewWindow: o python herda ESTA console, entao os logs dele saem aqui e o
# Ctrl+C da console chega nele junto (e como o servidor e encerrado).
$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList @($serverScript, "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $PSScriptRoot -NoNewWindow -PassThru

if (-not (Wait-ForService -Seconds $TimeoutSeconds -Process $proc)) {
    Write-Host "Erro: servidor nao respondeu em $BaseUrl apos ${TimeoutSeconds}s." -ForegroundColor Red
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}

$realPid = Get-ListeningPid
if (-not $realPid) { $realPid = $proc.Id }
$realPid | Out-File -FilePath $PidFile -Encoding ascii

Write-Host ""
Write-Host "Servidor iniciado em $BaseUrl (PID $realPid). Pressione Ctrl+C para encerrar." -ForegroundColor Green
Write-Host ""

try {
    # Sleep curto em laco (em vez de WaitForExit) para o PowerShell conseguir
    # processar o Ctrl+C entre as iteracoes.
    while (-not $proc.HasExited) { Start-Sleep -Milliseconds 500 }
}
finally {
    # Best-effort: se o script morrer antes do python, nao deixa servidor orfao.
    Get-Process -Id $realPid -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    Write-Host "Servidor encerrado." -ForegroundColor Yellow
}
