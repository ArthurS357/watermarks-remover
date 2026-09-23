@echo off
setlocal
REM ---------------------------------------------------------------------------
REM watermarks-server -- comando global para o servico watermarks-remover.
REM
REM Uso (de qualquer diretorio, em CMD ou PowerShell):
REM
REM   watermarks-server              Abre uma NOVA janela CMD com o servidor em
REM                                  primeiro plano e os logs ao vivo, e sai na
REM                                  hora. Ctrl+C naquela janela encerra tudo.
REM                                  Se o servico ja estiver no ar, so avisa.
REM
REM   watermarks-server --wait [N]   Mesma coisa, mas BLOQUEIA ate o healthcheck
REM                                  passar. Sai 0 quando o servico responde,
REM                                  1 no timeout (N segundos, padrao 30).
REM                                  E o modo para automacao / agentes.
REM
REM   watermarks-server --status     Imprime online / degraded / offline.
REM                                  Sai 0 quando atende, 1 quando offline.
REM
REM   watermarks-server --stop       Encerra o servidor. Idempotente (sai 0
REM                                  mesmo se ja estava parado).
REM
REM   watermarks-server --help       Este resumo.
REM
REM Instalacao: copie este .cmd para uma pasta do PATH (ex.: %USERPROFILE%\bin).
REM Se o .ps1 nao estiver ao lado do .cmd, o caminho fixo abaixo e usado.
REM Editar REPO se o repositorio mudar de lugar.
REM ---------------------------------------------------------------------------

set "REPO=E:\Projetos\Scripts\watermarks-remover"
set "PS1=%~dp0start-watermarks-server.ps1"
if not exist "%PS1%" set "PS1=%REPO%\start-watermarks-server.ps1"

if not exist "%PS1%" (
    echo Erro: nao encontrei start-watermarks-server.ps1.
    echo Ajuste a variavel REPO dentro de "%~f0".
    exit /b 1
)

set "TIMEOUTSEC=30"
if not "%~2"=="" set "TIMEOUTSEC=%~2"

if /i "%~1"=="--status" goto :status
if /i "%~1"=="--stop"   goto :stop
if /i "%~1"=="--wait"   goto :wait
if /i "%~1"=="--help"   goto :help
if /i "%~1"=="-h"       goto :help
if not "%~1"=="" (
    echo Argumento desconhecido: %~1
    goto :help
)

REM --- sem argumentos: comportamento historico, inalterado ---
call :probe
if not errorlevel 1 (
    echo Servico ja esta em execucao em http://127.0.0.1:8765
    exit /b 0
)
call :spawn
exit /b 0

:wait
call :probe
if not errorlevel 1 (
    echo Servico ja esta em execucao em http://127.0.0.1:8765
    exit /b 0
)
call :spawn
REM A janela sobe o servidor; este processo so espera o healthcheck. -WatchPid
REM entrega o PID daquela janela para o modo wait: se ela morrer (python
REM ausente, porta ocupada, bind recusado), a falha e imediata em vez de
REM esperar o timeout inteiro. Sem PID capturado, o wait so faz polling.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -Mode wait -TimeoutSeconds %TIMEOUTSEC% -WatchPid %SPAWNPID%
exit /b %errorlevel%

:status
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -Mode status
exit /b %errorlevel%

:stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -Mode stop
exit /b %errorlevel%

:help
echo Uso: watermarks-server [--wait [segundos] ^| --status ^| --stop ^| --help]
echo.
echo   (sem argumentos)   abre a janela do servidor e sai na hora
echo   --wait [segundos]  abre a janela e espera o /health responder (padrao 30s)
echo   --status           imprime online / degraded / offline
echo   --stop             encerra o servidor
exit /b 0

REM --- helpers ---

:probe
REM errorlevel 0 = servico no ar; 1 = offline.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { if ((Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 3).ok) { exit 0 } } catch {}; exit 1"
exit /b %errorlevel%

:spawn
REM Start-Process (e nao o `start` do cmd) de proposito: `start` abre a janela,
REM mas o filho HERDA os handles deste processo. Um chamador que capture a
REM saida (`watermarks-server --wait > log.txt`, ou um agente lendo stdout)
REM ficaria pendurado ate o SERVIDOR morrer -- um pipe so fecha quando o ultimo
REM detentor solta. Start-Process cria o processo com console proprio e sem
REM herdar handle, entao o pipe fecha quando este .cmd termina.
REM O caminho vai por %PS1% (variavel de ambiente, ja setada acima) e as aspas
REM por [char]34, para nao aninhar aspas dentro das aspas do cmd.
REM -PassThru devolve o PID da janela; o for /f captura para %SPAWNPID%. O pipe
REM do for /f e seguro justamente por causa do Start-Process: o neto nao herda
REM handle, entao este powershell fecha o pipe assim que imprime o PID.
set "SPAWNPID=0"
for /f "usebackq tokens=1" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$q=[char]34; (Start-Process cmd.exe -ArgumentList '/c', ('title Watermarks Server & powershell -NoProfile -ExecutionPolicy Bypass -File ' + $q + $env:PS1 + $q) -PassThru).Id"`) do set "SPAWNPID=%%i"
exit /b 0
