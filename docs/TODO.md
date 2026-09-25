# TODO — watermarks-remover

## Rodada R9 — 2026-09-25 — Fechamento e verificação de uso

Baseline (FASE 0, HEAD `805270f`): 755 coletados / 748 passed / 7 skipped, `ruff check .` e
`ruff format --check .` limpos, `pip-audit` (`.venv`) 0 vulnerabilidades. Bate com o fim da R8.

| ID | Item | Estado encontrado na FASE 0 | Decisão preliminar |
|---|---|---|---|
| R9-01 | R7-04: `make test-cov-subprocess` via `make` de verdade | Sem `make`/`gmake`/`mingw32-make`, sem docker/podman/act; `wsl --status`: "não está instalado". CI (`ci.yml`) não chama o target | **Fechar pela opção 1:** step na CI (`ubuntu-latest` + 3.14) rodando o target e checando que nenhum `.coverage*` vaza para `service/`/`tests/`. Sem `git push` o run não acontece nesta rodada, então o estado honesto é 🟡 até o primeiro run. Se a busca em disco achar um GNU make, roda local também |
| R9-02 | Conflito de worktrees MarkDiffusion | `git worktree list`: só a principal. `.git/worktrees/` não existe. Branch local: só `main`. Sem stash. Nenhuma sessão do app com worktree deste repo. O R8 (7d053bd/805270f) foi commitado direto no `main` pela própria sessão da R7 | **Fechar sem ação:** não há worktree nem branch do cartão para reconciliar |
| R9-03 | `markdiffusion_harness.py` sem pin | Arquivo existe e **já tem o pin** desde a R8 (7d053bd): `DEFAULT_MODEL_REVISION`, `--revision`, `MARKDIFFUSION_MODEL_REVISION`, teste `test_cli_revision_resolution` | **Fechar como já resolvido na R8.** Só reexecutar o teste |

**Ordem:** R9-03 (só verificação) → R9-02 (só verificação) → R9-01 (edita `ci.yml`, commit) →
FASE 3 (suíte, ruff, pip-audit, smoke do serviço) → FASE 4 (DONE/TODO) → commit de docs.

**Riscos:**
- O step novo soma ~3–4 min ao job `ubuntu-latest`/3.14 e roda a suíte uma segunda vez. Se
  a medição via subprocesso quebrar no Linux, a CI fica vermelha no próximo push. Reverter é
  apagar o step.
- `PYTHON ?=` cai em `python3` no runner (sem `.venv`). O `setup-python` põe `python3` no
  PATH, então o fallback do Makefile é exercitado de propósito, sem override.
- Smoke do serviço usa a porta 8765: se algo já escuta nela, `--status` inicial não dá `offline`.

## Rodada R7 — 2026-09-25 — Fechamento dos resíduos da R6

Concluída, exceto pelo item abaixo. O plano original está em a713bbd, e o detalhe e os
commits estão em [`docs/DONE.md`](DONE.md#rodada-r7--2026-09-25--fechamento-dos-resíduos-da-r6).

### 🔴 Escalado

**R7-04 — rodar `make test-cov-subprocess` via `make` de verdade.**

- **Motivo:** esta máquina não tem nenhum `make`, o WSL não está instalado e não há
  docker/podman/act. A CI não chama o target, e sem `git push` não dá para usar a CI.
  Declarar "verificado" sem evidência é proibido.
- **O que já está verificado:** a receita, rodada via bash com `$(CURDIR)` trocado por
  `$PWD`, depois do fix 281b4b2 (paths absolutos de coverage).
- **O que falta verificar, e só o `make` mostra:** o parse da receita (TAB), a expansão de
  `$(CURDIR)` e a resolução de `$(PYTHON)`.
- **Como verificar:** na raiz, num POSIX (Linux, macOS, WSL ou CI) com `.venv/bin/python`,
  rodar `make test-cov-subprocess`. O esperado é pytest verde, `Combined N files`,
  `clean_ctrlregen.py` ≈73%, TOTAL ≈82% e **nenhum** `.coverage*` em `service/` ou `tests/`.
- **Nota Windows:** `PYTHON ?=` só detecta `.venv/bin/python`. Com a venv do Windows
  (`.venv\Scripts\python.exe`) o make cai em `python3`, que nesta máquina é o stub da
  Microsoft Store. Com make no Windows, passe `PYTHON=.venv/Scripts/python.exe`.
- **Decisão do usuário:** (a) `wsl --install` e rodar; (b) branch + passo de CI;
  (c) aceitar a evidência via bash e fechar.

## Rodada R6 — 2026-09-22 — Fechamento de gaps

Concluída. Todos os itens (R6-01..R6-11, Q1..Q7, REC-01..REC-07) foram reconciliados —
aplicados, confirmados como já resolvidos, ou mantidos com decisão registrada. Nenhum item
foi escalado (🔴). Ver [`docs/DONE.md`](DONE.md) para o detalhe, commits e notas.

Nenhum item pendente nesta rodada. A próxima rodada começa lendo este arquivo; se estiver
vazio (como agora), não há escopo pré-existente e um novo prompt deve popular novos itens
aqui antes de qualquer edição.
