# TODO — watermarks-remover

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
