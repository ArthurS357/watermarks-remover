# TODO — watermarks-remover

## Rodada R10 — 2026-09-30 — Detecção estilométrica e medição de efetividade

Concluída em 2026-09-30. Ver [`docs/DONE.md`](DONE.md#estado-do-sistema--2026-09-30). O plano
abaixo é o que foi escrito antes de qualquer edição; o que mudou na execução está em
"Ajustes durante a execução", no fim desta seção. Duas entregas independentes, **scripts CLI isolados** (não tocam
`service/scripts/server.py` nem as skills): `tools/detect_ai_patterns.py` (sinais
estilométricos em texto e código) e `tools/measure_skill_effectiveness.py` (antes/depois).
Uso pessoal: o output ajuda a revisar o que você escreveu, não a acusar terceiros. Nunca emite
`is_ai`; sempre `signals`, `score` 0.0–1.0, `confidence` low|medium|high e `disclaimer`.

### Baseline (FASE 0, HEAD `2302a15`)

| Medida | Valor | Esperado |
|---|---|---|
| `pytest` | 755 coletados / **748 passed / 7 skipped**, exit 0 (184 s) | bate |
| `ruff check .` / `ruff format --check .` | limpos, 102 arquivos | bate |
| `pip-audit` (`.venv`) | **3 vulns em `urllib3 2.7.0`** (CVE-2026-97687/97688/97689, fix 2.8.0) | a R9 registrou 0 |

O `pip-audit` divergiu da R9 por advisories publicados depois dela. `urllib3` é transitivo do
`pip-audit`/`requests` na `.venv` de dev, não está em `requirements-dev.txt` e não entra no
serviço. O critério explícito de parada (755/748/7) bate, então a rodada segue. "Sem novas
vulnerabilidades" da FASE 5 é medido contra estes 3. **Resolvido na retomada:** o usuário
mandou subir o `urllib3` na `.venv` (ação local, como a Q6 da R6). `uv pip install --upgrade
urllib3` levou de 2.7.0 a 2.8.0 e o `pip-audit` voltou a 0.

### Achados da FASE 0 que mudam premissas do prompt

| # | Achado | Consequência no plano |
|---|---|---|
| A1 | **Não existe `pyproject.toml`.** Config em `ruff.toml`, `pytest.ini`, `.coveragerc`; deps em `requirements-dev.txt`. A R6-07 manteve isso de propósito | R10-06 **cria** um `pyproject.toml` só com `[dependency-groups]`, sem `[project]`. Nada é consolidado. `ruff.toml`/`pytest.ini`/`.coveragerc` têm precedência sobre ele e a FASE 5 confirma que nada mudou |
| A2 | **`.gitignore` é deny-by-default** (`/*`). `tools/` e `pyproject.toml` seriam ignorados pelo git | Novo R10-08: `!/tools/`, `!/tools/**` (bloco 1) e `!/pyproject.toml` (bloco 6). `stylometry-report.md` na raiz já é ignorado, então não há risco de commitá-lo |
| A3 | **`uv sync --group formats` é exato e remove o pytest da venv** (testado numa cópia: `- pytest`, `- pluggy`…). Sem `[project]` ele também cria `.venv` e `uv.lock` e avisa "no `requires-python`" | O README recomenda `uv pip install --group formats` / `pip install --group formats` (aditivos) e documenta `uv sync --inexact --group formats`. O comando literal do prompt fica com o aviso |
| A4 | `tree-sitter 0.26.0` + `tree-sitter-typescript 0.23.2` instalam e parseiam no Windows com Python 3.14 (testado em venv de teste) | Sem limitação de Windows a declarar. O fallback regex existe para a **ausência** do grupo |
| A5 | A CI instala só `requirements-dev.txt`, em Python **3.12 e 3.14**, em 3 SOs. `ruff.toml` tem `target-version = py312` | Testes novos passam **sem** `python-docx`/`pypdf`/`tree-sitter` (`importorskip` nos caminhos pesados). Nada de sintaxe acima de 3.12 |
| A6 | `ruff check .`/`ruff format --check .` varrem `tests/fixtures/`. `code_ai_like.py` tem comentário óbvio e em-dash de propósito | `ruff.toml`: `extend-exclude = ["tests/fixtures/stylometry"]` (bloco 2) |
| A7 | Já existe `service/scripts/score_stylometry.py` (burstiness, MATTR, frases-clichê, sem linha por sinal) | **Não reaproveitado**, por duas razões: cada sinal precisa de `linha`/`snippet` (o existente descarta a posição) e o prompt exige script isolado, sem acoplar ao serviço. As duas ferramentas ficam separadas; o README explica a diferença |
| A8 | `pip-audit`, `bandit` e `mypy` não estão na `.venv`; `pip-audit` está (2.10.1), `bandit`/`mypy` só no Python global | FASE 5 roda `bandit`/`mypy` do Python global e compara o bandit com o baseline da R9 (Low 32 / Medium 1 / High 0 em `service/scripts/`) |
| A9 | `mutmut` não roda no Windows (R6) | Sem mutation testing. Cobertura de `tools/` medida com `--cov=tools`, sem mexer no `.coveragerc` |

### Plano

| ID | Item | Arquivos | Bloco de commit |
|---|---|---|---|
| R10-01 | Sinais de texto | `tools/stylometry/__init__.py` (`Signal`, score, disclaimer), `text.py`, `tests/test_stylometry_text.py`, `tests/fixtures/stylometry/text_{ai,human}_like.md` | 1 |
| R10-08 | `.gitignore` libera `tools/` e `pyproject.toml`; `ruff.toml` exclui fixtures | `.gitignore` (blocos 1 e 6), `ruff.toml` (bloco 2) | 1, 2, 6 |
| R10-02 | Sinais de código | `tools/stylometry/code.py`, `tests/test_stylometry_code.py`, `tests/fixtures/stylometry/code_{ai,human}_like.py`, `code_ai_like.tsx` | 2 |
| R10-05 | Carregadores de formato | `tools/stylometry/loaders.py`, `tests/test_stylometry_loaders.py` | 3 |
| R10-03 | CLI de detecção | `tools/detect_ai_patterns.py`, `tests/test_detect_ai_patterns.py`, README (uso, formatos, disclaimer, exemplo real) | 4 |
| R10-04 | CLI de medição | `tools/measure_skill_effectiveness.py`, `tests/test_measure_skill_effectiveness.py`, README (uso) | 5 |
| R10-06 | `[dependency-groups].formats` | `pyproject.toml`, README (grupo, `--inexact`) | 6 |
| R10-07 | README, seção "Detecção estilométrica" | `README.md` (montada nos blocos 4, 5 e 6) | 4, 5, 6 |
| R10-09 | Dogfooding e registro | `docs/DONE.md`, `docs/TODO.md`. Relatório e cópia reescrita ficam **fora do git** | 7 |

Os testes de sinais ficam em arquivos próprios (`test_stylometry_text/code/loaders.py`) em vez
de tudo em `test_detect_ai_patterns.py`: um commit por bloco e arquivos abaixo de 800 linhas.
`test_detect_ai_patterns.py` fica só com CLI e integração.

**Ordem de execução e de commit:** plano (`docs(todo)`) → 1 → 2 → 3 → 4 → 5 → 6 → 7, a mesma
ordem do prompt. TDD dentro de cada bloco: teste vermelho (positivo e negativo por sinal),
implementação, verde, `ruff`, suíte completa. README do bloco 4 já aponta o grupo opcional;
as instruções de instalação do grupo chegam no bloco 6 junto com o `pyproject.toml`.

### Contrato comum

- `Signal(name, value, severity, line, snippet)`, `NamedTuple`. Sinal por ocorrência: `value` =
  total daquele sinal no arquivo, `line` = linha da ocorrência. Sinal de documento (métricas):
  `line = None`. `severity` ∈ low | medium | high.
- **Score** = `min(1.0, Σ peso(categoria) × força(severidade máxima de cada sinal) / 8.0)` no
  plano. **Na execução virou `1 − e^(−Σ/8)`** (ver "Ajustes durante a execução").
  Força: low 0.33, medium 0.66, high 1.0. Peso: **estrutural 2.0, lexical 1.0, métrica 0.5**.
  Desvio deliberado de "média ponderada" pura: a média só dos sinais disparados dá 1.0 a um
  único sinal alto, e a média sobre o catálogo inteiro nunca passa de ~0.4, o que tornaria o
  limiar `delta < -0.30` da R10-04 inalcançável. O divisor 8.0 é um orçamento de saturação,
  calibrado nas fixtures (AI-like ≥ 0.6, human-like ≤ 0.2) e não é probabilidade.
- **Confidence** por tamanho da amostra: texto < 150 palavras low, < 600 medium, senão high;
  código < 40 linhas de código low, < 200 medium, senão high. Teto `low` para TS/JS em regex
  fallback e teto `medium` para PDF (perde heading, negrito e tabela).
- `--min-severity` filtra o que é **listado**; o score é sempre calculado com todos os sinais.

### Sinais de texto (`tools/stylometry/text.py`), limiares preliminares

Limiares sem calibração contra corpus real, por decisão da rodada (sem modelo estatístico).
Linhas numeradas sobre o arquivo original: front matter e blocos de código viram linhas em
branco antes da análise, sem renumerar.

| Sinal | Categoria | Regra | L / M / H |
|---|---|---|---|
| `em_dash_density` | lexical | `—` por frase | ≥0.20 / ≥0.40 / ≥0.80 |
| `not_just_but` | lexical | "não é apenas X, é Y", "not just X, it's Y" (PT/EN) | 1 / 2 / ≥3 |
| `delve_family` | lexical | `delve`, `dive in`; `explore`/`unpack` só após "let's/we'll/vamos" | 1 / 2 / ≥3 |
| `worth_noting` | lexical | "vale notar", "importante ressaltar", "it's worth noting" | 1 / 2 / ≥4 |
| `fast_paced_world` | lexical | "in today's fast-paced", "em um mundo onde" | — / 1 / ≥2 |
| `on_the_other_hand_cascade` | lexical | 3+ "por outro lado"/"on the other hand" numa janela de 2500 caracteres | — / 3 / ≥5 |
| `hedge_double` | lexical | dois hedges a ≤2 palavras ("pode ser que talvez", "arguably perhaps") | 1 / 2 / ≥3 |
| `bold_lead_in` | estrutural | `**Termo**` seguido de `—`, `–`, `:` ou `-`, em linha ou item de lista | ≥3 / ≥6 / ≥12 |
| `tricolon_uniform` | estrutural | série de 3 itens (com ou sem vírgula de Oxford) em 3+ parágrafos seguidos | — / 3 / ≥5 |
| `template_heading` | estrutural | `^#+\s*(Por que\|O que\|A linha\|Why\|What\|The bottom)` | 1 / 2 / ≥3 |
| `emoji_heading` | estrutural | heading com `U+1F300–1FAFF` ou dingbats `U+2600–27BF` | 1 / 2 / ≥4 |
| `meta_commentary` | estrutural | "nesta seção", "como vimos", "in this section" | 1 / 2 / ≥4 |
| `paragraph_uniformity` | estrutural | desvio-padrão de frases/parágrafo < 0.5 (≥5 parágrafos) | — / <0.5 / <0.25 |
| `sentence_uniformity` | estrutural | desvio-padrão de palavras/frase < 5 (≥8 frases) | — / <5 / <3 |
| `declarative_close` | estrutural | "Não é X. É Y." / "It's not X. It's Y." | fora do fecho L / no último parágrafo M / — |
| `here_is_why` | estrutural | "Aqui está por quê:", "Here's why:" | 1 / 2 / ≥3 |
| `comparison_table_symmetry` | estrutural | tabela markdown com colunas de tamanho médio dentro de ±10% | — / 1 tabela / ≥2 |
| `type_token_ratio` | métrica | únicos/total nas primeiras 300 palavras (≥100 palavras) | <0.50 / <0.42 / <0.35 |
| `sentence_length_stddev` | métrica | desvio-padrão de palavras/frase, só na faixa [5, 7), para não contar duas vezes com `sentence_uniformity` | [5,7) / — / — |
| `paragraph_length_stddev` | métrica | desvio-padrão de palavras/parágrafo (≥5 parágrafos) | <12 / <8 / <4 |
| `em_dash_to_comma_ratio` | métrica | `—` / vírgulas | ≥0.15 / ≥0.30 / ≥0.60 |

### Sinais de código (`tools/stylometry/code.py`), limiares preliminares

| Sinal | Categoria | Regra | L / M / H |
|---|---|---|---|
| `docstring_echoes_name` | estrutural (ast) | docstring de 1 linha cujas palavras são as do nome + artigos | 1 / ≥3 / ≥6 |
| `obvious_comment` | lexical | `# Initialize/Set/Import/Define/Create/Return…` antes de statement de 1 linha | 1 / ≥3 / ≥6 |
| `comment_density` | métrica | linhas de comentário / linhas de código (≥30 linhas de código) | ≥0.15 / ≥0.20 / ≥0.25 |
| `type_hint_on_trivial_local` | estrutural (ast) | `x: int = 0` dentro de função, valor literal | 1 / ≥3 / ≥6 |
| `generic_try_except` | estrutural (ast) | `except Exception:`/`BaseException`/bare + só `pass` | — / 1 / ≥3 |
| `excessive_params` | estrutural (ast) | função com ≥10 parâmetros (sem `self`/`cls`) | — / ≥10 / ≥14 |
| `over_descriptive_name` | estrutural (ast) | nome com ≥4 palavras e ≥30 caracteres. **Só se o scan tem ≤50 arquivos de código** ("projeto pequeno") | 1 / ≥3 / ≥6 |
| `complete_main_boilerplate` | estrutural (ast) | guard `__main__` + argparse + logging + try/except | — / todos / — |
| `future_annotations_on_314` | estrutural (ast) | `from __future__ import annotations` com `requires-python >= 3.14` lido do `pyproject.toml` mais próximo. **Sem `requires-python`, não dispara** (é o caso deste repo) | 1 / — / — |
| `match_where_if_fits` | estrutural (ast) | `match` com 2 casos, padrões só literal/valor/curinga, sem guarda | 1 / ≥3 / — |
| `as_const_everywhere` | estrutural (TS) | `as const` sobre literal primitivo | ≥3 / ≥6 / ≥10 |
| `optional_chaining_overuse` | estrutural (TS) | cadeia com ≥3 `?.`, ou `?.` em `this`/literal/`const` inicializado com literal no mesmo arquivo | ≥3 / ≥6 / ≥12 |
| `jsdoc_on_trivial_type` | estrutural (TS) | `@param {string\|number\|boolean…}` em `.ts/.tsx`; em `.js/.jsx` só sem descrição | 1 / ≥3 / ≥6 |
| `explicit_return_types_on_arrow` | estrutural (TS) | `(): void =>` em arrow inline (argumento de chamada ou atributo JSX) | 1 / ≥3 / ≥6 |
| `warning_comment` | lexical | `# Note:`/`# Important:`/`# WARNING:` sem palavra crítica (security, race, never, secret…) | 1 / ≥3 / ≥6 |
| `todo_comment_style` | lexical | ≥3 `TODO(autor):` com o mesmo formato | ≥3 / ≥6 / — |

TS/JS: `tree-sitter` quando instalado (`.ts` na gramática typescript; `.tsx/.js/.jsx` na tsx);
regex como fallback. O resultado marca qual dos dois rodou e o fallback limita `confidence`.

### CLIs: decisões que o prompt deixou abertas

- **Pastas ignoradas por padrão:** `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`,
  `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.code-review-graph`, `dist`, `build`. Sem isso,
  `detect_ai_patterns.py .` varreria a `.venv` inteira. `--ignore` soma a esta lista.
  Texto maior que 1 MB (o plano dizia 2 MB) e binário maior que 25 MB são pulados com motivo. `--output` dentro da árvore varrida é pulado na
  própria execução.
- **Saída:** `disclaimer` no topo do JSON e do relatório, dos dois CLIs. Arquivo sem dependência
  (`.docx`/`.pdf`) vira `skipped` com o motivo e o comando de instalação, sem abortar.
  Exit 2 quando nenhum arquivo foi analisado, inclusive se todos os suportados foram pulados.
- **`measure_skill_effectiveness`:** `delta = depois − antes` (negativo é melhora). Faixas do
  prompt: `< −0.30` high; `[−0.30, −0.10)` medium; senão low. Além dos campos pedidos, inclui
  `signal_deltas` (por sinal) e `signals_introduced` (sinais que só existem depois).
  `--signals` restringe score e listas aos sinais nomeados. Em diretório, `files` por caminho
  relativo mais `aggregate`; arquivos de um lado só vão para `unmatched_*`.
- **Dogfooding (R10-09):** a "cópia reescrita fora do git" do `docs/DONE.md` fica no scratchpad
  da sessão. Os testes do compare usam o par tracked `text_ai_like.md` / `text_human_like.md`,
  não a cópia. A skill `clean-user-facing-text` é invocada via `Skill` na FASE 4 (não está no
  gate de skills, mas é o objeto da medição). n = 1 arquivo: não generaliza.

### Riscos por item

- **R10-01:** limiares arbitrários e falsos positivos em texto técnico disciplinado (esperado,
  no disclaimer). ReDoS nos regex: quantificadores limitados e teste de tempo com entrada de 1 MB.
  `type_token_ratio` depende do tamanho do texto, por isso a janela de 300 palavras. Decode:
  `utf-8-sig` com `errors="replace"`, sem abortar em arquivo estranho.
- **R10-02:** `ast.parse` falha em arquivo com erro de sintaxe: o arquivo mantém os sinais de
  regex e ganha nota `parse_error`. `over_descriptive_name` e `future_annotations_on_314` dependem
  de contexto (tamanho do scan, `requires-python`): sem o contexto, ficam quietos, não chutam.
  O regex de TS só aproxima `optional_chaining_overuse`; nulidade de verdade exige o type checker.
- **R10-05:** `python-docx`/`pypdf` leem arquivo não confiável. Limite de tamanho, `try/except`
  largo com mensagem, PDF criptografado ou que trava vira `skipped`. `html.parser` ignora
  `script`/`style`. Diferenças de API do `tree-sitter` entre versões caem no fallback com nota.
- **R10-03:** diretório grande e symlink (`followlinks=False`), encoding, relatório
  auto-ingerido (tratado acima). O repo vai pontuar alto contra si mesmo: é o insight, não falha.
- **R10-04:** pareamento por caminho relativo; o mesmo conjunto de limiares nos dois lados,
  senão o delta mede a mudança de régua.
- **R10-06:** `uv sync` exato apagando dev deps (A3, documentado). `pyproject.toml` novo não pode
  mudar o comportamento de `ruff`/`pytest`/`coverage`: a FASE 5 roda a suíte inteira e o
  `ruff` antes e depois, e confere que os dois continuam lendo os arquivos próprios.
- **R10-07:** o exemplo de saída no README vem de execução real (`--format md` num arquivo do
  repo), não escrito à mão. O README já tem 77 KB: a seção fica curta.
- **R10-08:** a allowlist do `.gitignore` tem que liberar `tools/` sem abrir o resto. Conferido
  com `git status` e `git check-ignore` depois de cada bloco.
- **R10-09:** a cópia reescrita é feita por mim, seguindo a skill. A medição mostra o efeito
  dessa aplicação, não da skill em geral.

### Ajustes durante a execução

O plano acima não foi reescrito: estas são as diferenças entre ele e o que saiu.

| # | Plano | Execução | Motivo e commit |
|---|---|---|---|
| J1 | Score `min(1, Σ/8)` | `1 − e^(−Σ/8)` | A soma cortada batia 1.0 na fixture carregada e deixava uma reescrita parcial com delta 0, o que cegaria a R10-04. Fixture meio limpa: 0.67, contra 0.89 da cheia. 3f7aff8 |
| J2 | Texto até 2 MB | Texto até 1 MB, binário até 25 MB | Reduz o pior caso de regex e `ast` em entrada hostil. dd07e5d |
| J3 | Sem teto de blocos | `MAX_BLOCKS = 50_000`, com nota no relatório | Medido: 50k blocos levam 1,57 s. Um arquivo de 1 MB pode ter ~333 mil blocos (3 bytes cada, `a\n\n`): analisa os 50k primeiros em 2,85 s, contra 10,23 s se o teto subisse para cobrir tudo. Um documento real de 1 MB tem ~21 mil blocos (1,93 s). Mantido em 50k |
| J4 | `try/except` largo e timeout | Processo filho morto no timeout (`tools/stylometry/isolate.py`), JSON no pipe (sem pickle), guarda de zip-bomb pelos bytes reais | O `python-reviewer` deu FAIL com 7 ALTA: 21 bytes travam o parser TSX segurando a GIL, `obvious_comment` levava 12 s em 40 KB, 3 regex quadráticos, `RecursionError` escapando de `analyze()` e zip-bomb confiando no tamanho do cabeçalho. dd07e5d, c65b66b, c3f90d0 |
| J5 | Contexto implícito | `Context(small_project=False, requires_python=None)`: fato ausente deixa o sinal quieto | É a regra "sem contexto, não chuta" do plano, tornada explícita no tipo |
| J6 | `obvious_comment`: `# Initialize/Set/Import...` antes de statement de 1 linha | Verbos ampliados (`increment`, `call`, `get`, `add`) e comentário que já explica o porquê (`:`, `(`, `because`, `since`, `see`) não conta | Menos falso positivo em comentário útil |
| J7 | `type_hint_on_trivial_local`: `x: int = 0`, valor literal (inclui `[]` e `{}`) | Só a anotação que repete o tipo de um literal escalar (`x: int = 0`, `s: str = ""`) | O dogfooding pôs o sinal em 37 arquivos, quase todos `x: list[T] = []` e `x: T \| None = None`, onde o `mypy --strict` exige a anotação. 70b3c2f |
| J8 | Leitores tolerantes a arquivo ruim | Também `zlib.error`/`LZMAError`/`EOFError` de `.docx` corrompido, junctions do Windows e nome de arquivo com escape | `code-reviewer` (0 crítico, 2 maior, 1 menor), reproduzidos antes de corrigir. f4a7b27 |
| J9 | CLI de medição chama `scan` e herda seus avisos | `Options.warn`; `quote` e `utf8_streams` públicos | O aviso precisa dizer de que lado veio o arquivo pulado. 969ece2 |
| J10 | README no bloco 4 | README depois dos dois CLIs, mais o parágrafo da A7 | O exemplo precisava da saída real. ff7916f, f3db001 |
| J11 | — | Fixture autouse em `tests/test_markdiffusion_harness.py` | Os testes antigos deixavam um `PIL` falso em `sys.modules`; com o grupo `formats` instalado, o primeiro `import pypdf` depois disso quebrava 10 testes de PDF na suíte completa. 3634dbc |

## Rodada R9 — 2026-09-25 — Fechamento e verificação de uso

Concluída. Ver [`docs/DONE.md`](DONE.md#estado-do-sistema--2026-09-25). **Sistema pronto
para uso: sim.** Nenhuma pendência bloqueia o uso.

### 🟡 Aberto, não bloqueia uso

**R9-01: primeiro run do step `Subprocess coverage (make test-cov-subprocess)` na CI.**

- **Motivo de ainda estar aberto:** o step existe (1ec955a), mas a CI só roda depois de
  `git push`, que está fora da autoridade das rodadas.
- **Por que não bloqueia:** é uma ferramenta de medição de cobertura de dev. A receita já foi
  verificada via bash no mesmo HEAD (83%, sem vazamento de `.coverage*`), e nenhum caminho de
  uso passa por ela.
- **Fecha quando:** o job `test (ubuntu-latest, 3.14)` ficar verde no primeiro push. Aí basta
  anotar o link do run no DONE e trocar para ✅.

### Plano (registrado antes das edições, c85d942)

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

Concluída. O plano original está em a713bbd, e o detalhe e os commits estão em
[`docs/DONE.md`](DONE.md#rodada-r7--2026-09-25--fechamento-dos-resíduos-da-r6).

### ~~🔴 Escalado~~ → absorvido pela R9-01 (opção "b": step de CI, 1ec955a)

**R7-04 — rodar `make test-cov-subprocess` via `make` de verdade.** O texto abaixo foi
mantido como histórico. O estado atual é o da R9-01, acima.

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
