---
name: detect-ai-patterns
description: Analisa texto e código em busca de padrões estilométricos de IA (em-dash denso, bold lead-in, template headings, hedges, docstrings que ecoam o nome da função, comentário óbvio, type hint em local trivial). Determinístico, sem ML. Cobre .md, .txt, .html, .docx, .pdf, .py, .ts, .tsx, .js, .jsx. Use quando o usuário pedir "esse texto parece IA?", "detecta IA nisso", "analisa esse arquivo", "quais hábitos de IA tem aqui", ou invoca /detect-ai-patterns. O resultado é indicativo, não veredito, e nunca diz quem escreveu.
---

# Detect AI patterns: onde o estilo denuncia hábito

Ferramenta do repositório `watermarks-remover`. Varre um arquivo ou uma pasta e lista, por linha, os hábitos de estilo que costumam aparecer em texto e código gerados por modelo: travessões em excesso, títulos de modelo, comentários que repetem a linha seguinte, e assim por diante. Sem modelo e sem rede: regex, `ast` e contagens.

Este arquivo também é a documentação. Se o usuário perguntar "como isso funciona?", responda a partir das seções abaixo, sem abrir o código.

## O que é, e o que não é

- **É** uma ajuda de revisão de uso pessoal: aponta hábitos no que **o próprio usuário** escreveu, para ele reescrever.
- **Não é** um detector de autoria. A saída nunca traz `is_ai`. Traz `signals`, `score` (0,0 a 1,0), `confidence` (`low`, `medium`, `high`) e `disclaimer`. Nunca diga "isso foi escrito por IA", e não use o resultado para acusar terceiros.
- **Não é** o `service/scripts/score_stylometry.py` (o `--stylometry` do serviço): aquele dá uma nota única só para texto, sem a posição de cada achado. Este lista cada sinal com linha e trecho, cobre código e compara antes e depois.

## Onde está o CLI

Caminho do repositório: a variável de ambiente `WATERMARKS_REPO`, e, se ela não existir, `E:\Projetos\Scripts\watermarks-remover` (o mesmo padrão do `watermarks-server.cmd`). O script é `tools\detect_ai_patterns.py`. Funciona de qualquer diretório.

PowerShell:

```powershell
$repo = if ($env:WATERMARKS_REPO) { $env:WATERMARKS_REPO } else { 'E:\Projetos\Scripts\watermarks-remover' }
if (-not (Test-Path "$repo\tools\detect_ai_patterns.py")) { throw "Repositório não encontrado em $repo. Defina WATERMARKS_REPO." }
$py = if (Test-Path "$repo\.venv\Scripts\python.exe") { "$repo\.venv\Scripts\python.exe" } else { 'python' }
& $py "$repo\tools\detect_ai_patterns.py" CAMINHO --format md
```

Bash (Git Bash, WSL, Linux, macOS):

```bash
REPO="${WATERMARKS_REPO:-/e/Projetos/Scripts/watermarks-remover}"   # no WSL: /mnt/e/Projetos/Scripts/watermarks-remover
[ -f "$REPO/tools/detect_ai_patterns.py" ] || { echo "Repositório não encontrado em $REPO. Defina WATERMARKS_REPO." >&2; exit 1; }
PY="$REPO/.venv/Scripts/python.exe"; [ -x "$PY" ] || PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
"$PY" "$REPO/tools/detect_ai_patterns.py" CAMINHO --format md
```

Prefira o Python da `.venv` do repositório. Nesta máquina o `python` do PATH é o stub da Microsoft Store ("Python was not found"): se o fallback falhar assim, use o interpretador real (3.12 ou mais novo) e diga isso ao usuário.

`.docx`, `.pdf` e a análise de TS/JS com tree-sitter precisam do grupo opcional `formats` (`uv pip install --group formats`). Sem ele, `.docx` e `.pdf` são pulados com um aviso e TS/JS são analisados por regex, com `confidence` no máximo `low`.

## Comandos típicos

```
detect_ai_patterns.py CAMINHO [--format json|md] [--only text|code|all]
                      [--min-severity low|medium|high] [--ignore GLOB]
                      [--exclude-tests] [--output ARQUIVO]
```

| Quero | Comando |
|---|---|
| Um arquivo, em markdown | `CAMINHO --format md` |
| Só o texto de um repositório | `. --only text --format md` |
| Só o código | `. --only code --format md` |
| Ver só o que pesa | `CAMINHO --format md --min-severity high` |
| Repositório de terceiros | `. --exclude-tests --format md` |
| Guardar o relatório | `CAMINHO --format md --output relatorio.md` |
| Consumir por script | `CAMINHO --format json` |

Pastas como `.git`, `.venv`, `node_modules` e caches nunca são varridas, e links simbólicos não são seguidos. Texto acima de 1 MB e binário acima de 25 MB são pulados com o motivo.

Exit: **0** rodou; **1** caminho inexistente ou `--output` inválido; **2** nada foi analisado.

## Como ler a saída

- **Cada sinal** traz nome, severidade (`low`, `medium`, `high`), valor (quantas vezes aparece, ou a métrica), a linha e um trecho. Sinais de documento (métricas) não têm linha.
- **Score.** Soma ponderada dos sinais que dispararam (estrutural 2, lexical 1, métrica 0,5; `low`/`medium`/`high` valem 0,33/0,66/1), saturada por `1 − e^(−soma/8)`. Não é probabilidade. Limiares e pesos são escolha da ferramenta, sem calibração contra corpus. `--min-severity` só esconde sinais do relatório: o score usa todos.
- **Confidence** vem do tamanho da amostra: texto com menos de 150 palavras é `low`, menos de 600 é `medium`; código com menos de 40 linhas é `low`, menos de 200 é `medium`. Regex no lugar do tree-sitter limita a `low`, e PDF a `medium`. **Se a confiança é `low`, diga isso junto do score.**
- **No relatório `md`:** a tabela "Sinais mais frequentes" (quantos arquivos, severidade máxima) e o "Top 10 arquivos por score", com os sinais de cada um.
- **`.docx`, `.pdf` e `.html`:** as linhas se referem ao texto extraído, não ao arquivo original. O relatório avisa.

Trecho real, `detect_ai_patterns.py code_ai_like.py --format md --min-severity medium`:

```text
### 1. `code_ai_like.py`

Score 0.69 · confiança medium · python

- `obvious_comment` (high, valor 7): linha 6: `# Import the required modules`; linha 21: `# Initialize the content variable` (+5)
- `comment_density` (high, valor 0.28): documento: `14 comentários / 50 linhas de código`
- `docstring_echoes_name` (medium, valor 3): linha 19: `get_file_content: Gets the file content.`
- `excessive_params` (medium, valor 10): linha 41: `write_output(10 parâmetros)`
```

## Catálogo de sinais

**Texto (21)**

| Sinal | O que conta |
|---|---|
| `em_dash_density`, `em_dash_to_comma_ratio` | travessões por frase, e travessões por vírgula |
| `not_just_but` | "não é apenas X, é Y", "not just X, it's Y" |
| `delve_family` | `delve`, `dive in`; "vamos explorar/desvendar/mergulhar" |
| `worth_noting` | "vale notar", "importante ressaltar", "it's worth noting" |
| `fast_paced_world` | "in today's fast-paced world", "em um mundo onde", "no mundo de hoje" |
| `on_the_other_hand_cascade` | três ou mais "por outro lado" em 2500 caracteres |
| `hedge_double` | dois hedges a até duas palavras ("pode ser que talvez") |
| `meta_commentary` | "nesta seção", "como vimos", "in this section" |
| `here_is_why` | "aqui está por quê:", "here's why:" |
| `declarative_close` | "Não é X. É Y." (mais forte no último parágrafo) |
| `bold_lead_in` | `**Termo** — definição` no começo de linha ou item de lista |
| `template_heading` | títulos que começam com "Por que", "O que", "A linha", "Why", "What", "The bottom" |
| `emoji_heading` | emoji em título |
| `tricolon_uniform` | séries de três itens em parágrafos seguidos |
| `comparison_table_symmetry` | tabela cujas colunas têm o mesmo tamanho médio |
| `paragraph_uniformity`, `sentence_uniformity` | desvio-padrão baixo de frases por parágrafo e de palavras por frase |
| `sentence_length_stddev`, `paragraph_length_stddev` | as mesmas métricas, em faixa mais branda |
| `type_token_ratio` | vocabulário repetido nas primeiras 300 palavras |

**Código (16).** `.py` usa `ast`; TS/JS usa tree-sitter, ou regex se o grupo `formats` não está instalado.

| Sinal | O que conta |
|---|---|
| `docstring_echoes_name` | docstring de uma linha que só repete o nome da função |
| `obvious_comment` | `# Initialize/Set/Import/Return...` antes de uma linha que já diz isso |
| `comment_density` | proporção de comentários por linha de código |
| `type_hint_on_trivial_local` | anotação que só repete o tipo de um literal escalar (`x: int = 0`) |
| `generic_try_except` | `except Exception:` ou `except:` só com `pass` |
| `excessive_params` | função com 10 ou mais parâmetros |
| `over_descriptive_name` | nome com 4 palavras ou mais e 30+ caracteres (só em projeto com até 50 arquivos de código) |
| `complete_main_boilerplate` | `__main__` com argparse, logging e try/except juntos |
| `future_annotations_on_314` | `from __future__ import annotations` com `requires-python >= 3.14` |
| `match_where_if_fits` | `match` de dois casos simples |
| `warning_comment`, `todo_comment_style` | `# Note:`/`# Important:` sem risco real; `TODO(autor):` repetido |
| `as_const_everywhere`, `optional_chaining_overuse`, `jsdoc_on_trivial_type`, `explicit_return_types_on_arrow` | só TS/JS |

## Regras ao reportar

1. **Sempre repita o disclaimer**, junto do score: *"Score é indicativo, não veredito. Falsos positivos esperados em texto técnico disciplinado e em código com convenções fortes."*
2. **`--exclude-tests` em repositório de terceiros.** Fixtures e testes carregam de propósito comentários óbvios e travessões, e distorcem o ranking.
3. **Dê o número e a confiança**, nunca só um adjetivo. Score com `confidence: low` é amostra pequena.
4. **Leia o contexto antes de recomendar.** Um documento técnico pode pontuar alto só por usar negrito de abertura e tabelas, que é o formato dele; código do serviço pode ter função com muitos parâmetros por bons motivos. Isso é falso positivo esperado, não defeito.
5. **Não acuse.** O resultado nunca é prova sobre quem escreveu, e o uso é sobre o que o usuário produziu.

## Próximo passo

- Para **texto** com problema estrutural (negrito de abertura, travessão, título de modelo, "vale notar que"): skill `naturalize`, que aplica transformações determinísticas e mede o efeito.
- Para **prosa** que precisa de reescrita (ritmo, vocabulário): `/clean-user-facing-text`. Atenção: a medição da R10 mostrou que ela **não reduz** o score deste detector.
- Para **código**: não há humanizador. Os sinais apontam onde revisar à mão.
- Para medir antes e depois: `tools\measure_skill_effectiveness.py ANTES DEPOIS`.
