# Corpus pessoal: procedimento

Limiares, pesos e o divisor do score do detector (`tools/detect_ai_patterns.py`) nunca foram
calibrados contra texto real. Antes de decidir se um modelo aprendido vale o esforço, falta um
número: quanto o detector atual separa o que você escreve do que um modelo escreve. O
`tools/build_corpus.py` cria o corpus, confere e calcula esse número.

O corpus é privado. Fica fora do repositório (pasta temporária por padrão), nada dele é versionado,
e o script recusa criar a pasta dentro do repo.

## Criar

```powershell
py tools\build_corpus.py init
```

Cria `%TEMP%\corpus\` com as pastas `human\` e `ai\` e um `README.md` curto. A pasta temporária pode
ser limpa pelo Windows (Sensor de Armazenamento, limpeza de disco). Para um corpus que você quer
manter, escolha outro lugar:

```powershell
py tools\build_corpus.py init --dir D:\meu-corpus
```

O mesmo `--dir` vale para `check` e `compare`. Rodar `init` de novo não apaga nem sobrescreve nada.
Em Linux e macOS a pasta temporária padrão é compartilhada entre usuários da máquina: lá, use um
`--dir` dentro da sua pasta pessoal.

## Preencher

| Pasta | O que vai nela |
|---|---|
| `human\` | Textos que você escreveu sem ajuda de modelo: e-mails, notas, relatórios, posts |
| `ai\` | Textos que um modelo escreveu para você, colados sem edição |

- No mínimo 10 arquivos em cada pasta. Com 30 ou mais por pasta o resultado fica estável; abaixo
  disso o `compare` avisa.
- Formatos: `.md`, `.txt` e `.html`. `.docx` e `.pdf` só entram com o grupo `formats` instalado. Código
  não conta: o corpus é de prosa. Arquivo de outra extensão (`.rst`, `.markdown`) também não é lido, e
  o `check` diz quantos foram ignorados, para o n que você vê não surpreender.
- Mesmo assunto e tamanho parecido nos dois lados. Se um lado só tem textos curtos e técnicos, o
  detector mede o tema, não o estilo.
- Nada de texto misto. Um rascunho de modelo que você reescreveu não é de nenhum dos dois lados.
- Subpastas são lidas. O nome do arquivo não importa.

## Conferir

```powershell
py tools\build_corpus.py check
```

Mostra quantos arquivos cada lado tem, a faixa de scores (mínimo, mediana, máximo), quantos foram
pulados (formato aceito, mas ilegível) e quantos ignorados (outra extensão ou código). Sai com 1 se
alguma pasta tem menos de 10 arquivos, e diz quantos faltam. Para ver por que um arquivo foi pulado,
rode o detector na pasta:

```powershell
py tools\detect_ai_patterns.py %TEMP%\corpus\human --format md
```

## Medir

```powershell
py tools\build_corpus.py compare
```

A saída tem este formato. O exemplo abaixo usa os dois textos de teste do repositório (um deles em 10
fatias de tamanhos diferentes), só para mostrar o formato. Separa bem porque são dois textos
escritos para isso, e não diz nada sobre o seu.

```text
corpus: <pasta>
human: 10 arquivos (mín 0.000, mediana 0.000, máx 0.000)
ai: 10 arquivos (mín 0.116, mediana 0.660, máx 0.760)
médias: human 0.000 (dp 0.000) · ai 0.541 (dp 0.230)
Cohen's d: +3.333 (ai menos human, desvio agrupado)
IC 95% de d: [+1.98, +4.69]
AUC: 1.00 (chance de um ai pontuar acima de um human; 0.50 = acaso)
recomendação: determinístico suficiente
o detector atual separa os dois lados.
aviso: com menos de 30 arquivos por pasta o intervalo é largo.
```

Se todos os arquivos de cada pasta tiverem o mesmo score (cópias do mesmo texto, por exemplo), o
`compare` recusa com "corpus degenerado" e sai com 1: sem variância não há d nem AUC que valham.

## Ler o resultado

Cohen's d é a diferença entre as médias dos dois lados, medida em desvios padrão agrupados. Um d de
1,0 quer dizer que o texto de IA médio pontua um desvio acima do humano médio. A AUC é a chance de
um texto sorteado de `ai\` pontuar acima de um sorteado de `human\`; 0,5 é acaso e 1,0 é separação
completa.

O rótulo não vem só do d. Com poucos arquivos o d varia muito de uma amostra para outra (com 10 por
pasta o intervalo de 95% tem cerca de ±0,9), então o `compare` imprime o intervalo e só dá um dos
rótulos abaixo quando o intervalo inteiro cai na mesma faixa. Se o intervalo cruza um limiar, o
rótulo é `inconclusivo`, onde quer que o d caia. Com 10 por pasta, `determinístico suficiente` pede
um d de uns 1,9 para cima, e `ML justificado` só aparece com d negativo (o intervalo inteiro tem de
ficar abaixo de 0,5). Para provar que o detector não separa, o corpus precisa ser maior: com 100 por
pasta o d pode chegar a 0,2.

| Cohen's d | Recomendação impressa | Leitura |
|---|---|---|
| 0,8 ou mais | `determinístico suficiente` | O detector atual separa os lados. O corpus não justifica um modelo |
| de 0,5 até menos de 0,8 | `inconclusivo` | Separa, mas com sobreposição. Recalibrar antes de pensar em modelo |
| menos de 0,5, inclusive negativo | `ML justificado` | O detector atual quase não separa. Vale investigar |

Os limiares são os de Cohen para efeito grande e médio, e estão em `tools/build_corpus.py`
(`D_SUFFICIENT`, `D_MARGINAL`). O mínimo de 10 por pasta e o aviso abaixo de 30 também.

O rótulo vem só do d. A AUC é uma conferência que o código não usa: se ela discordar muito do d (d
alto com AUC abaixo de 0,7, ou o contrário), desconfie do rótulo e olhe a faixa de scores do
`check`, porque scores limitados entre 0 e 1, com muitos zeros, não são normais e o d supõe algo
próximo disso. Um d negativo quase sempre é pasta trocada.

## Decidir a partir do número

`determinístico suficiente`: nada a fazer. Registre o d, a AUC, o n de cada pasta, a data e o commit
no `docs/DONE.md`, e siga com o detector.

`inconclusivo`: o que mexe no score está em `tools/stylometry/__init__.py` (`STRENGTH`, `WEIGHT`,
`SATURATION`) e nos limiares de cada sinal em `tools/stylometry/text.py`. Mude um de cada vez e rode
o `compare` de novo. Calibrar e medir no mesmo corpus superestima o ganho: ajuste com metade dos
arquivos e meça com a outra metade.

`ML justificado` quer dizer que o detector atual não separa, não que um modelo vai separar. Antes de
qualquer treino, descarte as causas baratas: pastas trocadas (d negativo), assuntos ou tamanhos
diferentes entre os lados, menos de 30 arquivos por pasta. Um corpus pessoal de dezenas de arquivos
é pequeno demais para treinar um modelo que generalize; o próximo passo é juntar mais texto e medir
de novo, não treinar.

## Limites

- Os dois rótulos são os que você pôs nas pastas. Se o modelo foi instruído a escrever de forma
  natural, o corpus mede isso, não "texto de IA" em geral.
- n pequeno dá d e AUC instáveis. O piso de 10 é para o cálculo não quebrar, não uma garantia.
- O score é indicativo, não veredito, e o uso é pessoal: não use o resultado para acusar terceiros.
