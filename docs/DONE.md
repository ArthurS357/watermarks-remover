# DONE — watermarks-remover

Histórico append-only. Mais recente no topo.

## Rodada R6 — 2026-09-22 — Fechamento de gaps

Baseline no início da rodada: 738 coletados / 731 passed / 7 skipped. Baseline no fim:
744 coletados / 737 passed / 7 skipped (net +6 testes, 0 regressões). `ruff check .` e
`ruff format --check .` limpos. `pip-audit` no `.venv` local: 0 vulnerabilidades (era 4
CVEs em `pip`). `mutmut` não roda nativo no Windows (upstream: sem suporte, exige WSL) —
não executado; registrado como limitação do ambiente, não pulado por escolha.

| ID | Item | Commit | Nota |
|---|---|---|---|
| R6-11 / Q1 | Launcher untracked/gitignored — versionado | 48d3c25 | `.gitignore`/`.gitattributes` abertos; `REPO` já era fallback, sem mudança; corrige link 404 em AI_INTEGRATION.md |
| Q2 | Copiar `.cmd` para `%USERPROFILE%\bin\` | — (ação local, não é commit) | hash SHA-256 confirmado idêntico após cópia |
| Q3 | SECURITY.md risco aceito ctrlregen + CI pip-audit não-bloqueante | e200d03 | job `continue-on-error: true` só para `requirements-ctrlregen.txt` |
| Q4 | Sidecar SynthID recusa bind não-loopback sem chave | f18db09 | TDD: 6 testes novos, mesmo padrão de `_refuses_insecure_bind` do server.py |
| Q5 | Lista dos 11 itens (R6-01..R6-11) | — | colada em `docs/TODO.md` no bootstrap desta rodada |
| Q6 | `uv pip install --upgrade pip` na `.venv` local | — (ação local, não é commit) | pip 26.0.1 → 26.2.1; `pip-audit` 4 CVEs → 0 |
| Q7 | `--stop` sai com 1 em recusa | 48d3c25 | RED confirmado antes do fix; 3 testes de pinning atualizados (`test_stop_never_kills_*`) |
| R6-01 | Cobertura via subprocess-coverage (opt-in) | 9cfc3a9 | `make test-cov-subprocess`; verificado manualmente (`inspect_file.py` 0%→40%) já que `make` não está disponível neste ambiente |
| R6-02 | Testes para `clean_ctrlregen.py` | 9cfc3a9 (mesma wiring) | resolvido pela medição, não por testes novos: 73% via subprocess-coverage, acima da meta de 40% — mock de CLI descartado, não valia a pena |
| R6-03 | `_LOOPBACK_HOSTS` duplicado | (já resolvido na R5) | confirmado: `common.LOOPBACK_HOSTS` já era a única definição; só faltava propagar a 3 chamadores, feito em 251bf26. **Nota (R7-06):** a R5 centralizou em `common.py` mas não propagou a 3 chamadores. Rodadas futuras: "centralizado em X" ≠ "todos os chamadores usam X". |
| R6-04 | `logging` stdlib no serviço | — (mantido) | `eprint()` cobre CLI e serviço; migrar é projeto separado |
| R6-05 | Refatorar 4 funções grandes (C901) | — (mantido) | 44 funções C901 são despacho inerente; ponytail degrau 1 |
| R6-06 | README subdocumenta flags CLI | 8f495f7 | `--json`, `--in-place`, `--stylometry`/`--threshold` |
| R6-07 | Consolidar config em `pyproject.toml` | — (mantido) | config espalhada funciona; consolidar é modernização |
| R6-08 | Verificação funcional de `pixel_backends` | — (mantido) | `verified: false` é a resposta certa |
| R6-09 | `/capabilities` enriquecido | — (mantido) | contrato bool intocável |
| R6-10 | `--wait` distinguir *por que* morreu | — (mantido) | trade-off correto |
| REC-01 | 401/413 sem drenar corpo | — (mantido) | exige decisão arquitetural |
| REC-02 | Slowloris no corpo | — (mantido) | exige refatoração do loop |
| REC-03 | 44 funções > C901 10 | — (mantido, = R6-05) | |
| REC-04 | `S101` ignorado globalmente | — (mantido) | `assert` em produção é narrowing deliberado |
| REC-05 | HF Hub sem pin de revisão (B615) | 2650c4d | `--revision`/`MARKLLM_MODEL_REVISION`, default `"main"` (sem mudança de comportamento); bandit B615 0 achados após. **Corrigido na R7 (R7-01):** esse "0" era falso negativo. O B615 não avalia `revision=` não-literal, e o default ainda era o `main` mutável. O pin real está na seção R7. |
| REC-06 | 17 env vars internas sem doc | 8f495f7 | ~20 vars documentadas em `.env.example` (incluindo as 2 novas desta rodada) |
| REC-07 | `urlopen_no_redirect` não valida scheme | — (mantido) | chamadores já validam |
| — | Reconciliação de 19 arquivos + trabalho da R5 não commitado | 251bf26, c899a59, 7824c98 | bearer-token-via-redirect, non-ASCII API key, Content-Length não-decimal, spec OpenAPI, cleanup de código |
| — | `docs/TODO.md` + `docs/DONE.md` criados | (este commit) | rastreamento de escopo passa a viver em arquivos, não no prompt |

### Verificação final — R6

O smoke test original da R6 ficou só no chat, sem registro. Foi **repetido na R7 (R7-02)**
em 2026-09-25 03:30 -03:00, no commit `6a97ae9` (R6 + o pin do R7-01), usando a cópia
`%USERPROFILE%\bin\watermarks-server.cmd`, que é byte a byte igual à do repo:

| Comando | Saída | Exit |
|---|---|---|
| `watermarks-server --status` | `offline -- http://127.0.0.1:8765 nao respondeu.` | 1 |
| `watermarks-server --wait` | `Servico no ar em http://127.0.0.1:8765 (versao dev).` | 0 |
| `watermarks-server --status` | `degraded -- online em http://127.0.0.1:8765 (versao dev), sem: c2patool.` | 0 |
| `watermarks-server --stop` | `Servidor encerrado (PID 21900).` | 0 |
| `watermarks-server --status` | `offline -- http://127.0.0.1:8765 nao respondeu.` | 1 |

O resultado `degraded` é o esperado nesta máquina, porque o `c2patool` não está instalado. A
limpeza funciona e PDF/imagem ficam best-effort (contrato da R6: `degraded` sai 0).
