---
name: detect-ai-patterns
description: Analisa prosa em busca de padrões estilométricos de IA (em-dash denso, bold lead-in, template headings, hedges, aberturas de "mundo acelerado"). Determinístico, sem ML. Cobre .md, .txt, .html, .docx e .pdf. Código-fonte está fora do escopo. Use quando o usuário pedir "esse texto parece IA?", "detecta IA nisso", "analisa esse texto", "quais hábitos de IA tem aqui", ou invoca /detect-ai-patterns. O resultado é indicativo, não veredito, e nunca diz quem escreveu.
---

# Detect AI patterns: onde o estilo denuncia hábito

Ferramenta do repositório `watermarks-remover`. Varre um arquivo ou uma pasta e lista, por linha, os hábitos de estilo que costumam aparecer em texto gerado por modelo: travessões em excesso, títulos de modelo, negrito de abertura, e assim por diante. Sem modelo e sem rede: regex e contagens. **Só prosa.** Código-fonte (`.py`, `.ts`, `.js`...) saiu do escopo na R15: os sinais de código marcaram 49% dos arquivos humanos da biblioteca padrão do Python e não pegaram código de modelo realista. Um arquivo de código passado ao CLI é recusado com uma mensagem, e numa pasta é ignorado.

Este arquivo também é a documentação. Se o usuário perguntar "como isso funciona?", responda a partir das seções abaixo, sem abrir o código.

## O que é, e o que não é

- **É** uma ajuda de revisão de uso pessoal: aponta hábitos no que **o próprio usuário** escreveu, para ele reescrever.
- **Não é** um detector de autoria. A saída nunca traz `is_ai`. Traz `signals`, `score` (0,0 a 1,0), `confidence` (`low`, `medium`, `high`) e `disclaimer`. Nunca diga "isso foi escrito por IA", e não use o resultado para acusar terceiros.
- **Não é** o `service/scripts/score_stylometry.py` (o `--stylometry` do serviço): aquele dá uma nota única só para texto, sem a posição de cada achado. Este lista cada sinal com linha e trecho e compara antes e depois.

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

`.docx` e `.pdf` precisam do grupo opcional `formats` (`uv pip install --group formats`). Sem ele, são pulados com um aviso.

## Comandos típicos

```
detect_ai_patterns.py CAMINHO [--format json|md] [--only text|all]
                      [--min-severity low|medium|high] [--ignore GLOB]
                      [--output ARQUIVO]
```

`--only` existe só por compatibilidade: `text` e `all` fazem a mesma coisa, e `--only code` não existe mais.

| Quero | Comando |
|---|---|
| Um arquivo, em markdown | `CAMINHO --format md` |
| A documentação de um repositório | `. --format md` |
| Ver só o que pesa | `CAMINHO --format md --min-severity high` |
| Guardar o relatório | `CAMINHO --format md --output relatorio.md` |
| Consumir por script | `CAMINHO --format json` |

Pastas como `.git`, `.venv`, `node_modules` e caches nunca são varridas, e links simbólicos não são seguidos. Texto acima de 1 MB e binário acima de 25 MB são pulados com o motivo.

Exit: **0** rodou; **1** caminho inexistente ou `--output` inválido; **2** nada foi analisado (inclui um único arquivo de código, recusado com a mensagem "não é prosa").

**Saída de build entra na varredura e domina o ranking.** Só `.git`, `.venv`, `node_modules` e caches ficam de fora; `.next/`, `coverage/`, `dist/`, `build/` e afins não. Num projeto Next.js real (CodeQuest), 850 arquivos foram analisados e os 3 primeiros do ranking eram HTML gerado em `frontend/.next/`. Em repositório com frontend, passe sempre o `--ignore`:

```bash
detect_ai_patterns.py . --format md \
  --ignore 'frontend/.next/*' --ignore 'frontend/coverage/*' --ignore 'frontend/node_modules/*'
```

Para só a documentação, aponte direto a pasta (`Docs`) em vez de varrer a raiz.

## Como ler a saída

- **Cada sinal** traz nome, severidade (`low`, `medium`, `high`), valor (quantas vezes aparece, ou a métrica), a linha e um trecho. Sinais de documento (métricas) não têm linha.
- **Score.** Soma ponderada dos sinais que dispararam (estrutural 2, lexical 1, métrica 0,5; `low`/`medium`/`high` valem 0,33/0,66/1), saturada por `1 − e^(−soma/8)`. Não é probabilidade. Limiares e pesos são escolha da ferramenta, sem calibração contra corpus. `--min-severity` só esconde sinais do relatório: o score usa todos.
- **Confidence** vem do tamanho da amostra: texto com menos de 150 palavras é `low`, menos de 600 é `medium`. PDF limita a `medium`. **Se a confiança é `low`, diga isso junto do score.**
- **Forma do `--format json`.** Chaves de topo: `files_scanned`, `by_format`, `by_signal`, `scores`, `skipped`, `disclaimer`. `scores` é um **dicionário** indexado pelo nome do arquivo, não uma lista; cada entrada traz `format`, `kind`, `score`, `confidence`, `signals[]` (`name`, `value`, `severity`, `line`, `snippet`) e `notes`. Para ranquear: `sorted(d["scores"].items(), key=lambda kv: -kv[1]["score"])`. Procurar `files` ou `results` devolve vazio. Em dúvida, use `--format md`, que já vem ordenado.
- **No relatório `md`:** a tabela "Sinais mais frequentes" (quantos arquivos, severidade máxima) e o "Top 10 arquivos por score", com os sinais de cada um.
- **`.docx`, `.pdf` e `.html`:** as linhas se referem ao texto extraído, não ao arquivo original. O relatório avisa.

## Catálogo de sinais (21)

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

## Regras ao reportar

1. **Sempre repita o disclaimer**, junto do score: *"Score é indicativo, não veredito. Falsos positivos esperados em texto técnico disciplinado."*
2. **Dê o número e a confiança**, nunca só um adjetivo. Score com `confidence: low` é amostra pequena.
3. **Leia o contexto antes de recomendar.** Um documento técnico pode pontuar alto só por usar negrito de abertura e tabelas, que é o formato dele. Isso é falso positivo esperado, não defeito.
4. **Não acuse.** O resultado nunca é prova sobre quem escreveu, e o uso é sobre o que o usuário produziu.
5. **O catálogo é maior que o que pesa.** Há 21 sinais, mas num corpus pessoal de 51 arquivos em português só 13 dispararam, e quatro (`bold_lead_in`, `emoji_heading`, `em_dash_density`, `em_dash_to_comma_ratio`) respondem por cerca de 70% do score do lado IA. Dois deles só existem em Markdown. Tirando os `**`, o AUC desse corpus cai de 0,63 para 0,49: **o score não separa humano de IA, só aponta hábito**. Não o apresente como detecção.

## Precisa agir? Regra de decisão

Antes de recomendar qualquer reescrita, olhe **quais** sinais puxam o score:

- **Sinais ditados pelo formato** (`bold_lead_in` em requisitos com `**Campo:**`, `comparison_table_symmetry`, `paragraph_uniformity` em lista de requisitos, `template_heading` em doc de "Por que existe"): são o gênero do documento. Score até ~0,4 com esses sinais é **falso positivo esperado**. Diga isso e não proponha mexer.
- **Sinais de hábito** (`em_dash_density`, `worth_noting`, `delve_family`, `fast_paced_world`, `hedge_double`): valem uma passada, são baratos de corrigir à mão e melhoram o texto de verdade.
- Nunca persiga o número como meta. Um score baixo não prova autoria humana, e um alto não prova o contrário. Se o motivo do pedido for esconder o uso de IA de quem exige divulgação (disciplina, edital, plataforma), esse é um problema de política, não de estilo: diga isso em vez de otimizar o score.

Caso medido (CodeQuest, `Docs/`): 8 arquivos com algum sinal, máximo 0,41, os três primeiros todos por formato. Conclusão correta: nada a reduzir.

## Próximo passo

- Para **texto** com problema estrutural (negrito de abertura, travessão, título de modelo, "vale notar que"): skill `naturalize`, que aplica transformações determinísticas e mede o efeito.
- Para **prosa** que precisa de reescrita (ritmo, vocabulário): `/clean-user-facing-text`. Atenção: a medição da R10 mostrou que ela **não reduz** o score deste detector.
- **Código** não é analisado nem humanizado: está fora do escopo desta ferramenta.
- Para medir antes e depois: `tools\measure_skill_effectiveness.py ANTES DEPOIS`.
