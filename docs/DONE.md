# DONE — watermarks-remover

Histórico append-only. Mais recente no topo.

## Rodada R8 — 2026-09-25 — Pin de revisão HF no MarkDiffusion

| Medida | Início | Fim |
|---|---|---|
| Testes coletados / passed / skipped | 750 / 743 / 7 | 755 / 748 / 7 (+5 testes, 0 regressões) |
| `ruff check .` e `ruff format --check .` | limpos | limpos |
| `mypy --strict markdiffusion_harness.py` | erros preexistentes | os mesmos (delta 0) |

| ID | Item | Commit | Nota |
|---|---|---|---|
| R8-01 | `markdiffusion_harness.py` carregava o modelo do `main` mutável | 7d053bd | Mesmo padrão do R7-01 (6a97ae9). Detalhe abaixo |

- **Pin:** `DEFAULT_MODEL_REVISION = "f71d7867a2745c420aa93441638b119c85995963"`, o `main`
  atual do `huanzi05/stable-diffusion-2-1-base`. O repo é um espelho numa conta pessoal e só
  tem 2 commits, `522fda6` ("initial commit") e `f71d786` (o upload), ambos de 2025-11-19.
  Qualquer cache existente já está nesse commit, então o `--offline` continua funcionando.
- **Resolução** (`_load_diffusion`, por onde passam watermark, detect e purify): usa
  `--revision` ou `MARKDIFFUSION_MODEL_REVISION` (vazio conta como não definido). Sem nenhum
  dos dois, usa o pin se `--model` for o `DEFAULT_MODEL` (comparação sem diferenciar
  maiúsculas) e `main` para outro modelo. `revision=` vai para as **duas** cargas: o
  scheduler (`subfolder="scheduler"`) e o pipeline. O `image_meta.run_markdiffusion_purify`
  só passa `--model` quando recebe um valor, e o default desse valor é `None`, então herda o
  pin. Nenhum código copia o nome do modelo, e por isso não precisa de guarda de drift.
- **Como bumpar:** fazer `GET https://huggingface.co/api/models/huanzi05/stable-diffusion-2-1-base/revision/main`,
  pegar o campo `sha` e atualizar `DEFAULT_MODEL_REVISION` e `PINNED` em
  `tests/test_markdiffusion_harness.py`.
- **Bandit:** o B615 dá 0 antes e 0 depois. O plugin só casa chamadas via
  `transformers`/`datasets`/`huggingface_hub`, e diffusers nunca é escaneado, então o scanner
  não prova nada aqui. A prova é o teste `test_cli_revision_resolution`: 5 casos, com fakes
  de `torch` e `diffusers` escritos só no upstream do teste (o processo do pytest não é
  poluído).
  - **RED no código antigo, pelo motivo certo:** 4 casos com `revision=None` nas duas
    cargas, e o caso de override com `unrecognized arguments: --revision`.
  - **Mutação feita pelo `python-reviewer`:** tirar `revision=` do scheduler ou do pipeline,
    tirar o `.lower()` e tirar o `or None` são todos pegos pelo teste.
- **`.env.example`:** documenta `MARKDIFFUSION_MODEL_REVISION`. O exemplo de
  `MARKDIFFUSION_MODEL` passou a ser o próprio default. O exemplo antigo
  (`runwayml/stable-diffusion-v1-5`) não era o default, então descomentá-lo derrubava o pin
  sem aviso.
- **Revisão:** `python-reviewer` deu PASS (0 CRITICAL/HIGH). A recomendação de testar o
  repasse de `args.revision` nos call sites de watermark e purify **não foi aplicada**: o
  repasse é trivial, e se um deles regredir o pin padrão continua valendo.
- **Limite conhecido:** o pacote upstream `markdiffusion` pode baixar outros modelos do Hub
  por conta própria (por exemplo, o captioner do SEAL), sem revisão fixa. Esses downloads
  estão fora do alcance deste pin e não foram verificados, porque o pacote não está
  instalado aqui.

## Rodada R7 — 2026-09-25 — Fechamento dos resíduos da R6

| Medida | Início | Fim |
|---|---|---|
| Testes coletados / passed / skipped | 744 / 737 / 7 | 750 / 743 / 7 (+6 testes, 0 regressões) |
| `ruff check .` e `ruff format --check .` | limpos | limpos |
| `pip-audit` (`.venv`) | 0 vulnerabilidades | 0 vulnerabilidades |
| Bandit, `-r service/scripts/` completo | Low 32 / Medium 1 / High 0 | igual |
| `mypy --strict detect_text_watermark.py` | 8 erros (preexistentes) | os mesmos 8 (delta 0) |

O plano foi escrito antes de qualquer edição, em a713bbd (`docs/TODO.md`).

| ID | Item | Commit | Nota |
|---|---|---|---|
| R7-01 | REC-05 ambíguo: pin real da revisão HF | 6a97ae9 | Opção **A**. Detalhe e evidência do bandit abaixo |
| R7-02 | Evidência do smoke test da R6 no DONE | e549636 | Smoke repetido em 6a97ae9. Seção `### Verificação final — R6` |
| R7-03 | Justificativa do `S101` no `ruff.toml` | a1e69a8 | O comentário antigo ("idiomatic in this test suite") estava errado, porque o ignore é global. Agora aponta para REC-04. Não reaberto |
| R7-04 | `make test-cov-subprocess` exercitado via `make` | 281b4b2 (bug da receita) · 🔴 `make` em si **escalado** | Ver abaixo e `docs/TODO.md` |
| R7-05 | Âncora da decisão de cobertura de `clean_ctrlregen.py` | 01e9bbb | Comentário entre o shebang e a docstring (`__doc__` intacto). 73% re-medido na R7 |
| R7-06 | Nota: a R5 fechou `_LOOPBACK_HOSTS` pela metade | 86d5559 | Linha adicionada na R6-03. Não reaberto |

### R7-01 — pin da revisão do modelo MarkLLM

- **Pin:** `DEFAULT_MODEL_REVISION = "3f5c25d0bc631cb57ac65913f76e22c2dfb61d62"`, que é o
  `main` atual do `facebook/opt-1.3b` (API do HF, `lastModified` 2023-09-15). Como o main de
  hoje é o próprio pin, um cache existente continua servindo com `--offline`.
- **Resolução** (`_load_algorithm`, por onde passam os 3 caminhos: detect, watermark e
  serve): `--revision` ou `MARKLLM_MODEL_REVISION` (vazio conta como não definido). Sem
  nenhum dos dois, usa o pin se `--model` for o `DEFAULT_MODEL` (comparação sem diferenciar
  maiúsculas, como os ids do Hub) e `main` para qualquer outro modelo. Os chamadores
  `rewrite_text.py` e `bench_synthid_text.py` passam a própria cópia do nome do modelo. Um
  teste de guarda falha se essa cópia divergir, porque a divergência cairia no `main` sem
  aviso.
- **Como bumpar:** fazer `GET https://huggingface.co/api/models/facebook/opt-1.3b/revision/main`,
  pegar o campo `sha` e atualizar `DEFAULT_MODEL_REVISION` e `PINNED` em
  `tests/test_markllm_detect.py`. O teste falha se só um dos dois mudar.
- **Bandit B615, antes e depois:**

  | Árvore | B615 |
  |---|---|
  | `2650c4d^` (antes do REC-05) | **2** (`detect_text_watermark.py` L128, L129) |
  | `8c6c851` (fim da R6, default `"main"`) | 0 |
  | `6a97ae9` / HEAD (pin real) | 0 |

  **O número não muda com o pin, e não é supressão.** O plugin
  (`bandit/plugins/huggingface_unsafe_download.py`, bandit 1.9.4) sai sem achado sempre que
  o kwarg `revision=` não é `ast.Constant`. Desde o 2650c4d a chamada usa uma variável, então
  o scanner nunca viu o valor, e o "0 achados após" da R6 era falso negativo. Demonstração
  num arquivo scratch: `revision="main"` literal **dispara**, e `revision=rev` com o mesmo
  valor fica em silêncio. A prova do pin é o valor mais o teste
  `test_cli_revision_resolution`: 5 casos, com tokenizer e modelo ambos na revisão
  resolvida. Esse teste ficou RED no código antigo, só no caso do pin.
- **Revisão:** `python-reviewer` deu PASS (0 CRITICAL/HIGH). Dos achados, a comparação
  case-insensitive, o assert duplo tokenizer+modelo e o caso de env vazia foram aplicados, e
  a recomendação de import do nome do modelo virou o teste de guarda de drift. O
  `code-reviewer` (inline) deu Approve.
- **Fora de escopo, observado:** `markdiffusion_harness.py` chama o `from_pretrained` do
  diffusers sem `revision`, e o B615 não cobre diffusers. É candidato a R8 e foi aberto como
  tarefa separada. **Resolvido na R8 (7d053bd).**

### R7-04 — `make test-cov-subprocess`

- **Ambiente:** não há `make`/`gmake`/`mingw32-make`. O WSL não está instalado (só o stub) e
  não há docker/podman/act. A CI não chama o target, e os commits não foram pushados. Por
  isso o `make` em si **não foi exercitado**. Fica escalado (🔴 em `docs/TODO.md`).
- **Bug encontrado mesmo assim** (receita rodada via bash): `COVERAGE_PROCESS_START=.coveragerc`
  é relativo. `test_rewrite_text.py:657` e `test_synthid_score.py:379` sobem Python com
  `cwd=service/scripts`, onde o coverage 7.15.4 inicia **em silêncio** com os defaults (sem
  `parallel`). O resultado é um `service/scripts/.coverage` não rastreado, com dado que nunca
  é combinado. Corrigido em 281b4b2 com `$(CURDIR)` absoluto para o rcfile **e** para
  `COVERAGE_FILE`. Só o rcfile absoluto não basta, porque o arquivo sufixado continuaria
  caindo no cwd do subprocesso.
- **Evidência (bash, não make):** depois do fix, 0 arquivos `.coverage*` em `service/` e
  `tests/`, e o `combine` roda na raiz. `clean_ctrlregen.py` 73%, `rewrite_text.py` 87%,
  `synthid_score_server.py` 67%, TOTAL 82%. Esses números são iguais aos de antes do fix,
  porque o dado perdido era só de linhas de import, já cobertas in-process.

### Skills invocadas (para cruzar com o transcript)

| Skill | Fase | Propósito |
|---|---|---|
| `ponytail:ponytail-review` | 0 | Critério de over-engineering aplicado ao diff da rodada: "Lean already. Ship." |
| `ponytail:ponytail-debt` | 0 | Ledger `ponytail:`: 0 marcadores |
| `python-pro` | 0 | Padrões do código do R7-01 (`str \| None`, sem default mutável) |
| `py-test-quality` | 0 | RED/GREEN do teste de revisão; medição via subprocess-coverage (R7-04/R7-05) |
| `py-security` | 0 | Análise do B615, bandit antes/depois, pip-audit |
| `py-code-health` | 0 | Nenhum código morto introduzido; comentário `S101` corrigido |
| `py-typing` | 0 | Contrato `revision: str \| None`; delta do `mypy --strict` = 0 |
| `caveman` | 0 | Estilo de saída |
| `python-test` | 0 | Baseline via agente `python-test-runner` (744/737/7) |
| `python-review` (condicional) | 2 | Agente `python-reviewer` no diff do R7-01: PASS. O gatilho literal ("R6-02 toca o scorer") não se aplica, porque `clean_ctrlregen.py` não importa `image_meta`/`synthid_score`. Invocado por ser código de produção |
| `code-reviewer` (condicional) | 2 | Revisão inline do R7-01: Approve |
| `python-type` (condicional) | — | **Não invocado.** O `mypy --strict` no arquivo tocado teve delta 0 (8 erros preexistentes, nenhum novo) |

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
