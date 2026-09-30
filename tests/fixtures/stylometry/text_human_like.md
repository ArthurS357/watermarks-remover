# limpa.py

## Instalação e uso

O limpa.py tira caracteres invisíveis de arquivos de texto. Não depende de nada além da biblioteca padrão.

Copiei um trecho da web e a busca do editor não achava uma palavra que estava bem na minha frente. Levei um tempo até perceber que havia um espaço de largura zero no meio dela, colado pelo site de origem, e que só um script resolveria sem eu caçar caractere por caractere. Foi aí que escrevi isto. Hoje uso quase todo dia.

Você roda o comando com o nome do arquivo. Ele localiza espaços de largura zero, marcas de direção e caracteres de controle soltos, grava uma cópia limpa ao lado do original e imprime quantos de cada tipo saíram.

## Limites

Uma exceção importa: sequências de emoji usam o joiner (U+200D) para juntar símbolos. Por isso o script mantém esse caractere quando ele está dentro de uma sequência válida. Fora dela, sai.

O resto do texto fica como estava. Ordem das palavras, acentos e quebras de linha não mudam. O original só é tocado se você pedir a sobrescrita, e nesse caso sobra uma cópia de reserva. Num arquivo comum a execução leva poucos milissegundos. Nunca precisei de mais que isso.

| Critério | Sem o script | Com o script |
|---|---|---|
| Busca no editor | falha em algumas palavras | acha tudo |
| Trabalho | caçar caracteres a olho | rodar um comando |
