---
tags:
  - arsenal
  - watermarks-remover
  - prompt-portatil
  - estilometria
status: ativo
criado: 2026-10-21
atualizado: 2026-10-21
versao: "1.0"
objetivo: "Prompt auto-contido para executar o watermarks-remover em qualquer projeto ou documento, sem depender de skills, regras ou arsenais instalados."
---

# Arsenal Watermark

**Este é um prompt auto-contido. Cole em qualquer projeto e execute.** Não depende de Arsenal Python, de `~/.claude/skills/`, de regras globais nem de `run_antigravity_task`. Tudo o que precisa está abaixo: o que o sistema faz, o que ele **não** faz, o comando exato de cada caso, e quando parar. Se o seu agente tiver skills com os nomes `/detect-ai-patterns`, `/naturalize` ou `/remove-ai-marks`, elas só chamam os mesmos comandos; sem elas, use os comandos daqui.

Você é o executor. Siga a árvore de decisão (§4), use os comandos (§5), respeite os limites (§6 e §7) e **reporte o número e o aviso, nunca só um adjetivo**.

---

## 1. O que o sistema é

`watermarks-remover` é uma ferramenta **pessoal e não comercial** em Python, para trabalhar em conteúdo que **o próprio usuário produziu**. Tem duas metades que não se misturam:

1. **Serviço HTTP local** (`service/scripts/server.py`, `127.0.0.1:8765`) e scripts de limpeza. Remove marcas de proveniência em três camadas:
   - **Camada A:** Unicode invisível, espaços exóticos, marcas bidi, caracteres de tag. Determinístico. É a parte mais confiável.
   - **Camada B:** marca estatística de amostragem de tokens (esquemas verde/vermelho, Gumbel, SynthID-Text). Só se reduz por **reescrita** do texto; não há garantia de remoção, e **a eficácia em português não foi medida**. Trate como não validada.
   - **Camada C:** metadados de arquivo (C2PA, EXIF, XMP, propriedades de documento) em PNG, JPEG, WebP, AVIF, HEIC, BMP, GIF, TIFF, SVG, PDF, DOCX, XLSX, PPTX, EPUB, ODT, HTML, Markdown, MP4/MOV/M4A/M4V, WAV, MP3.
2. **CLIs locais de estilometria** (`tools/`), só biblioteca padrão, sem modelo e sem rede: `detect_ai_patterns.py` (lista sinais de estilo por linha), `naturalize.py` (reescreve **estrutura**, não frases), `measure_skill_effectiveness.py` (delta de score antes e depois) e `build_corpus.py` (mede se o detector separa texto humano de texto de IA).

**A realidade, sem enfeite (medida em 2026-10-21, corpus pessoal de 51 textos em português):**

- **O detector do serviço é só inglês.** Usa 36 frases-clichê em inglês, burstiness e MATTR. Em 51 textos em português ele não achou nenhum marcador e teve AUC 0,43 (abaixo do acaso). O serviço agora devolve `language`, `confidence` e `notice`; para qualquer texto que não seja inglês, `confidence` é sempre `low` e `notice` diz que o detector é calibrado para inglês.
- **`tools/stylometry` é experimental.** Tem 21 sinais de prosa, mas no corpus só 13 dispararam, e quatro (`bold_lead_in`, `emoji_heading`, `em_dash_density`, `em_dash_to_comma_ratio`) respondem por cerca de 70% do score do lado IA. `bold_lead_in` é o de maior peso (cerca de 40%) e só existe em Markdown. Tirando os `**`, o AUC do corpus caiu de 0,63 para 0,49. **O score aponta hábito de estilo; não separa humano de IA.** O JSON do CLI traz `experimental: true` e o relatório em Markdown abre com um aviso.
- **Só prosa. Código-fonte está fora do escopo (R15).** O detector de código foi medido e abandonado: na biblioteca padrão do Python (escrita por humanos) 49% dos arquivos dispararam algum sinal, e em código de modelo realista só um sinal disparou. Um arquivo de código passado ao CLI é recusado. Não existe humanizador de código.
- **Conclusão dura (2026-10-21):** o detector de texto **não foi validado em nenhum idioma**. Em português ele não separou humano de IA, nem com o formato igualado (medição preliminar AUC 0,42, d −0,50, n = 20/31, confundida por tamanho e gênero; o corpus pareado não será coletado). Na prática ele serve só como verificação de formatação e de hábitos de estilo, e para análise semântica em português não é confiável. Em inglês o sinal também não foi medido: o detector do serviço é calibrado para inglês, mas nunca foi validado contra corpus.
- **O `/naturalize` troca formato, não estilo.** O delta medido (−0,288, de 0,4401 para 0,1521) é **n = 1** e vem de negrito e dois títulos; o texto não ficou melhor.

Nada aqui acusa autoria, e nenhum número prova que alguém usou ou não IA.

## 2. Pré-requisitos

| Item | Requisito |
|---|---|
| Python | 3.12 ou mais novo (testado em 3.12 e 3.14). O `python` do PATH pode ser o *stub* da Microsoft Store ("Python was not found"): use o da `.venv` do repositório |
| Repositório | Variável de ambiente `WATERMARKS_REPO`. Sem ela, o caminho de instalação padrão do autor é `E:\Projetos\Scripts\watermarks-remover` (só um exemplo: defina a variável na sua máquina) |
| Dependências | Os CLIs de `tools/` e os scripts de limpeza de texto usam só a biblioteca padrão |
| Grupo `formats` (opcional) | `python-docx`, `pypdf`. Necessário para `.docx` e `.pdf` |

Resolver o repositório e o Python:

```powershell
$repo = if ($env:WATERMARKS_REPO) { $env:WATERMARKS_REPO } else { 'E:\Projetos\Scripts\watermarks-remover' }
if (-not (Test-Path "$repo\tools\detect_ai_patterns.py")) { throw "Repositório não encontrado em $repo. Defina WATERMARKS_REPO." }
$py = if (Test-Path "$repo\.venv\Scripts\python.exe") { "$repo\.venv\Scripts\python.exe" } else { 'python' }
```

```bash
REPO="${WATERMARKS_REPO:-/e/Projetos/Scripts/watermarks-remover}"
[ -f "$REPO/tools/detect_ai_patterns.py" ] || { echo "Defina WATERMARKS_REPO" >&2; exit 1; }
PY="$REPO/.venv/Scripts/python.exe"; [ -x "$PY" ] || PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
```

**Instalar o grupo `formats` sem destruir o ambiente:**

```bash
uv pip install --group formats        # ou: pip install --group formats   (pip 25.1 ou mais novo)
uv sync --inexact --group formats     # alternativa com uv
```

> ⚠️ **Nunca use `uv sync --group formats` sozinho.** É uma sincronização **exata**: remove da venv tudo o que não está no grupo, **pytest e ruff inclusos**. Se já fez, reinstale com `uv pip install -r requirements-dev.txt` dentro do repositório.

Sem `formats`, as ferramentas ainda rodam: `.docx` e `.pdf` são pulados com aviso.

## 3. Regras que valem em todo caso

1. **Só conteúdo do próprio usuário.** Não use para analisar ou "limpar" texto de terceiros.
2. **Detectar antes de alterar.** Comece pelo que só lê (`detect_ai_patterns`, `inspect_file`).
3. **Diff antes de gravar.** `naturalize` começa por `--diff-only`. Limpeza de arquivo: grave em cópia (`-o`) e confira, ou use `--in-place` só com backup (os scripts criam `.bak`).
4. **Reporte o número e o aviso.** Dê o score, a `confidence`, o `language` quando houver, e repita o disclaimer da §8. Nunca diga "isto foi escrito por IA".
5. **Peça autorização antes de subir o serviço.** Iniciar processo em segundo plano tem efeito colateral.

## 4. Árvore de decisão

| Situação | Faça |
|---|---|
| **Suspeito de marca num documento** (quero só olhar) | `detect_ai_patterns.py CAMINHO --format md`. **Se o texto é português, ignore o score** e use a lista de sinais só para ver onde olhar. Em inglês, ainda é indicativo, não veredito. Para Unicode e metadados: `inspect_file.py CAMINHO --json` |
| **Quero limpar Unicode invisível de um texto** (Camada A) | `clean_text.py ARQ -o SAIDA --stats` (sem servidor) |
| **Quero limpar metadados** (C2PA/EXIF/XMP, imagem ou documento) | `clean_file.py ARQ -o SAIDA` (sem servidor), ou, com o serviço no ar, `POST /clean`. Inspecione antes com `inspect_file.py`. **Se o serviço não estiver rodando, pare e peça ao usuário para iniciar.** |
| **Quero reduzir marca estatística em prosa** (Camada B) | Reescreva o texto à mão ou com o seu agente, depois limpe de novo a Camada A. Meça com `detect_ai_patterns` antes e depois. Sem garantia; em português, sem validação |
| **Quero naturalizar um `.md` ou `.txt`** | `naturalize.py ARQ.md --diff-only --format md` → **ler o diff inteiro** → `--output COPIA.md` ou `--in-place` → `measure_skill_effectiveness.py ANTES DEPOIS` |
| **É `.docx`, `.pdf` ou `.html`** | Confirme o `formats` (§2). Sem ele, declare a limitação e pare. `.docx` perde o negrito inline na leitura: `bold_lead_in` não dispara |
| **É código-fonte** | Fora do escopo: o detector recusa `.py`, `.ts`, `.js` e afins. **Não** use `naturalize` e **não** reescreva código para baixar score |
| **Quero decidir se vale treinar um modelo (ML)** | `build_corpus.py init` → preencher `human\` e `ai\` com 10 ou mais arquivos cada, **no mesmo formato** → `check` → `compare` → ler d, intervalo e AUC. Com o corpus pessoal atual, nenhum número é válido |
| **O serviço está offline** | Declare ao usuário (`curl http://127.0.0.1:8765/health` recusa). **Não suba o servidor você mesmo**: peça autorização, entregue o comando e pare (ver "Regra de Ouro do Serviço", §5) |

## 5. Comandos exatos

### Regra de Ouro do Serviço

> **Atenção (IA):** NUNCA inicie o `watermarks-server` automaticamente. O servidor roda em primeiro plano e travará a sessão. Se o endpoint `/health` estiver offline, **peça autorização ao usuário** e instrua-o a abrir uma nova janela de terminal e rodar `watermarks-server` manualmente (na prática: `.\start-watermarks-server.ps1` ou `python service/scripts/server.py --host 127.0.0.1 --port 8765`, a partir da raiz do repositório).

Execute a partir da raiz do repositório (`$py` e `$PY` são o Python da §2).

### Detectar: `tools/detect_ai_patterns.py`

```bash
"$PY" tools/detect_ai_patterns.py CAMINHO [--format json|md] [--only text|all] \
    [--min-severity low|medium|high] [--ignore GLOB] [--output ARQUIVO]
```

- Aceita arquivo ou pasta. **Só prosa:** `.md .txt .html .docx .pdf`. Um único arquivo de código é recusado (exit 2, "não é prosa"); numa pasta, é ignorado. `--only` fica por compatibilidade: `text` e `all` fazem o mesmo.
- Saída: por arquivo, `score` (0,0 a 1,0), `confidence` (`low`, `medium`, `high`) e `signals` com linha e trecho. O JSON traz `experimental: true` e `notice`; o Markdown abre com o aviso.
- **Exit:** 0 rodou · 1 caminho inexistente ou `--output` inutilizável · 2 nada foi analisado.

### Naturalizar: `tools/naturalize.py`

```bash
"$PY" tools/naturalize.py ARQUIVO.md --diff-only --format md      # 1º: só mostra, não grava
"$PY" tools/naturalize.py ARQUIVO.md --output COPIA.md             # grava numa cópia
"$PY" tools/naturalize.py ARQUIVO.md --in-place                    # atômico; mantém BOM, fim de linha e permissão
# opções: --signals CSV  --preserve GLOB (repetível)  --format text|md|json
```

- Só `.md` e `.txt`, UTF-8, até 1 MB. São 8 reescritas estruturais: `bold_lead_in`, `em_dash_density`, `template_heading`, `emoji_heading`, `hedge_double`, `delve_family`, `worth_noting`, `fast_paced_world`. **Não reescreve frases.**
- Limites medidos: `hedge_double` só funde hedges adjacentes (não pega "Arguably, perhaps…" com vírgula); `fast_paced_world` aceita um adjetivo; o dicionário de títulos é de correspondência exata (`Por que isso importa` → `Relevância`).
- **Idempotente:** rodar de novo sobre a saída dá exit 3. Link de **outro** arquivo para um título renomeado não é visto: por isso o diff vem primeiro.
- **Exit:** 0 mudou algo · 1 caminho inválido ou falha ao gravar · 2 entrada não suportada (extensão, não UTF-8, mais de 1 MB) ou erro de uso · 3 nada aplicável.

### Medir: `tools/measure_skill_effectiveness.py`

```bash
"$PY" tools/measure_skill_effectiveness.py ANTES DEPOIS [--format json|md] [--signals sinal1,sinal2] [--output ARQUIVO]
```

Dois arquivos, ou duas pastas. Dá o delta de score, a efetividade e os sinais eliminados e introduzidos. **Exit:** 0 rodou · 1 caminho ausente ou tipos diferentes · 2 nada pareado.

### Corpus: `tools/build_corpus.py`

```bash
"$PY" tools/build_corpus.py init    --dir PASTA_FORA_DO_REPO
"$PY" tools/build_corpus.py check   --dir PASTA --mode text
"$PY" tools/build_corpus.py compare --dir PASTA --mode text    # --mode all faz o mesmo; --mode code não existe mais
```

- `init` cria `human\` e `ai\` e **recusa** uma pasta dentro do repositório. O padrão é a pasta temporária do sistema, que o Windows pode limpar: use `--dir`.
- `compare` imprime Cohen's d com intervalo de 95%, a AUC e uma recomendação (`determinístico suficiente`, `inconclusivo` ou `ML justificado`) pela faixa em que o **intervalo inteiro** cai. Mínimo de 10 arquivos por pasta, 30 ou mais para ficar estável. Leia `ML justificado` como "o detector atual não separa", não como "treine um modelo".
- **Exit:** 0 rodou · 1 corpus ausente, pequeno, degenerado ou impossível de criar · 2 erro de uso.

### Limpeza e inspeção de arquivo (sem servidor)

```bash
"$PY" service/scripts/inspect_file.py ARQ [--json] [--aggressive] [--as auto|text|image|container|av]
"$PY" service/scripts/clean_text.py   ARQ -o SAIDA [--nfkc] [--keep-em-dash] [--strip-bidi] [--stats]
"$PY" service/scripts/clean_file.py   ARQ -o SAIDA [--keep-em-dash] [--keep-non-ai-metadata] [--json]
```

Texto, imagem, áudio e vídeo, e contêineres de documento. Use `--in-place` só se aceitar o `.bak` que o script cria. `--force-text` reescreve bytes de binário e **corrompe o arquivo**: não use.

### Serviço HTTP (só `/clean`, `/inspect`, `/detect` e o resto da API)

```bash
"$PY" service/scripts/server.py --host 127.0.0.1 --port 8765     # ou: .\start-watermarks-server.ps1
curl http://127.0.0.1:8765/health          # saúde; /readyz, /capabilities, /openapi.json também
```

- Rotas: `GET /health`, `/readyz`, `/capabilities`, `/openapi.json`; `POST /inspect`, `/detect`, `/clean` e as variantes `/batch`. O corpo leva o arquivo em base64 (`{"file": "...", "name": "x.md"}`).
- **Só `/remove-ai-marks` e `/clean-user-facing-text` (skills) dependem do serviço.** `detect_ai_patterns`, `naturalize`, `measure` e `build_corpus` **não** usam o serviço.
- `/detect` e `/inspect` trazem, na entrada `stylometry`, os campos `language` (`en`, `pt`, `unknown`), `confidence` (`low` ou `medium`, nunca `high`) e, fora do inglês, `notice`. O campo `suspicious` do `/inspect` (score ≥ 0,65) **não tem sentido em português**.
- O serviço é local: **recusa** bind fora de loopback sem `WATERMARKS_SERVER_API_KEY`. Não use `--allow-insecure-bind`. Com a chave definida, as rotas pedem `Authorization: Bearer`. **Nunca imprima a chave.**
- Não existem `/healthz` nem `/naturalize`.

## 6. Quando NÃO usar

- **Código-fonte** no `detect_ai_patterns` (recusado) ou no `naturalize` (só `.md` e `.txt`). Não existe detector nem humanizador de código, e a remoção de marca estatística em código não compensa. Exceção segura: Unicode invisível.
- **Acusar terceiros** ou usar o resultado como prova de autoria. O score é indicativo, não veredito.
- **Onde a divulgação de autoria é exigida** (trabalho acadêmico, jurídico, contratual, política de plataforma). Remover marca nesse contexto é problema de conformidade, não tarefa técnica: devolva ao usuário.
- **Trechos que devem ficar literais:** citações, normas, identificadores, comandos, caminhos, fórmulas.
- **Texto em português, para tirar conclusão do score** do serviço (é só inglês) ou do `tools/stylometry` (experimental).
- **Reescrever até o score baixar.** Baixar o score não prova autoria humana.

## 7. Modos de falha comuns

| Sintoma | Causa | O que fazer |
|---|---|---|
| `curl .../health` recusa a conexão | Serviço offline | Declare, peça autorização e suba; só afeta `/clean` e skills de limpeza |
| "Python was not found" | O `python` do PATH é o stub da Microsoft Store | Use o `python` da `.venv` do repositório |
| `.docx`/`.pdf` "pulado" com aviso, ou exit 2 de "nada analisado" | Grupo `formats` ausente | `uv pip install --group formats` e rode de novo |
| `detect_ai_patterns` sai com exit 2 e "não é prosa" | Você passou um arquivo de código (`.py`, `.ts`, `.js`...) | Esperado: código está fora do escopo desde a R15 |
| `pytest` sumiu depois de instalar `formats` | `uv sync --group formats` é sincronização **exata** | `uv pip install -r requirements-dev.txt`. Da próxima vez, `uv pip install --group formats` |
| `naturalize` sai com exit 3 | Nada aplicável, ou é a 2ª passada (idempotente) | Esperado. Confira o diff do arquivo original |
| `build_corpus compare` diz "faltam N arquivo(s) em human" | Os `.docx` foram pulados por falta de `formats` | Instale `formats`; não conclua "corpus vazio" |
| AUC alto ou baixo "demais" no corpus | **Confundidor de formato:** humano em `.docx`, IA em `.md`. O loader de `.docx` descarta o negrito inline, então `bold_lead_in` só dispara no lado `.md` | Use o mesmo formato nos dois lados. Com os `**` retirados do lado IA, o AUC de 0,63 caiu para 0,49 |
| Score alto em documento técnico disciplinado | Negrito de abertura e tabelas são o formato dele | Falso positivo esperado; leia o contexto |
| `build_corpus init` recusa a pasta | Está dentro do repositório (texto pessoal não vai para o git) | Use uma pasta fora dele |
| O `notice` aparece em tudo que não é inglês | O detector do serviço é calibrado para inglês | Esperado. Use o resultado só como pista |

## 8. Disclaimer final

- **O score é indicativo, não veredito.** Nunca diz quem escreveu, e nunca prova autoria.
- **Baixar o score não prova autoria humana**, e reduzir um score não é evasão de detector de terceiros.
- **A medição n = 1 do `docs/DONE.md` do repositório (delta −0,288) é frágil por natureza:** vem de formatação de um arquivo. O AUC do corpus pessoal (0,63) **não vale**: mede formato, não estilo. Nenhum número do detector sustenta decisão de ML.
- O uso é **pessoal e não comercial**. Divulgação de uso de IA exigida por política, contrato ou norma **deve ser mantida**.
- O detector do serviço é **calibrado para inglês**; o `tools/stylometry` é **experimental**. Diga isso ao usuário toda vez que reportar um número.

## 9. Como estender

Para quem mantém o repositório. Cada passo leva um teste.

- **Novo sinal de estilo:** declare em `tools/stylometry/__init__.py` (`CATEGORY`) e implemente em `tools/stylometry/text.py`. Todo sinal entra numa tabela parametrizada de `tests/test_stylometry_text.py`. Pesos: estrutural 2,0, lexical 1,0, métrica 0,5. **Não** recalibre com um corpus de 51 arquivos.
- **Nova reescrita do `naturalize`:** acrescente em `_STEPS` de `tools/stylometry/naturalize.py`, mantenha a idempotência (o teste compara 2 passagens com 1) e acrescente um caso em `tests/fixtures/stylometry/naturalize/<nome>/before.md` e `after.md`.
- **Novo caso do corpus:** `tools/build_corpus.py` (modos `text` e `all`, que fazem o mesmo); documente em `docs/CORPUS.md`.
- **Campo novo no serviço:** só **aditivo** em `/detect` e `/inspect`; descreva no OpenAPI (`STYLOMETRY_NOTE` em `service/scripts/server.py`) e prenda o formato em teste.
- **Depois de editar:** `python -m ruff check service tests tools`, `python -m ruff format --check service tests tools` e `python -m pytest -rs` (com o grupo `formats` instalado, ou os testes de `.docx` e `.pdf` pulam).
