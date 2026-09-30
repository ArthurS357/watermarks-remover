# DONE — watermarks-remover

Histórico append-only. Mais recente no topo.

## Estado do sistema — 2026-09-30

| ID | Item | Estado | Commit |
|---|---|---|---|
| R10-01 | Sinais de texto (21) | ✅ fechado | 3f7aff8 |
| R10-02 | Sinais de código (16, dos quais 4 só de TS/JS) | ✅ fechado | 6a4ca93, dd07e5d, 70b3c2f |
| R10-05 | Carregadores de formato e processo filho isolado | ✅ fechado | c3f90d0, c65b66b, f4a7b27 |
| R10-03 | CLI `detect_ai_patterns` | ✅ fechado | 14fe38c |
| R10-04 | CLI `measure_skill_effectiveness` | ✅ fechado | 969ece2 |
| R10-06 | `pyproject.toml` com `[dependency-groups].formats` | ✅ fechado | 34b5826 |
| R10-07 | README, seção "Detecção estilométrica" | ✅ fechado | ff7916f, f3db001 |
| R10-08 | `.gitignore` libera `tools/` e `pyproject.toml` | ✅ fechado | 3f7aff8, 34b5826 |
| R10-09 | Dogfooding e registro | ✅ fechado | este commit |

| Medida | Valor final (HEAD `f3db001`) |
|---|---|
| Testes, `.venv` sem o grupo `formats` | 1262 coletados / 1192 passed / 70 skipped, 0 falhas, exit 0 |
| Testes, `.venv` com `formats` instalado | 1262 coletados / 1254 passed / 8 skipped, 0 falhas, exit 0 |
| Os 755 de antes | Os 748 passed seguem passando e os 7 skips são os mesmos. Os outros skips são da R10: 62 sem as libs opcionais e 1 de symlink sem privilégio no Windows |
| Cobertura de ramo (com `formats`, `--cov=tools`) | `tools/stylometry/*.py` 100%. Os 2 CLIs 99%, só falta o `sys.exit(main())`, que roda nos testes de subprocess |
| `ruff check .` e `ruff format --check .` | limpos (117 arquivos) |
| `mypy --strict` nos 7 arquivos de `tools/` | limpo |
| `pip-audit` (`.venv`) | 0 vulnerabilidades, também com `formats` instalado. Eram 3 no início (`urllib3` 2.7.0) |
| Bandit, `-r tools/` | 0 achados em 2000 linhas. `-r service/scripts/` segue em Low 32 / Medium 1 / High 0 |
| `service/` e `skills/` | Sem diff desde o baseline `2302a15` |

**R10 pronta para uso: sim.** Os dois scripts rodam sem o grupo opcional (avisam e seguem) e com ele. Nenhum arquivo do serviço HTTP nem das skills mudou, e nenhum `git push` foi feito.

**Riscos residuais que não bloqueiam uso:**
- **Limiares sem calibração.** Pesos, faixas e o divisor 8 do score são escolha desta ferramenta, sem corpus. O `disclaimer` diz isso em toda saída. O repositório pontua alto contra si mesmo nos próprios documentos.
- **Primeiro run da CI pendente.** Nada foi pushado. O teste de symlink (sem privilégio aqui) e os de POSIX só rodam no Linux/macOS da CI. O de junction só roda no Windows.
- **Memória do processo filho sem teto do SO.** O Windows não tem `RLIMIT`. O que limita o dano é o teto por stream do PDF (5 MB), o teto de 20 MB descomprimidos do DOCX e o timeout de 30 s, não um limite em bytes.
- **HTML lido no processo pai, sem timeout.** 1 MB de `<` levou 2,4 s no Python 3.14.4. O teto de 1 MB limita, mas não medi os patches antigos do 3.12 da CI.
- **Vazamento de estado entre testes.** O de `PIL` falso foi corrigido (3634dbc). Outro teste antigo pode deixar sujeira parecida e só aparecer quando algo novo importar a lib.
- **Guarda do `.gitignore` parcial.** O teste cobre `pyproject.toml` e `tools/**/*.py`. Uma pasta nova na raiz continua nascendo ignorada até entrar na allowlist.
- **Medição do `/clean-user-facing-text` é n = 1**, feita por mim e sobre um documento técnico cheio de tabelas. Não generaliza.

## Rodada R10 — 2026-09-30 — Detecção estilométrica e medição de efetividade

| Medida | Início (`2302a15`) | Fim (`f3db001`) |
|---|---|---|
| Testes coletados / passed / skipped | 755 / 748 / 7 | 1262 / 1192 / 70 sem `formats`; 1262 / 1254 / 8 com `formats` (+507 testes, 0 regressões) |
| `ruff check .` e `ruff format --check .` | limpos (102 arquivos) | limpos (117 arquivos) |
| `pip-audit` (`.venv`) | 3 (`urllib3` 2.7.0) | 0 |

O plano foi escrito antes de qualquer edição, em 868478e (`docs/TODO.md`). As diferenças entre ele e o que saiu estão em "Ajustes durante a execução" (J1 a J11), no mesmo arquivo.

### O que saiu

- **`tools/detect_ai_patterns.py`** e o pacote `tools/stylometry/` (`text.py`, `code.py`, `loaders.py`, `isolate.py`): 37 sinais com linha e trecho, em texto (`.md .txt .html .docx .pdf`) e código (`.py .ts .tsx .js .jsx`). Determinístico: regex, `ast`, `tokenize`, tree-sitter quando instalado. A saída nunca traz `is_ai`: só `signals`, `score`, `confidence` e `disclaimer`.
- **`tools/measure_skill_effectiveness.py`**: antes/depois de arquivo ou pasta (pareada pelo caminho relativo), com `delta`, sinais eliminados, restantes e introduzidos, faixa de `effectiveness` e uma `recommendation` que nomeia o pior sinal que sobrou e o que fazer com ele.
- **`pyproject.toml`** só com `[dependency-groups].formats`. Sem `[project]` e sem `[tool.*]`: conferido que `ruff`, `pytest` e `coverage` continuam lendo `ruff.toml`, `pytest.ini` e `.coveragerc`.
- **Testes** em arquivos próprios (`test_stylometry_text/code/loaders/isolate.py`, `test_detect_ai_patterns.py`, `test_measure_skill_effectiveness.py`, `test_pyproject_formats_group.py`), todos abaixo de 800 linhas.

### Registros pedidos

- **`urllib3` (ação local, como a Q6 da R6).** O `pip-audit` do baseline achou 3 vulnerabilidades no `urllib3` 2.7.0 (CVE-2026-97687, 97688 e 97689, correção em 2.8.0). Ele é transitivo do `pip-audit`/`requests` na `.venv` de dev e não entra no serviço. Na retomada o usuário mandou subir: `uv pip install --upgrade urllib3` levou a 2.8.0 e o `pip-audit` voltou a 0. Depois, com o grupo `formats` instalado, continuou em 0.
- **Teto de blocos.** O prompt fala em 330k. O repo não tinha esse número; tomei como o máximo de blocos que cabe no teto de 1 MB (1 000 000 / 3 bytes = 333 333, com blocos `a\n\n`). O teto real é `MAX_BLOCKS = 50_000`. Medido: 50k blocos levam 1,57 s; um arquivo de 1 MB com 333 mil blocos leva 2,85 s (analisa os 50k primeiros e avisa na saída), contra 10,23 s se o teto subisse para cobrir tudo. Um documento real de 1 MB tem ~21 mil blocos (1,93 s). **Decisão: manter 50k.** Se o número que você tinha em mente era outro, diga.
- **`.gitignore` deny-by-default como padrão de falha recorrente.** O `.gitignore` é `/*` mais uma allowlist, então todo arquivo ou pasta novo na raiz nasce ignorado em silêncio: `git status` não mostra e `git add .` não reclama. Já tinha mordido na R6 (launcher, R6-11, 48d3c25) e mordeu duas vezes aqui, com `tools/` (3f7aff8) e `pyproject.toml` (34b5826). Defesa agora: `test_files_the_round_adds_are_not_swallowed_by_the_deny_by_default_gitignore` falha se `pyproject.toml` ou qualquer `tools/**/*.py` estiver ignorado. Ao criar algo na raiz, rode `git check-ignore <caminho>` (sem `-v`: com ele o `git` também lista os padrões de negação e sai com 0 mesmo para arquivo liberado).
- **Achado de teste, não de produto.** `tests/test_markdiffusion_harness.py`, anterior à R10, deixava um `PIL` falso em `sys.modules`. Com `formats` instalado, o primeiro `import pypdf` (que lê `PIL.__version__`) falhava: 10 testes de PDF quebraram na suíte completa e passavam isolados. Achado por bissecção e corrigido com uma fixture autouse (3634dbc), sem mudar nenhum assert.

### Revisões

- **`python-review`** sobre `tools/stylometry/`: FAIL com 7 ALTA (21 bytes travando o parser TSX, `obvious_comment` com 12 s em 40 KB, 3 regex quadráticos, `RecursionError` escapando, zip-bomb pelo cabeçalho). Reproduzidos e corrigidos em dd07e5d, c65b66b e c3f90d0, cada um com teste de regressão.
- **`code-reviewer`** sobre o diff acumulado (868478e..14fe38c): 0 crítico, 2 maior, 1 menor, **Request Changes**. Reproduzidos antes de corrigir: um `.docx` com stream deflate corrompido levantava `zlib.error`, que escapava de `load()` e derrubava o scan inteiro; `os.walk(followlinks=False)` ainda entra em junction do Windows; nome de arquivo com escape chegava ao terminal e ao markdown. Corrigidos em f4a7b27.

### Dogfooding (FASE 4)

Comando exato do prompt, com a venv que tem `formats`: `python tools/detect_ai_patterns.py . --format md --output stylometry-report.md`. Rodou em 4 s, exit 0, 140 arquivos (html 1, javascript 1, markdown 28, python 93, text 16, tsx 1). O relatório **não foi commitado** (o `.gitignore` já o ignora). Medido no HEAD `70b3c2f`.

**A primeira execução achou um erro do detector.** O sinal mais frequente era `type_hint_on_trivial_local`, em 37 arquivos, quase todos `x: list[T] = []` ou `x: T | None = None`, onde o `mypy --strict` exige a anotação. O sinal foi restringido à anotação que só repete o tipo de um literal escalar (70b3c2f) e caiu para 1 arquivo (a fixture). Os números abaixo são da segunda execução.

**Os 5 maiores scores** (3 são fixtures de teste, carregadas de sinais de propósito):

| # | Arquivo | Score | Confiança | Sinais dominantes |
|---|---|---|---|---|
| 1 | `tests/fixtures/stylometry/text_ai_like.md` | 0.89 | medium | `template_heading`, `em_dash_to_comma_ratio`, `paragraph_uniformity` (todos high) |
| 2 | `tests/fixtures/stylometry/code_ai_like.py` | 0.67 | medium | `obvious_comment` (high, 7), `comment_density` (high, 0.28) |
| 3 | `README.md` | 0.43 | high | `bold_lead_in` (high, 43), `comparison_table_symmetry` (medium) |
| 4 | `tests/fixtures/stylometry/code_ai_like.tsx` | 0.39 | low | `explicit_return_types_on_arrow` (medium), `jsdoc_on_trivial_type`, `as_const_everywhere` |
| 5 | `docs/DONE.md` | 0.35 | high | `bold_lead_in` (high, 21), `comparison_table_symmetry` (medium) |

Sem as fixtures, a ordem é `README.md` 0.43, `docs/DONE.md` 0.35, `docs/TODO.md` 0.34, `skills/remove-ai-marks/references/vendor-notes.md` 0.34 e `.github/ISSUE_TEMPLATE/bug_report.md` 0.31 (confiança low). O script de serviço mais alto é `service/scripts/image_meta.py`, com 0.42 antes da correção do J7.

**Sinais que o repo dispara em si mesmo, por número de arquivos:** `bold_lead_in` (11, high), `em_dash_to_comma_ratio` (10, high), `template_heading` (8, high), `comment_density` (7, high), `excessive_params` (6, high), `generic_try_except` (5, high). Nos documentos é o negrito de abertura e as tabelas, que são o formato que este repo usa; no código do serviço são funções com muitos parâmetros (`rewrite` tem 20) e `except Exception: pass`.

**Efetividade medida do `/clean-user-facing-text` sobre o `docs/DONE.md`** (versão do HEAD `70b3c2f`, antes desta seção). A skill foi invocada via `Skill`, e a cópia reescrita foi feita por mim, seguindo-a, fora do git. A passada `inspect_text.py` / `clean_text.py` não achou caractere invisível (0 no original e 0 na cópia, byte a byte idêntica depois do `clean_text.py`). Os 227 trechos em crase e os 27 hashes do original estão na cópia sem perda.

| | Antes | Depois |
|---|---|---|
| Score | 0.3531 | 0.3663 |
| Delta | | **+0.0132** |
| Efetividade | | **low** (confiança high) |
| Eliminado | | `em_dash_to_comma_ratio` |
| Restantes | | `bold_lead_in` (high, 21 → 21), `comparison_table_symmetry` (medium) |
| Introduzido | | `em_dash_density` (low, 0.243) |

O resultado é coerente com o que a skill faz: ela reescreve a prosa e preserva formatação, código, tabelas e identificadores, e é exatamente a estrutura markdown que dá o score deste arquivo (negrito de abertura e tabela). Os travessões que sobraram estão em títulos e células de tabela, protegidos. Como a cópia ficou com frases mais longas, eles passaram a pesar mais por frase, o que acendeu `em_dash_density`. **Limites:** n = 1, aplicado por mim, em documento técnico atípico, e desfiz a quebra de linha dura (350 → 249 linhas), o que não é pedido da skill. Mostra o efeito desta aplicação, não o da skill em geral.

### Skills invocadas (para cruzar com o transcript)

Extraído do transcript da sessão: 13 chamadas à tool `Skill`.

| # | Skill | Fase | Propósito |
|---|---|---|---|
| 1 | `ponytail-review` (sem namespace) | 0 | **Falhou:** `Unknown skill`. O nome certo é `ponytail:ponytail-review` |
| 2 | `ponytail:ponytail-review` | 0 | Gate. Régua de over-engineering da rodada |
| 3 | `ponytail:ponytail-debt` | 0 | Gate. Ledger `ponytail:`: 0 marcadores em `tools/` e `tests/`, conferido de novo na FASE 5 |
| 4 | `python-pro` | 0 | Gate. Padrões Python 3.12+ (alvo `py312`) no código novo |
| 5 | `py-test-quality` | 0 | Gate. Cobertura de ramo: 100% em `tools/stylometry/`, 99% nos CLIs |
| 6 | `py-security` | 0 | Gate. Entrada hostil (zip-bomb, ReDoS, processo filho), `bandit` em `tools/` (0), `pip-audit` (o `urllib3`) |
| 7 | `py-code-health` | 0 | Gate. `vulture` em `tools/`: 1 item, falso positivo (`attrs`, parâmetro obrigatório de `HTMLParser.handle_starttag`) |
| 8 | `py-typing` | 0 | Gate. `mypy --strict` limpo nos 7 arquivos de `tools/` |
| 9 | `caveman` | 0 | Gate. Estilo de saída |
| 10 | `python-test` | 0 | Gate. Baseline 755 / 748 / 7 e leitura das execuções da suíte, com e sem `formats` |
| 11 | `python-review` (condicional) | 2 | Gatilho: código que lê arquivo não confiável. `python-reviewer`: FAIL, 7 ALTA, corrigidas |
| 12 | `code-reviewer` (condicional) | retomada, após o bloco 4 | Gatilho atingido no bloco 4 e **omitido até a retomada**. Request Changes, corrigido em f4a7b27 |
| 13 | `clean-user-facing-text` | 4 | Objeto da medição de efetividade. Não faz parte do gate |
| — | `python-type` (condicional) | — | **Não invocado.** O `mypy --strict` passou sem erro, então não havia erro de tipo para resolver |

## Estado do sistema — 2026-09-25

| ID | Item | Estado | Commit |
|---|---|---|---|
| R9-01 | R7-04: `make test-cov-subprocess` via `make` de verdade | 🟡 mitigado: step na CI, primeiro run pendente do push | 1ec955a |
| R9-02 | Conflito de worktrees MarkDiffusion | ✅ fechado: não havia conflito | — (nada a mudar) |
| R9-03 | `markdiffusion_harness.py` sem pin | ✅ fechado: já resolvido na R8 | 7d053bd |

| Medida | Valor final (HEAD `1ec955a`) |
|---|---|
| Testes | 755 coletados / 748 passed / 7 skipped, 0 falhas, exit 0 |
| Cobertura (receita do `test-cov-subprocess`, via bash) | TOTAL **83%** (R7: 82%) |
| `ruff check .` e `ruff format --check .` | limpos (102 arquivos) |
| `pip-audit` (`.venv`) | 0 vulnerabilidades |
| Bandit, `-r service/scripts/` (1.9.4) | Low 32 / Medium 1 / High 0, igual à R7. B615: 0 |
| Smoke do serviço | 8/8 verdes (tabela na R9) |

**Sistema pronto para uso: sim.** Suíte, lint, auditoria e smoke do serviço estão verdes. O
único item aberto (R9-01) é da ferramenta de cobertura de dev e não afeta nenhum caminho de uso.

**Riscos residuais que não bloqueiam uso (cards futuros):**
- **R9-01:** o `make` real só roda no primeiro push. Vira ✅ se o step ficar verde. Se falhar,
  o erro mostra qual das 3 coisas quebrou: o parse da receita (TAB), a expansão de `$(CURDIR)`
  ou o fallback `PYTHON ?= python3`.
- O pacote upstream `markdiffusion` pode baixar outros modelos do Hub sem revisão fixa (por
  exemplo, o captioner do SEAL). Isso fica fora do nosso código e é o limite já registrado na
  R8.
- Os 7 skips dependem do ambiente: 4 precisam de privilégio de symlink (WinError 1314), 2
  exigem POSIX e 1 precisa do `scipy`, que não está na `.venv`. Dois deles são testes de
  hardening (`safe_write`/`backup_path` com symlink), que **nunca rodam nesta máquina**. Só a
  CI em Linux/macOS os exercita.
- `degraded` no `--status` porque o `c2patool` não está instalado. É o esperado (contrato da
  R6).
- Os itens mantidos nas R5/R6/R7 (REC-01, REC-02, REC-04, REC-07 e R6-04..R6-10) continuam
  mantidos e não foram reabertos.

## Rodada R9 — 2026-09-25 — Fechamento e verificação de uso

| Medida | Início (`805270f`) | Fim (`1ec955a`) |
|---|---|---|
| Testes coletados / passed / skipped | 755 / 748 / 7 | 755 / 748 / 7 (0 testes novos, 0 regressões) |
| `ruff check .` e `ruff format --check .` | limpos | limpos |
| `pip-audit` (`.venv`) | 0 | 0 |

O plano foi escrito antes de qualquer edição, em c85d942 (`docs/TODO.md`).

| ID | Item | Commit | Nota |
|---|---|---|---|
| R9-01 | R7-04: `make` de verdade no `test-cov-subprocess` | 1ec955a | Opção 1 (step na CI). Detalhe abaixo |
| R9-02 | Worktree do cartão MarkDiffusion | — | Não havia worktree nem branch. Nenhuma ação |
| R9-03 | Pin do `markdiffusion_harness.py` | 7d053bd (R8) | Premissa desatualizada: a R8 já tinha fechado o item |

### R9-01 — `make test-cov-subprocess` na CI

- **Por que a opção 1:** ninguém na máquina roda `make`. `make`, `gmake`, `mingw32-make`,
  docker, podman e act não estão no PATH. Uma busca recursiva (profundidade 7) por
  `make.exe`/`gmake.exe`/`mingw32-make.exe` também não achou nada. Ela cobriu `Program Files`
  (x64 e x86), `ProgramData`, `%LOCALAPPDATA%` e `%APPDATA%`, e também `C:\msys64`,
  `C:\cygwin64`, `C:\Strawberry` e scoop, onde esses existissem. O `wsl --status` responde que o WSL "não está
  instalado". Isso descarta as opções 2 (a CI já existe) e 3 (container).
- **Step adicionado** em `.github/workflows/ci.yml`, job `test`, depois do `Test`:

  ```yaml
  - name: Subprocess coverage (make test-cov-subprocess)
    if: matrix.os == 'ubuntu-latest' && matrix.python-version == '3.14'
    run: |
      make test-cov-subprocess
      test -z "$(find service tests -name '.coverage*')"
  ```

  O step roda sem override de `PYTHON` de propósito. O runner não tem `.venv`, então o
  fallback `python3` do Makefile também é exercitado. A segunda linha é a guarda de regressão
  do 281b4b2: ela falha se algum `.coverage*` cair em `service/` ou `tests/`. O YAML foi
  validado com `yaml.safe_load`, e o step ficou na posição 4 do job `test`.
- **Evidência de execução:** **nenhuma via `make` ainda.** Sem `git push` o run não acontece.
  A receita foi rodada de novo via bash no HEAD `1ec955a`, com `$(CURDIR)` trocado por
  `pwd -W`:

  | Passo | Saída | Exit |
  |---|---|---|
  | `coverage run -m pytest -q` | 755 resultados de progresso: 748 `.`, 7 `s`, 0 `F`, 0 `E` | 0 |
  | `coverage combine` | `Combined 71 files, skipped 35` | 0 |
  | `coverage report -m` | `TOTAL 7183 1252 83%`. `clean_ctrlregen.py` 73%, `rewrite_text.py` 87%, `synthid_score_server.py` 67%, `markdiffusion_harness.py` 79% | 0 |
  | `find service tests -name '.coverage*'` | vazio | — |

- **Nota de processo:** a primeira execução da suíte na FASE 3 foi descartada como evidência.
  O `-q` que passei somou com o `addopts = -q` e virou `-qq`, que esconde o resumo, e o
  `| tail` mascarou o exit code do pytest. Os números acima são da segunda execução, com o
  log completo.

### R9-02 — worktrees da sessão do cartão

| | Estado |
|---|---|
| Antes | `git worktree list`: 1 (só `E:/Projetos/Scripts/watermarks-remover`, `main`). `.git/worktrees/` não existe e `git worktree prune --dry-run` não mostra nada. Branch local: só `main`. Sem stash. `E:\Projetos\claude-worktrees\` só tem `LoveLedger/` |
| Origem do "conflito" | O app não tem nenhuma sessão com worktree ou branch deste repo. A sessão da R7 foi arquivada às 06:51:42Z, 18 s depois do `805270f` (03:51:24 -03 = 06:51:24Z). O R8 foi commitado direto no `main` pela própria sessão da R7, e o cartão aberto na R7 nunca virou worktree |
| Ação | Nenhuma. Não havia worktree nem branch para remover, e por isso não houve o commit `chore(git)` do plano |
| Depois | Igual ao antes |

- **Fora de escopo, observado:** existe o branch remoto `origin/feat/markdiffusion-harness`
  (`67ab20a`). É o branch original da feature e não é worktree. O `git cherry` marca o commit
  como `-`, ou seja, o conteúdo já está no `main` via `6144019`. Apagar esse branch exige push
  e ficou fora do escopo desta rodada.
- Se o cartão ainda aparecer na sessão arquivada da R7, **descarte**: o trabalho está em
  7d053bd.

### R9-03 — pin do `markdiffusion_harness.py`

- A referência veio da R7 ("Fora de escopo, observado", seção R7-01), que já dizia
  "Resolvido na R8 (7d053bd)". O arquivo existe. `DEFAULT_MODEL_REVISION = "f71d786…"`,
  `--revision` e `MARKDIFFUSION_MODEL_REVISION` estão presentes, e as 2 chamadas
  `from_pretrained` do diffusers (L142, L146) passam `revision=`. Nenhuma outra chamada
  `from_pretrained`/`snapshot_download`/`hf_hub_download` em `service/scripts/` fica sem
  `revision`.
- **Reexecução:** `pytest tests/test_markdiffusion_harness.py -k revision` deu 5 passed. Não
  há TDD novo, porque não há código novo.

### Verificação final — R9 (smoke do serviço)

A verificação rodou em 2026-09-25, por volta das 10:50 -03:00, no HEAD `1ec955a`, usando
`%USERPROFILE%\bin\watermarks-server.cmd`. O SHA-256 dessa cópia é igual ao da do repo. A
porta 8765 estava livre antes.

| Comando | Saída (1 linha) | Exit / HTTP |
|---|---|---|
| `watermarks-server --status` | `offline -- http://127.0.0.1:8765 nao respondeu.` | 1 |
| `watermarks-server --wait` | `Servico no ar em http://127.0.0.1:8765 (versao dev).` | 0 |
| `curl /health` | `{"ok": true, "version": "dev"}` | 200 |
| `curl /readyz` | `status: degraded`, chaves `capabilities`, `ok`, `pixel_backends`, `service`, `status`, `tools`. `pixel_backends.verified: false` | 200 |
| `curl /capabilities` | 5 grupos (`tools`, `pixel_backends`, `scorers`, `text_detectors`, `harnesses`), 12 folhas, todas `bool` | 200 |
| `curl /openapi.json` | OpenAPI 3.0.3, `openapi_spec_validator.validate` OK, 10 paths | 200 |
| `watermarks-server --stop` | `Servidor encerrado (PID 23068).` | 0 |
| `watermarks-server --status` | `offline -- http://127.0.0.1:8765 nao respondeu.` A porta 8765 ficou livre | 1 |

Os contratos pinados continuam valendo: `/capabilities` só tem bool e
`pixel_backends.verified` é `false`.

### Skills invocadas (para cruzar com o transcript)

| Skill | Fase | Propósito |
|---|---|---|
| `ponytail:ponytail-review` | 0 | Critério aplicado ao diff da rodada (9 linhas de YAML): "Lean already. Ship." |
| `ponytail:ponytail-debt` | 0 | Ledger `ponytail:`: 0 marcadores |
| `python-pro` | 0 | Carregada. Não houve código Python novo na rodada (R9-03 já estava resolvido) |
| `py-test-quality` | 0, 3 | Medição de cobertura pela receita do target (83%) e contagem pelo progresso completo |
| `py-security` | 0, 3 | `pip-audit` 0. Bandit Low 32 / Medium 1 / High 0. Varredura de `from_pretrained` sem `revision` |
| `py-code-health` | 0 | Nenhum código adicionado ou removido. Nada a varrer |
| `caveman` | 0 | Estilo de saída |
| `python-test` | 0 | Baseline via agente `python-test-runner`: 755/748/7 |
| `python-review` (condicional) | — | **Não invocado.** O gatilho previsto era tocar o Makefile, e o Makefile não foi tocado. O diff é só YAML de CI, sem secret, sem action nova e com `permissions` inalterado |
| `python-type` (condicional) | — | **Não invocado.** Nenhum `.py` foi alterado |

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
