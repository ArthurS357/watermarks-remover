# DONE — watermarks-remover

Histórico append-only. Mais recente no topo.

## Estado do sistema — 2026-10-01 (R12)

| ID | Item | Estado | Commit |
|---|---|---|---|
| R12-05 | CI vermelha no primeiro push | 🟡 causa achada e corrigida; só um push novo confirma a CI verde | 8568366 |
| R12-01 | `_TEMPLATES`: `o que saiu`, `o que falta`, `o que significa` | ✅ fechado, delta no `DONE.md` −0,288 | be80556 |
| R12-02 | Detector fecha cerca só com trecho nu do tamanho do abridor | ✅ fechado, sem efeito medido nos arquivos do repo | 3924467, 30eb72e |
| R12-03 | `tools/build_corpus.py` e `docs/CORPUS.md` | ✅ ferramenta pronta; **sem número real**, o corpus está vazio | 908c3a5, 0fad1f0 |
| R12-04 | `clean-user-facing-text` instalada sincronizada com o repo | ✅ operacional, sem commit | — |
| R12-06 | `comparison_table_symmetry` em tabela de pares chave e valor | ✅ decidido: aceito, sem código | este commit |
| R12-07 | Strings gatilho no README como exemplo | ✅ decidido: esperado, sem código | este commit |

| Medida | Início (`3d7a1be`) | Fim (`0fad1f0`, antes deste registro) |
|---|---|---|
| Testes, `.venv` sem o grupo `formats` | 1790 coletados / 1720 passed / 70 skipped | 1849 / 1779 / 70, 0 falhas, exit 0 |
| Testes, venv com `formats` | 1790 / 1782 / 8 (valor da R11; não remedi antes de editar) | 1849 / 1841 / 8, 0 falhas, exit 0 |
| `ruff check .` e `ruff format --check .` | limpos, 126 arquivos | limpos, 129 arquivos |
| `mypy --strict` em `tools/` | limpo, 9 arquivos | limpo, 10 arquivos |
| `pip-audit` (`.venv`) | 0 vulnerabilidades | 0 |
| Bandit (`tools/`, `install_skill.py`) | 0 achados | 0 |
| `vulture` (60%) e `pylint` duplicate-code | 0 e 10/10 | 0 achados em `build_corpus.py`, 10/10 |
| Cobertura de ramo | motor 100% | motor 100% (299 instruções, 96 ramos), `text.py` 100%, `build_corpus.py` 99% (só o `sys.exit(main())`, que roda no teste de subprocesso) |
| `service/` e `skills/` | | sem diff desde `3d7a1be` |

R12 pronta para uso: sim, com três pendências que dependem de você e estão nos riscos abaixo (confirmar a CI com um push, preencher o corpus, e uma linha desatualizada na skill `naturalize`). Nenhum `git push` foi feito: oito commits locais à frente de `origin/main`, contando o deste registro.

## Rodada R12 — 2026-10-01 — Fechar os gaps restantes

O plano foi escrito antes de qualquer edição, em c120491 (`docs/TODO.md`). As diferenças entre ele e o que saiu estão em "Ajustes durante a execução" (L1 a L8), no mesmo arquivo, e os seis achados da FASE 0 que mudaram premissas do prompt estão em B1 a B6.

### CI (R12-05)

O push de `3d7a1be` deixou o run 36882959726 vermelho. Diagnóstico:

| Job | Resultado |
|---|---|
| `lint` | passou |
| `test (ubuntu-latest, 3.12)` | falhou no step `Test`: um teste, `test_the_read_itself_is_capped_even_if_stat_lies`, com `AttributeError: 'Tiny' object has no attribute 'st_mode'` |
| as outras 5 combinações | canceladas por fail-fast antes de terminar |
| `make test-cov-subprocess` | pulado, nunca rodou |

A causa não era Makefile, `$(CURDIR)` nem `python3`. O teste trocava `Path.stat` por um objeto só com `st_size`. No Python 3.12 `Path.is_file()` lê `self.stat().st_mode`; no 3.14 vai direto a `os.path.isfile`. Por isso passava aqui, que só tem 3.14. O Makefile usa TAB e `$(CURDIR)` corretos, conferido com `cat -A`. A correção é uma linha no teste (8568366).

Não foi possível confirmar: sem push não há CI nova, e não há Python 3.12 nesta máquina (`uv python list` só oferece o download, que não fiz sem autorização). Só o job do Linux 3.12 rodou até o fim, com uma falha em toda a suíte, então Windows e macOS no 3.12 seguem sem resultado. O gap #5 fecha quando um push novo ficar verde.

### Entregas

- `tools/stylometry/naturalize.py`: três chaves no `_TEMPLATES` (`o que saiu` → `Resultado`, `o que falta` → `Pendências`, `o que significa` → `Implicações`). O prompt dizia que o dicionário só tinha inglês; já tinha onze chaves em português, e faltavam as que o `DONE.md` usa. Duas sugestões do prompt não entraram: `o resultado final` (o detector não marca esse título, então trocá-lo mexeria num título que ninguém apontou) e `a linha de fundo` → `Resumo` (a chave existe com o valor `Conclusão`). A R11 tinha fixado o contrário para `O que saiu` em `tests/test_naturalize.py`; esse teste agora afirma o comportamento novo.
- `tools/stylometry/text.py`: `_mask` fecha uma cerca só com um trecho nu, do mesmo caractere e pelo menos do tamanho do abridor. A regra (`_closes`) saiu do motor e agora existe uma só vez, usada pelos dois. O prompt dizia que o detector contava sinais dentro de cercas; na verdade ele já mascarava cerca simples (o teste de aceitação do prompt passava antes da correção, e ficou como pin). O erro real era o fechamento frouxo: um ` ``` ` dentro de um ```` ```` ```` encerrava o bloco de fora.
- `tools/build_corpus.py` (`init`, `check`, `compare`) e `docs/CORPUS.md`. Reusa `detect_ai_patterns.scan`. `compare` imprime Cohen's d, o intervalo de 95% de d, a AUC e uma recomendação. O rótulo é a faixa em que o intervalo inteiro cai (d ≥ 0,8 `determinístico suficiente`, de 0,5 a menos de 0,8 `inconclusivo`, abaixo de 0,5 `ML justificado`); intervalo que cruza um limiar dá `inconclusivo`. O guard recusa pasta dentro do repo, inclusive escrita com o prefixo `\\?\` do Windows. Um teste fixa os números e rótulos do documento às constantes do script.
- `clean-user-facing-text` instalada: ver a seção de sincronização.

### Corpus (R12-03)

`py tools\build_corpus.py init` criou `%TEMP%\corpus\` (com `human\`, `ai\` e um `README.md`); `check` e `compare` saíram com 1: 0 arquivos em cada pasta, faltam 10. **Não existe número real de separabilidade nesta rodada**, e nenhum texto foi inventado para preencher a lacuna. O exemplo no `docs/CORPUS.md` vem de uma execução real sobre os dois textos de teste do repositório, e o documento diz que serve só para mostrar o formato. A pasta temporária pode ser limpa pelo Windows; para manter, `--dir` em outro lugar. Passo seguinte, do usuário: pôr 10 ou mais arquivos (30 para ficar estável) em cada pasta e rodar `compare`.

### Sincronização de `clean-user-facing-text` (R12-04)

Backup da pasta instalada inteira em `%TEMP%\clean-ufc.bak.20261001-123348`, depois `install_skill.py --skill clean-user-facing-text --cursor-home ~/.claude --force`. O instalador deixou uma pasta `.backup.5da4d3d11662` dentro de `skills/`, com outro `SKILL.md`; ela foi **movida** para `%TEMP%`, não apagada. Depois: os 7 arquivos da instalada têm o mesmo hash do repo, e `git status` de `skills/` e `service/` segue vazio.

Hash (SHA-256, 12 primeiros caracteres) da instalada antes, e o do repo, que a instalada passou a ter:

- `scripts/clean_text.py`: `827BEE267055` (22/08) → `C7A95FC8BAE5`
- `scripts/common.py`: `B1D242E740A3` (07/09) → `CA1BA91B420A`
- `scripts/inspect_text.py`: `098B43DEFC08` (22/08) → `6B2D2EDFF290`
- `scripts/text_unicode.py`: `8BEC9A737966` (22/08) → `CACB1F5CDC49`
- `SKILL.md`: `1154C2A1D9B0` (07/09) → `649BBC6D399C`, com a seção da R11-06
- `references/*` (2 arquivos): já iguais, sem mudança

A instalada também tinha um `scripts/common.py.bak.20260907` solto que não existe no repo. Ele não está mais na instalada e continua no backup. Quem chamar scripts da cópia antiga por caminho fixo agora recebe os do repo; o backup tem a versão anterior.

### Decisões de política (R12-06 e R12-07), sem código

`comparison_table_symmetry` é falso positivo esperado em tabela estrutural: par chave e valor, ou comparação com duas colunas. O detector marca tabela cujas colunas têm o mesmo tamanho médio de célula, e não distingue um par `Medida | Valor` de uma tabela de IA. As duas tabelas marcadas no repo são desse tipo: `Medida | Valor final` na seção da R9 deste arquivo e `Tool | Role` no README. Calibrar o limiar para não pegá-las deixaria de pegar tabelas genuínas. A recomendação do `measure_skill_effectiveness` (usar tabela só se as colunas diferirem de verdade) segue válida para tabela narrativa. Por isso é o único sinal que sobra depois do naturalize no `DONE.md`.

Sinais do README que são autorreferência: o README documenta as transformações do naturalizador com as próprias strings gatilho como exemplo. Nas linhas 918 a 920 e 963: `hedge_double`, `delve_family`, `fast_paced_world`, `worth_noting` e uma segunda ocorrência de `delve_family`. São artefato de documentação, não lacuna do texto. Decisão: opção B, documentar e não agir. Um `--exclude-self-reference` exigiria o detector distinguir menção de uso, o que é caro e sem ganho para um caso que se explica sozinho. Os outros sinais do README são de outra natureza: `comparison_table_symmetry` (acima), `em_dash_to_comma_ratio` (o texto usa muito travessão) e `template_heading` em `#### Why PDF needs qpdf, not just exiftool`, que é título legítimo pego pelo prefixo `why` do detector. Nenhum recebe ação.

### Revisões

`python-review` (agente `python-reviewer`) sobre o diff acumulado, com `ruff`, `mypy --strict`, `bandit` e os testes rodados por ele: **0 críticos, 0 altos, 5 médios, 5 baixos**. Reproduzi os dois que podiam enganar (1 e 2) antes de corrigir; os demais pela leitura do código ou pela conta.

| # | Achado | Estado |
|---|---|---|
| 1 MÉDIA | Guard burlado por caminho com prefixo `\\?\` (`resolve()` o mantém e `is_relative_to` dizia "fora") | Corrigido, 908c3a5, com teste (só roda no Windows) |
| 2 MÉDIA | 10 cópias do mesmo texto por lado davam d = +inf e `determinístico suficiente`, e um teste fixava isso | Corrigido: `compare` recusa corpus sem variância, o teste foi invertido |
| 3 MÉDIA | Rótulo instável com n pequeno (com d verdadeiro 0,8 e 10 por lado, 25% das vezes saía `ML justificado`); o doc mandava confiar na AUC e o código a ignora | Corrigido: intervalo de 95% de d e rótulo pela faixa do intervalo inteiro. A AUC continua só como conferência, e o doc agora diz isso |
| 4 MÉDIA | Cerca sem fechamento apaga o resto do texto, sem nota | **Não corrigido.** É o comportamento do CommonMark e vem da R10; risco residual |
| 5 MÉDIA | Testes fracos ou com efeito colateral (o do guard criava pasta no repo se regredisse) | Corrigido: `ROOT` falso em `tmp_path`, mensagem no stderr, frases exatas do doc, faixa completa no `check` |
| 6 BAIXA | `d` impresso arredondava para o outro lado do limiar | Corrigido: 3 casas e rótulo pelo intervalo |
| 7 BAIXA | `README.md` do corpus sem criação exclusiva; `<tmp>/corpus` compartilhado em POSIX | `open("x")` aplicado. Para POSIX, uma frase no doc; a ferramenta é de uso pessoal no Windows |
| 8 BAIXA | Dica de comando sem aspas | Corrigido |
| 9 BAIXA | Arquivos de outra extensão eram ignorados em silêncio | `check` conta "ignorado(s)". Pastas `build/`, `dist/`, `node_modules/` seguem fora, herdado do detector |
| 10 BAIXA | `_FENCE` aceita recuo de 4 ou mais; a docstring de `_closes` exagerava | Docstring corrigida, 30eb72e. `_FENCE` não mudou: é anterior e mudaria detector e motor |

`code-reviewer`: roteiro da skill aplicado por mim sobre o diff `3d7a1be..0fad1f0`, junto do agente acima (intenção: fechar os gaps de efetividade, detecção, corpus e CI; estrutura: uma função movida em vez de duplicada, um script que reusa o detector; detalhes: as correções acima; testes: RED visto nos casos novos, os dois pins marcados como pin). Veredito: Approve. Não houve segundo revisor independente além do `python-reviewer`.

### Dogfooding (FASE 8)

Medido no `docs/DONE.md` de `0fad1f0`, antes deste registro: `naturalize.py docs/DONE.md --diff-only` troca os dois `### O que saiu` por `### Resultado` e desnegrita os 23 rótulos; nada mais. Cópia no scratchpad, idempotente (rodar de novo dá exit 3), 599 linhas antes e depois.

| | Antes | Depois |
|---|---|---|
| Score | 0,4401 | 0,1521 |
| Delta | | **−0,288** (meta ≤ −0,25: atingida) |
| Efetividade | | `medium`, confiança high |
| Eliminados | | `bold_lead_in` (23), `template_heading` (2) |
| Restante | | `comparison_table_symmetry` (medium), aceito pela decisão acima |
| Introduzidos | | nenhum |

O delta bate com a conta do plano (−0,288). Continua n = 1 e vem de formatação (negrito e dois títulos), não de o texto ter ficado melhor. Medido de novo no arquivo final, já com esta seção: o mesmo 0,4401 → 0,1521. Na primeira versão da seção o score subiu para 0,4857, porque uma tabela de hashes minha (colunas de tamanho parecido) deu ao `comparison_table_symmetry` uma segunda ocorrência e a severidade foi de `medium` para `high`. Troquei a tabela por lista, que é o que a recomendação do próprio detector manda.

Relatório do repo inteiro (`detect_ai_patterns.py . --format md`, fora do git): 172 → 175 arquivos, e só mudaram de score os dois fixtures de `naturalize/template_heading/` que o R12-01 editou. Os três arquivos novos pontuam 0,0. **A expectativa do prompt de que o score do repo cairia por causa da correção da cerca não se confirmou**: nenhum documento daqui tem cerca aninhada nem linha com info string dentro de cerca, então a correção é de um caso que o repo não exercita.

### Skills invocadas (para cruzar com o transcript)

As 9 não-condicionais foram chamadas numa única mensagem, com os nomes qualificados (`ponytail:ponytail-review`, `ponytail:ponytail-debt`), e nenhuma falhou.

| # | Skill | Fase | Propósito |
|---|---|---|---|
| 1 | `ponytail:ponytail-review` | 0 | Gate. Régua de over-engineering; o `build_corpus.py` perdeu um helper e um dicionário antes de ser testado |
| 2 | `ponytail:ponytail-debt` | 0 | Gate. `grep` de `ponytail:` no repo inteiro: 0 marcadores |
| 3 | `python-pro` | 0 | Gate. Python 3.12+, tipagem completa, `mypy --strict` |
| 4 | `py-test-quality` | 0 | Gate. Cobertura de ramo 100%, 100% e 99%; sem mutation testing no Windows |
| 5 | `py-security` | 0 | Gate. `bandit` limpo; guard de caminho e leitura de corpus tratados na revisão |
| 6 | `py-code-health` | 0 | Gate. `vulture` e `pylint` duplicate-code limpos; a regra de cerca deixou de ser duplicada |
| 7 | `py-typing` | 0 | Gate. `mypy --strict` nos 10 arquivos de `tools/` |
| 8 | `caveman` | 0 | Gate. Estilo da prosa no chat |
| 9 | `python-test` | 0 | Gate. Baseline 1790 / 1720 / 70 e leitura das execuções, com e sem `formats` |
| 10 | `python-review` (condicional) | 3 | Gatilho: parse de cerca e regex no gap #2, depois I/O no corpus. Invocada com o código existente, antes dos commits. A revisão do diff acumulado foi delegada ao `python-reviewer` |
| 11 | `code-reviewer` (condicional) | 3 | Mesmo gatilho, invocada junto. Revisão descrita acima |
| — | `python-type` (condicional) | — | **Não invocado.** O `mypy --strict` passou sem erro |

### Riscos residuais

- A CI não foi confirmada. Falta um push (que eu não fiz) e, para ver Windows e macOS no 3.12, `fail-fast: false` no workflow mostraria todas as combinações de uma vez. Sugestão minha, não aplicada: o prompt não esperava edição em `.github/workflows/`.
- `skills/naturalize/SKILL.md`, linha 106, ainda diz que um título como `O que saiu` é contado pelo detector mas não é trocado. Agora é trocado. A restrição desta rodada proíbe tocar essa skill, então a linha ficou desatualizada; é uma frase para a próxima rodada, se você autorizar. O README (linha 968) e o fixture foram corrigidos.
- O corpus está vazio; sem ele não há número de separabilidade, e a decisão sobre ML segue aberta.
- Cerca sem fechamento mascara o texto até o fim sem avisar (achado 4), e `_FENCE` aceita cerca com recuo de 4 ou mais (achado 10). Os dois vêm da R10.
- Medição de efetividade com n = 1, e o delta mede formatação. Limiares e pesos do detector seguem sem calibração; o `build_corpus.py` existe para isso.
- Procurei outro teste que troque métodos de `Path` ou `os.path` por dublês, como o que quebrou no 3.12. Só achei um (`isjunction`, que existe no 3.12 e não depende de `st_mode`). Código novo que faça isso é sensível ao 3.12.
- O mutation testing continua indisponível no Windows (R6).

## Estado do sistema — 2026-09-30 (R11)

| ID | Item | Estado | Commit |
|---|---|---|---|
| R11-01 | Motor `tools/stylometry/naturalize.py` | ✅ fechado | fa620eb, 93f5736, d9d7a75 |
| R11-02 | CLI `tools/naturalize.py` | ✅ fechado | e7201d8, 59c088a, 370cb6f |
| R11-03 | Fixtures de naturalização (11 casos, pares `before.md`/`after.md`) | ✅ fechado | fa620eb |
| R11-04 | Skill `naturalize` | ✅ fechado | 28b5547, ed7f908 |
| R11-05 | Skill `detect-ai-patterns` | ✅ fechado | 568f57c |
| R11-06 | Seção nova em `clean-user-facing-text` (8 linhas, nenhuma removida) | ✅ fechado | 8ef6adb |
| R11-07 | Sync para `~/.claude/skills/` (`install_skill.py --skill`) | ✅ fechado para as duas skills novas. `clean-user-facing-text` **não** sincronizada, ver B3 | d5893ae |
| R11-08 | README, seção "Detecção estilométrica" | ✅ fechado | 6218cc9, ed7f908 |
| R11-09 | Dogfooding | ✅ fechado, **delta −0,1728** (medium) | este commit |

| Medida | Valor final (HEAD `d9d7a75`) |
|---|---|
| Testes, `.venv` sem o grupo `formats` | 1790 coletados / 1720 passed / 70 skipped, 0 falhas, exit 0 |
| Testes, venv com `formats` | 1790 coletados / 1782 passed / 8 skipped, 0 falhas, exit 0 |
| Os 1262 de antes | Os 1192 passed e os 70 skips seguem iguais sem `formats`; os 1254 e os 8 com `formats`. +528 testes, 0 regressões |
| Cobertura de ramo (`--cov=tools`) | Motor `tools/stylometry/naturalize.py` 100% (301 instruções, 96 ramos). CLI `tools/naturalize.py` 99%, só falta o `sys.exit(main())`, que roda no teste de subprocess |
| `ruff check .` e `ruff format --check .` | limpos (126 arquivos) |
| `mypy --strict` em `tools/` | limpo, 9 arquivos |
| `pip-audit` (`.venv`) | 0 vulnerabilidades |
| Bandit | `-r tools/ install_skill.py` e as duas skills novas: 0 achados. `-r service/scripts/` segue em Low 32 / Medium 1 / High 0 |
| `vulture` (60%) e `pylint` duplicate-code | 0 achados nos dois módulos novos; duplicação 10/10 em `tools/` |
| `service/` e `skills/remove-ai-marks/` | Sem diff desde o baseline `fb03416` |

**R11 pronta para uso: sim.** `tools/naturalize.py` roda de qualquer diretório com a stdlib (não precisa do grupo `formats`), reduz o score de forma medida e é idempotente. As duas skills estão em `~/.claude/skills/` e aparecem na lista desta sessão. Nenhum `git push` foi feito.

Riscos residuais que não bloqueiam uso:
- Medição n = 1. O delta de −0,1728 é sobre o `docs/DONE.md` e vem de tirar o negrito de 23 rótulos (formatação), não de o texto ter ficado melhor. O score mede o que o detector conta. Limiares, pesos e o divisor 8 seguem sem calibração contra corpus.
- Links de outros arquivos para um título renomeado não são vistos. A ferramenta protege os links do próprio arquivo. Por isso o fluxo das skills manda revisar o `--diff-only` antes de gravar.
- Limites conhecidos do motor, todos documentados na skill: código indentado dentro de item de lista, aspas curly aninhadas (só o par de dentro é protegido), `segunda — sexta` (sem número) vira lista, linha de hard-wrap não abre frase, e nome de ferramenta em minúscula fora de uma lista curta é capitalizado.
- Primeiro run da CI pendente. Nada foi pushado. Os testes novos passam no Windows (hard link incluído); a CI vai exercitá-los no Linux e no macOS pela primeira vez.
- `clean-user-facing-text` instalada em `~/.claude/skills/` está defasada do repo: os `scripts/` são de 22/08 e 07/09, os do repo de 16 e 21/09. A seção nova da R11-06 só existe na cópia do repo até alguém reinstalar. Reinstalar troca os scripts da skill instalada, por isso não foi feito sem pedido. Com `--force` o instalador cria uma pasta `.backup.*` com outro `SKILL.md` dentro de `skills/`; tire-a dali.
- Três observações sobre código da R10, não corrigidas por estarem fora do escopo: o `text._mask` fecha uma cerca com qualquer trecho do mesmo caractere (o que o motor corrigiu para si), então o detector conta como prosa o conteúdo de uma cerca dentro de outra; e `detect_ai_patterns.py --output` e `measure_skill_effectiveness.py --output` comparam caminhos resolvidos, então um hard link para a entrada passa pela guarda.
- O mutation testing não roda no Windows (R6). A qualidade dos testes foi medida por cobertura de ramo, 150 documentos aleatórios com semente fixa e 23 entradas hostis.

## Rodada R11 — 2026-09-30 — Naturalização e integração via skill

| Medida | Início (`fb03416`) | Fim (`d9d7a75`) |
|---|---|---|
| Testes coletados / passed / skipped, sem `formats` | 1262 / 1192 / 70 | 1790 / 1720 / 70 |
| Testes coletados / passed / skipped, com `formats` | 1262 / 1254 / 8 | 1790 / 1782 / 8 |
| `ruff check .` e `ruff format --check .` | limpos (117 arquivos) | limpos (126 arquivos) |
| `pip-audit` (`.venv`) | 0 | 0 |

O plano foi escrito antes de qualquer edição, em 66449e8 (`docs/TODO.md`). As diferenças entre ele e o que saiu estão em "Ajustes durante a execução" (K1 a K9), no mesmo arquivo, e os oito achados da FASE 0 que mudaram premissas do prompt estão em B1 a B8.

### O que saiu

- `tools/stylometry/naturalize.py`: o motor. Oito reescritas determinísticas (`bold_lead_in`, `em_dash_density`, `template_heading`, `emoji_heading`, `hedge_double`, `delve_family`, `worth_noting`, `fast_paced_world`), cada uma só enquanto o detector da R10 ainda dispara o sinal dela. Antes de transformar, tudo o que pode carregar um fato vira marcador opaco e volta idêntico: linhas de cerca, código indentado, front matter, tabela, citação em bloco, título setext; e, dentro da linha, código inline, destino de link, URL, e-mail, caminho, citação entre aspas, tag HTML, hash e identificador. O laço repete até o texto parar de mudar, então rodar sobre a própria saída não muda nada.
- `tools/naturalize.py`: o CLI. `--format text|md|json`, `--diff-only`, `--in-place` (escrita atômica que mantém BOM, fim de linha e permissão), `--signals`, `--preserve`, `--output`. Exit 0 mudou algo, 1 caminho ou escrita, 2 formato não suportado, 3 nada aplicável. O score é o de `detect_ai_patterns.py`, e um teste confirma que o `delta` bate com o do `measure_skill_effectiveness.py` para o mesmo par.
- `skills/naturalize/` e `skills/detect-ai-patterns/`: o corpo de cada uma é também a documentação (o que a ferramenta faz, onde está o CLI, fluxo, como ler o resultado, limites, um exemplo real). Achar o repositório: `WATERMARKS_REPO` e, sem ela, `E:\Projetos\Scripts\watermarks-remover`. Conferido de `C:\` no PowerShell e no Git Bash, com a variável certa, errada e ausente.
- `install_skill.py --skill NOME` (padrão inalterado), para o R11-07 não depender de cópia manual.
- Testes: `test_naturalize.py`, `test_naturalize_review.py`, `naturalize_support.py`, `test_naturalize_cli.py`, `test_naturalize_skills.py` e dois casos novos em `test_lightweight_skill.py`. Este último grupo mantém a prosa das skills honesta: toda flag citada existe, toda flag que existe é citada, a tabela de transformações lista exatamente as do motor, o catálogo lista os 37 sinais, nenhum arquivo de skill é engolido pelo `.gitignore`, e o instalador entrega as duas.

### Registros pedidos

- `.gitignore` deny-by-default mordeu de novo, pela quarta vez no total (B1): `skills/naturalize/SKILL.md` nasceria ignorado. Liberado em 28b5547, e `test_git_does_not_ignore_a_skill_folder` passa a cobrir todo arquivo sob `skills/`.
- Três desvios do prompt, declarados antes de editar (B6, B7, B8): o CLI aceita só `.md` e `.txt` (não há como reescrever HTML, DOCX ou PDF de volta de forma determinística), `hedge_double` mantém um hedge em vez de tirar os dois (tirar os dois transformaria dúvida em certeza), e o título de modelo é trocado no idioma do título.
- Extensão do arquivo de dogfooding (K1): o nome `docs/DONE.md.naturalized` do prompt não é lido pelo detector nem pelo compare (`nenhum arquivo pareado`, exit 2), e `docs/` não é ignorado pelo git. A cópia ficou no scratchpad, como `DONE.naturalized.md`.
- Um achado de eficácia no dogfooding: o rótulo `**RED no código antigo...:**` não era reescrito porque `RED` vira marcador de identificador e a checagem de maiúscula olhava o marcador. Corrigido em d9d7a75 (23 de 23 rótulos do `DONE.md` agora).
- Entrada hostil: o primeiro teste de desempenho achou um backtrack quadrático em `[A-Z]{2,}[A-Z0-9]*` (195 s para 100 kB) antes de qualquer commit. A auditoria seguinte achou mais dois do mesmo tipo (`.*?` antes de `[ \t]*$` num título, e `re.sub` de pontuação final).

### Revisões

`python-review` sobre o motor e o CLI (agente `python-reviewer`): **5 ALTA e 6 MÉDIA**, mais duas recomendações. Cada achado foi reproduzido antes de corrigir, e cada correção tem teste de regressão.

| # | Achado | Estado |
|---|---|---|
| 1 ALTA | `difflib` quadrático, rodando em todos os modos (arquivo de 55 mil linhas: cerca de 9 minutos) | Corrigido, 59c088a: diff por número de linha, só quando é mostrado |
| 2 ALTA | Máscara de aspas curly e guillemet quadrática (20 mil aberturas: 3 s) | Corrigido, 93f5736 |
| 3 ALTA | `KeyError` com `ı` e `ſ` sob `IGNORECASE` (traceback, exit 1) | Corrigido: padrões de `delve`/`dive` só ASCII |
| 4 ALTA | Cerca fechada por qualquer trecho do mesmo caractere vazava o bloco | Corrigido: o fechamento exige o tamanho do abridor e nenhuma info string |
| 5 ALTA | Intervalo numérico com espaço (`10 — 20`, `9h — 17h`) virava lista | Corrigido. `segunda — sexta`, sem número, continua virando lista, documentado |
| 6 MÉDIA | Literal entre aspas simples alterado | Corrigido, com apóstrofo tratado à parte |
| 7 MÉDIA | `--output` com hard link para a entrada trocava o original pelo relatório | Corrigido: `os.path.samefile` e escrita atômica |
| 8 MÉDIA | Âncora incompleta: título repetido, link com percent-encoding, colisão de slug | Corrigido |
| 9 MÉDIA | Citação e código quebrados em duas linhas, e tabela sem pipe inicial, reescritos | Corrigido |
| 10 MÉDIA | Capitalização e sentido: `pip` virava `Pip`, início de linha de hard-wrap virava início de frase, `to dive into the lake` virava figura | Corrigido |
| 11 MÉDIA | Sequência de controle e bidi (U+202E) chegando ao terminal | Corrigido. Com saída para um pipe os bytes seguem exatos, de propósito |
| Rec. | `fsync` antes do `os.replace`; arquivo alterado entre a leitura e a escrita | Feitas |

`code-reviewer` sobre o diff acumulado (`fb03416..370cb6f`): feita por mim pelo roteiro da skill (intenção, estrutura, detalhes, testes, veredito), junto do agente acima. Zero crítico. Três achados menores, corrigidos: `main()` com 52 linhas (passou para 40, 370cb6f), `test_naturalize.py` com 833 linhas (separado em três arquivos) e a ajuda do `--force` do instalador ainda falando só de Cursor. Não houve um segundo revisor independente além do `python-reviewer`. Veredito: Approve.

### Dogfooding (FASE 4)

Fluxo do prompt contra o próprio `docs/DONE.md`, medido no HEAD `d9d7a75` e antes desta seção:

1. `detect_ai_patterns.py docs/DONE.md --format md`: score 0,39, com `bold_lead_in` 23 (high), `comparison_table_symmetry` (medium) e `template_heading` 1 (low).
2. `naturalize.py docs/DONE.md --diff-only --format md`: 23 edições, todas `bold_lead_in`. Li o diff inteiro: só desnegrito de rótulos. Hashes, pins, código inline e o negrito que não abre item (`**nenhuma via make ainda.**`) ficaram como estavam.
3. Cópia fora do git (`DONE.naturalized.md`, no scratchpad).
4. `measure_skill_effectiveness.py`:

| | Antes | Depois |
|---|---|---|
| Score | 0,3920 | 0,2192 |
| Delta | | **−0,1728** |
| Efetividade | | **medium** (confiança high) |
| Eliminado | | `bold_lead_in` |
| Restantes | | `comparison_table_symmetry` (medium), `template_heading` (low) |
| Introduzido | | nenhum |

Critério de sucesso do prompt (delta ≤ −0,10): **atingido**. A cópia é idempotente (rodar de novo dá exit 3). Antes e depois são idênticos em 572 trechos de código inline, 84 hashes, 938 números e 9 URLs, e as duas têm 470 linhas.

Por que não foi mais longe: `comparison_table_symmetry` é tabela, que o motor protege de propósito (é dado), e `### O que saiu` é um título que o detector conta mas o dicionário de templates não conhece (trocá-lo seria inventar um título). O travessão não entrou na conta: nenhum sinal de travessão dispara neste arquivo, então o gate da reescrita de travessão ficou fechado.

Para comparar com a R10: a medição do `/clean-user-facing-text` foi de +0,0132 (piorou) sobre uma versão anterior do arquivo (score 0,3531). Esta é sobre a versão atual (0,3920), então os dois deltas não são do mesmo arquivo. Com a mesma ferramenta no `docs/TODO.md` o delta foi −0,2399 (medium), e no `README.md` −0,0519 (low). Todos são n = 1 e mudam só a formatação.

### Skills invocadas (para cruzar com o transcript)

As 9 não-condicionais foram chamadas numa única mensagem, com os nomes qualificados (`ponytail:ponytail-review`, `ponytail:ponytail-debt`), e nenhuma falhou.

| # | Skill | Fase | Propósito |
|---|---|---|---|
| 1 | `ponytail:ponytail-review` | 0 | Gate. Régua de over-engineering; passada própria sobre o diff: nada a cortar além do já simplificado |
| 2 | `ponytail:ponytail-debt` | 0 | Gate. `grep` de `ponytail:` em `tools/`, `tests/`, `install_skill.py` e `skills/`: 0 marcadores |
| 3 | `python-pro` | 0 | Gate. Python 3.12+ (alvo `py312`), tipagem completa, `mypy --strict` |
| 4 | `py-test-quality` | 0 | Gate. Cobertura de ramo: 100% e 99%. Sem mutation testing no Windows, então teste aleatório e entrada hostil |
| 5 | `py-security` | 0 | Gate. Entrada hostil, `bandit`, `pip-audit`; foi o que achou os backtracks quadráticos |
| 6 | `py-code-health` | 0 | Gate. `vulture` e `pylint` duplicate-code nos módulos novos |
| 7 | `py-typing` | 0 | Gate. `mypy --strict` nos 9 arquivos de `tools/` |
| 8 | `caveman` | 0 | Gate. Estilo de saída no chat |
| 9 | `python-test` | 0 | Gate. Baseline 1262 / 1192 / 70 e leitura das execuções, com e sem `formats` |
| 10 | `python-review` (condicional) | 2 | Gatilho: CLI que lê e escreve arquivo. Invocada assim que o CLI existiu, antes dos commits. Delegou ao `python-reviewer` |
| 11 | `code-reviewer` (condicional) | 2 | Mesmo gatilho, invocada junto, sem esperar a retomada (na R10 foi omitida até lá). Revisão do diff acumulado, descrita acima |
| — | `python-type` (condicional) | — | **Não invocado.** O `mypy --strict` passou sem erro, então não havia erro de tipo para resolver |

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
