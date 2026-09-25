# TODO — watermarks-remover

## Rodada R7 — 2026-09-25 — Fechamento dos resíduos da R6

Escopo fechado: só os 6 resíduos da revisão do DONE da R6. Nada de escopo novo; itens "mantidos"
na R6 não são reabertos.

Baseline FASE 0 (confere com o fim da R6): 744 coletados / 737 passed / 7 skipped
(`.venv\Scripts\python.exe -m pytest`, py3.14.4). `ruff check .` e `ruff format --check .`
limpos (ruff 0.16.3). `pip-audit` (`.venv`): 0 vulnerabilidades. `ponytail-debt`: 0 marcadores.

### Plano

| ID | Problema | Decisão preliminar | Arquivos | Risco |
|---|---|---|---|---|
| R7-01 | REC-05 diz "bandit B615 0 achados após" com default `"main"`. Investigado na FASE 0: o plugin B615 (bandit 1.9.4) **retorna sem achado quando `revision=` é expressão não-literal**. Antes de 2650c4d: 2 achados (L128/L129); depois: 0 — por falso negativo do scanner, não por pin. O default continuava `main`, que é mutável. | **Aplicar A.** Pinar `DEFAULT_MODEL_REVISION` no SHA de `main` do `facebook/opt-1.3b` (`3f5c25d0bc631cb57ac65913f76e22c2dfb61d62`, parado desde 2023-09-15). O pin vale só para `DEFAULT_MODEL`; `--model` customizado sem `--revision` segue em `main`. `--revision`/`MARKLLM_MODEL_REVISION` continuam como override. | `service/scripts/detect_text_watermark.py`, `tests/test_markllm_detect.py`, `.env.example`, `docs/DONE.md` | Médio. (a) Aplicar o SHA a um `MARKLLM_MODEL` de outro repo quebraria o carregamento; por isso a condição. (b) `--offline` com cache de outro commit falharia, mas hoje `main` é igual ao pin, então o cache existente continua servindo. (c) O B615 segue em 0 antes e depois (a chamada continua usando variável), então o scanner não prova o pin: a prova é o valor e o teste. |
| R7-02 | Smoke test da R6 (`--status` → `--wait` → `--stop`) só no chat | **Aplicar.** Repetir o smoke agora e colar a evidência em `### Verificação final — R6` | `docs/DONE.md` | Baixo. Usa a porta 8765; roda com a suíte parada. |
| R7-03 | `S101` no `ruff.toml` diz "asserts are idiomatic in this test suite", mas o ignore é global e cobre 2 asserts de produção (`rewrite_text.py:572,593`, ambos narrowing `is not None`) | **Aplicar.** Trocar o comentário pela justificativa da R6 (REC-04). Não reabrir. | `ruff.toml` | Nulo (só comentário). |
| R7-04 | `make test-cov-subprocess` nunca rodou via `make` | **Escalar (provável).** FASE 0: nenhum `make`/`gmake`/`mingw32-make` no PATH, WSL não instalado (só o stub), sem docker/podman/act. A CI não chama o target e os 10 commits não foram pushados. | `docs/TODO.md` | Nenhum risco se escalado. Corrigir o Makefile às cegas seria o único risco real da rodada, por isso não será feito. |
| R7-05 | `clean_ctrlregen.py` não aponta por que não tem teste de unidade | **Aplicar** o comentário no topo (opção preferida) | `service/scripts/clean_ctrlregen.py` | Nulo. Fica depois do shebang e antes da docstring, então `__doc__` é preservado. |
| R7-06 | R6-03 não registra que a R5 fechou a propagação de `_LOOPBACK_HOSTS` pela metade | **Aplicar** a nota ao lado de R6-03 | `docs/DONE.md` | Nulo. |

**Ordem:** R7-01 → R7-02 (smoke depois do commit de código, para o hash verificado ser o
mais recente) → R7-03 → R7-04 → R7-05 → R7-06 → validação (FASE 3) → seção R7 no DONE.

**Skills condicionais.** O gatilho de `/python-review` e `/code-reviewer` é "R6-02 tocar o
scorer (`image_meta.py`/`synthid_score`)". Isso não acontece: R7-05 só comenta
`clean_ctrlregen.py`, que não importa nenhum dos dois. Mesmo assim, os dois serão invocados
sobre o diff de R7-01, porque é código de produção. O `/python-type` só entra se o
`mypy --strict` no arquivo tocado piorar em relação ao baseline dele.

## Rodada R6 — 2026-09-22 — Fechamento de gaps

Concluída. Todos os itens (R6-01..R6-11, Q1..Q7, REC-01..REC-07) foram reconciliados —
aplicados, confirmados como já resolvidos, ou mantidos com decisão registrada. Nenhum item
foi escalado (🔴). Ver [`docs/DONE.md`](DONE.md) para o detalhe, commits e notas.

Nenhum item pendente nesta rodada. A próxima rodada começa lendo este arquivo; se estiver
vazio (como agora), não há escopo pré-existente e um novo prompt deve popular novos itens
aqui antes de qualquer edição.
