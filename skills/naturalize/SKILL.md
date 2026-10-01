---
name: naturalize
description: Remove padrões estilométricos de IA de texto (.md, .txt) aplicando transformações determinísticas (em-dash denso, bold lead-in, template headings, hedges duplos, verbo "delve", "vale notar que", aberturas de "mundo acelerado"). Preserva fatos, números, código, URLs, citações. Mede a efetividade com o compare da R10. Use quando o usuário pedir "humaniza esse texto", "remove o padrão de IA", "esse texto parece IA?", "deixa mais natural", "tira a cara de IA", ou invoca /naturalize. Não cobre .html, .docx, .pdf nem código.
---

# Naturalize: tira do texto os hábitos que o detector conta

Ferramenta do repositório `watermarks-remover`. Reescreve, de forma **determinística e conservadora**, os hábitos de estilo que `detect_ai_patterns` marca em texto, e mostra quanto o score caiu. Sem modelo e sem rede: cada transformação é uma regex sobre o texto, e rodar duas vezes dá o mesmo resultado que rodar uma.

Este arquivo também é a documentação. Se o usuário perguntar "como isso funciona?", responda a partir das seções abaixo, sem abrir o código.

## Quando usar, e quando não

- **Use** para um `.md` ou `.txt` cujo problema é estrutural: negrito de abertura (`**Termo** — definição`), travessão demais, títulos de modelo ("Why this matters"), "vale notar que", "delve into".
- **Não use** para `.html`, `.docx`, `.pdf` (o CLI sai com exit 2: extraia o texto antes) nem para código.
- **Prosa que precisa de reescrita semântica** (frases de comprimento uniforme, vocabulário repetido, ritmo) é outro trabalho: use `/clean-user-facing-text`. O `naturalize` não reescreve frase nenhuma.

## Onde está o CLI

Caminho do repositório: a variável de ambiente `WATERMARKS_REPO`, e, se ela não existir, `E:\Projetos\Scripts\watermarks-remover` (o mesmo padrão do `watermarks-server.cmd`). O script é `tools\naturalize.py` e só usa a biblioteca padrão, então funciona de qualquer diretório.

PowerShell:

```powershell
$repo = if ($env:WATERMARKS_REPO) { $env:WATERMARKS_REPO } else { 'E:\Projetos\Scripts\watermarks-remover' }
if (-not (Test-Path "$repo\tools\naturalize.py")) { throw "Repositório não encontrado em $repo. Defina WATERMARKS_REPO." }
$py = if (Test-Path "$repo\.venv\Scripts\python.exe") { "$repo\.venv\Scripts\python.exe" } else { 'python' }
& $py "$repo\tools\naturalize.py" ARQUIVO --diff-only
```

Bash (Git Bash, WSL, Linux, macOS):

```bash
REPO="${WATERMARKS_REPO:-/e/Projetos/Scripts/watermarks-remover}"   # no WSL: /mnt/e/Projetos/Scripts/watermarks-remover
[ -f "$REPO/tools/naturalize.py" ] || { echo "Repositório não encontrado em $REPO. Defina WATERMARKS_REPO." >&2; exit 1; }
PY="$REPO/.venv/Scripts/python.exe"; [ -x "$PY" ] || PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
"$PY" "$REPO/tools/naturalize.py" ARQUIVO --diff-only
```

Prefira o Python da `.venv` do repositório. Nesta máquina o `python` do PATH é o stub da Microsoft Store ("Python was not found"): se o fallback falhar assim, use o interpretador real (3.12 ou mais novo) e diga isso ao usuário.

## Comando

```
naturalize.py CAMINHO [--format text|md|json] [--diff-only | --in-place]
                      [--signals CSV] [--preserve GLOB]... [--output ARQUIVO]
```

| Flag | O que faz |
|---|---|
| (nenhuma) | imprime o texto naturalizado no stdout; o arquivo não é tocado |
| `--diff-only` | imprime o diff unificado e não escreve nada |
| `--in-place` | substitui o arquivo de uma vez (escrita atômica), mantendo BOM e fim de linha |
| `--format md` / `json` | relatório: scores, sinais antes e depois, cada edição e o diff (o `json` traz também o que foi protegido) |
| `--signals a,b` | só essas transformações (nomes da tabela abaixo) |
| `--preserve GLOB` | repetível. Se o glob casa com o caminho do arquivo, o arquivo não é tocado. Se casa com uma linha, a linha não é tocada |
| `--output ARQUIVO` | grava o resultado ali em vez de no stdout |

Exit: **0** mudou algo; **1** caminho inexistente, não é arquivo ou falha ao escrever; **2** formato não suportado (só `.md` e `.txt`), não é UTF-8, ou maior que 1 MB; **3** nada aplicável (o texto sai igual). Exit 3 não é erro.

## O que muda

Cada transformação só roda se o detector da R10 ainda dispara o sinal dela no texto **atual**. Um sinal que o detector não vê (por exemplo, dois negritos de abertura, abaixo do limiar de três) não é tocado.

| Sinal | Antes → depois |
|---|---|
| `bold_lead_in` | `**Termo** — definição`, `**Termo**: x`, `**Termo:** x` → `Termo: definição` |
| `em_dash_density` | `a — b` → `a, b` (também atende `em_dash_to_comma_ratio`). Não em título, tabela, citação, código, nem entre dígitos (`10—20`) |
| `template_heading` | `## Why this matters` → `## Relevance`; `## Por que isso importa` → `## Relevância`. Só títulos de um dicionário pequeno, e no idioma do título |
| `emoji_heading` | `## 🚀 Próximos passos` → `## Próximos passos`. Emoji fora de título fica |
| `hedge_double` | `pode ser que talvez X` → `talvez X`. Mantém **um** hedge: tirar os dois transformaria dúvida em certeza |
| `delve_family` | `delve into X`, `let's dive into X` → `look at X`, com a flexão do verbo |
| `worth_noting` | `Vale notar que X` → `X`; `It's worth noting that X` → `X`. Só no começo de frase ou depois de vírgula, sem negação antes |
| `fast_paced_world` | apaga `In today's fast-paced world, `, `No mundo de hoje, `, `Nos dias de hoje, `. Só no começo de frase |

## O que nunca muda

Antes de transformar, estes trechos viram marcadores opacos e voltam idênticos no fim:

- números (`1234`, `0.5`, `50%`, `2 MB`: nenhuma regra toca dígito; `10—20` é intervalo e fica);
- hashes (`3f7c25d`), código inline (`` `code` ``), blocos de código (cercados por ``` ou ~~~, e indentados), front matter, e títulos setext (texto sublinhado com `===` ou `---`);
- URLs, e-mails, destinos de link, caminhos (`E:\...`, `/usr/...`, `docs/x.md`), tags HTML;
- citações entre aspas (`"..."`, `“...”`, `«...»`, `'...'`) e citações em bloco (`>`); uma aspa ou crase que abre numa linha e fecha na seguinte segura o parágrafo até fechar;
- identificadores (`snake_case`, `CamelCase`, `UPPER_CASE`), e tabelas markdown inteiras (também as sem pipe inicial: toda linha com `|` fora de código fica);
- intervalos numéricos com travessão, colado ou com espaço (`10—20`, `1999 — 2005`, `9h — 17h`, `5% — 10%`).

Um identificador ou e-mail no começo da oração não é capitalizado quando um lead-in cai (`Vale notar que get_user falha` → `get_user falha`).

## Fluxo recomendado

1. **Detectar**: rode `detect_ai_patterns.py` (skill `detect-ai-patterns`) e guarde o score.
2. **Revisar antes de gravar**: `naturalize.py ARQUIVO --diff-only`. Mostre o diff ao usuário. Em especial, um título renomeado muda a âncora dele: a ferramenta protege links `#slug` do **mesmo** arquivo, mas não enxerga links de **outros** arquivos.
3. **Aplicar**: `--in-place` se o arquivo está no git (dá para reverter), ou `--output COPIA.md` para manter o original.
4. **Medir**: `measure_skill_effectiveness.py ANTES DEPOIS`. O `delta` de lá é o mesmo que o `naturalize.py --format json` reporta.
5. **Reportar** com números reais (ver abaixo).

## Como ler o resultado

`--format json` traz `score_before`, `score_after`, `delta` (`depois − antes`; negativo é melhora), `effectiveness` (`high` abaixo de −0,30; `medium` de −0,30 a −0,10 exclusive; `low` no resto), `signals_before`, `signals_after`, `transforms` (cada linha editada), `preserved_spans` (o que foi protegido), `confidence` e `disclaimer`. O score é o de `detect_ai_patterns` (`1 − e^(−soma/8)`, sem calibração contra corpus).

O score satura por faixa de severidade. Cair de 9 ocorrências para 3 de um mesmo sinal pode não mexer no score, porque as duas contagens já são `high`. Um delta pequeno não significa que a ferramenta falhou: olhe `signals_after` e as contagens.

## Limitações honestas

- **Não reescreve frases.** `sentence_uniformity`, `paragraph_uniformity` e `type_token_ratio` ficam como estão. Tabelas (`comparison_table_symmetry`) também: tabela é dado.
- **Só o que o dicionário conhece.** "O que saiu" (→ "Resultado"), "O que falta" e "O que significa" são trocados; um título como "O que é isto" é contado pelo detector, mas não é trocado. `dive in` sem objeto, `mergulhar` em português e hedges separados por quebra de linha ficam.
- **Código indentado dentro de item de lista não é reconhecido** (dentro de lista, linha indentada conta como continuação). Use bloco cercado por ``` nesses casos.
- **Travessão vira vírgula também onde a frase pediria ponto.** Fica legível, mas revise o diff. Um intervalo sem número (`segunda — sexta`) vira lista (`segunda, sexta`).
- **Texto quebrado em linhas fixas (hard-wrap).** Uma linha que continua a anterior (a anterior não termina em ponto) não é começo de frase, então um "vale notar que" ali fica. O mesmo vale para um `**Termo** — x` colado, sem linha em branco, logo abaixo de outro item.
- **Nome de ferramenta em minúscula** fora de uma lista curta (`pip`, `npm`, `git`, `uv`...) é capitalizado se abrir a frase depois de um lead-in removido. Aspas curly aninhadas protegem só o par de dentro.
- **Falso positivo em texto técnico disciplinado.** Um documento pode pontuar alto só por usar negrito e tabelas, que é o formato dele. Nesse caso reduzir o score não melhora o texto.
- **Não é evasão de detector.** O score é estilométrico desta ferramenta, não de um detector de terceiros. Baixá-lo não prova autoria humana nem torna o texto indetectável, e divulgações exigidas (acadêmicas, legais, de plataforma) devem ser mantidas.

## Exemplo

Entrada, `nota.md`:

```markdown
## Why this matters

- **Velocidade** — o parser roda em tempo linear.
- **Segurança**: entradas hostis rodam isoladas.
- **Custo:** zero dependências.

In today's fast-paced world, vale notar que o commit 3f7c25d mudou 1234 linhas — e `delve into` segue no código.
```

Saída de `naturalize.py nota.md`:

```markdown
## Relevance

- Velocidade: o parser roda em tempo linear.
- Segurança: entradas hostis rodam isoladas.
- Custo: zero dependências.

O commit 3f7c25d mudou 1234 linhas — e `delve into` segue no código.
```

Score 0.28 → 0.04 (delta −0.24, efetividade `medium`, confiança `low`: texto curto). O hash, o número e o código inline passaram intactos. O travessão da última linha ficou porque um só está abaixo do gate do detector, e `delve into` ficou porque está entre crases.

## Como reportar ao usuário

- Dê `score_before`, `score_after` e `delta` como números, com `effectiveness` e `confidence`.
- Delta entre −0,10 e 0: diga que melhorou **marginalmente**. Delta acima de 0: diga que **piorou** e por quê; não declare sucesso.
- Liste os sinais que sobraram e por que (fora de escopo, protegidos, abaixo do gate).
- Repita o disclaimer: **score é indicativo, não veredito**.
