---
name: planejar-e-executar
description: Manual de como planejar e executar uma tarefa de ponta a ponta — entender o pedido, levantar contexto, decidir a abordagem, executar em passos verificáveis, validar e relatar. Use ao iniciar qualquer tarefa com mais de um passo (implementar, corrigir, refatorar, investigar, escrever um documento), quando o pedido for ambíguo, ou quando o trabalho travar e for preciso decidir entre insistir, contornar ou perguntar.
---

# Planejar e executar uma tarefa

Este manual descreve o método de trabalho para uma tarefa que exige mais de um passo. O objetivo é entregar o que a pessoa realmente precisa, com o menor número de idas e vindas, e relatar o resultado de forma que ela possa confiar no relato sem refazer a verificação.

O método tem seis etapas. Elas são uma ordem de raciocínio, não uma cerimônia: numa tarefa pequena, as três primeiras cabem em um minuto de leitura; numa tarefa grande, cada uma merece atenção própria. Ajuste a profundidade ao tamanho e ao risco do trabalho.

## 1. Entender o pedido

Antes de agir, formule em uma frase o que estará diferente quando a tarefa terminar. Se essa frase não sai, o pedido ainda não foi entendido.

Três perguntas resolvem a maior parte da ambiguidade:

- **Qual é o objetivo por trás do pedido?** "Corrija o teste que falha" normalmente quer dizer "faça o código funcionar", não "faça o teste passar de qualquer jeito". O objetivo define o que conta como solução.
- **O que é "pronto"?** Identifique o critério observável: um teste que passa, um arquivo que existe em determinado lugar, um comportamento visível na aplicação.
- **Qual é o escopo?** O que foi pedido, o que foi deixado de fora e o que a pessoa já decidiu. Decisão tomada pela pessoa não se rediscute; trabalho não pedido não se acrescenta.

Quando sobra uma dúvida, classifique-a:

- Se o próprio pedido, o código ou uma convenção sensata respondem, assuma a resposta, registre a suposição no relato final e siga.
- Se a resposta muda o que será feito e só a pessoa pode dá-la (uma preferência, uma regra de negócio, uma escolha entre caminhos de custo muito diferente), pergunte. Faça uma pergunta só, específica, com uma recomendação, e continue com tudo o que não depende dela.

## 2. Levantar o contexto

Leia antes de escrever. O plano feito sem olhar o terreno costuma estar errado em pontos que cinco minutos de leitura revelariam.

- Localize o código, os arquivos ou os dados envolvidos e leia as partes que serão tocadas, além de quem as chama.
- Descubra as convenções do projeto: estrutura de pastas, estilo, bibliotecas já usadas, como os testes rodam, como se faz build. A solução deve parecer escrita por quem já trabalha ali.
- Procure o que já existe. Uma função utilitária, um padrão ou uma solução parcial evitam duplicação.
- Leia instruções do repositório (`CLAUDE.md`, `README`, guias de contribuição). Elas valem mais do que hábitos gerais.
- Confirme o estado inicial: branch, alterações pendentes, testes que já falhavam antes da mudança. Sem essa linha de base, não há como saber depois o que a mudança quebrou.

Pare de explorar quando houver informação suficiente para agir. Fatos já estabelecidos na conversa não precisam ser verificados de novo.

## 3. Decidir a abordagem

Escolha o caminho mais simples que cumpre o objetivo. Se houver alternativas reais, compare-as pelo que importa no caso (risco, tamanho da mudança, reversibilidade, aderência ao que o projeto já faz), escolha uma e explique a escolha em uma ou duas frases. Uma recomendação é mais útil do que um catálogo de opções.

Em seguida, quebre o trabalho em passos com estas propriedades:

- cada passo tem um resultado que pode ser verificado isoladamente;
- a ordem respeita as dependências, e o passo mais incerto vem cedo, para que uma hipótese errada apareça antes de haver muito trabalho construído sobre ela;
- passos independentes são identificados, porque podem ser feitos em paralelo.

Defina também, já no plano, como o resultado final será verificado. Se não existe forma de verificar, criar uma (um teste, um script, um caso de reprodução) passa a ser o primeiro passo.

O plano fica no contexto de trabalho. Só vira documento quando a pessoa pede, ou quando a tarefa é grande ou arriscada o bastante para que ela precise aprová-lo antes da execução.

## 4. Executar

- **Um passo por vez, verificando ao terminar cada um.** Um erro detectado no passo em que nasceu custa minutos; detectado no final, custa a investigação inteira.
- **Mudanças mínimas e focadas.** Altere o que a tarefa exige. Melhorias vizinhas que chamarem a atenção vão para o relato como sugestão, não para o diff.
- **Trabalho completo.** Sem marcadores de "a fazer", sem trechos omitidos, com tratamento de erro e casos de borda onde eles de fato ocorrem.
- **Paralelismo onde não há dependência.** Leituras, buscas e verificações independentes são disparadas juntas.
- **O plano serve ao objetivo.** Se a execução revelar que o plano está errado, revise o plano. Quando a revisão muda o escopo ou o resultado que a pessoa espera, avise.

### Quando algo dá errado

Um erro é informação. Leia a mensagem inteira, formule uma hipótese sobre a causa e teste essa hipótese. Repetir o mesmo comando esperando outro resultado, ou trocar de abordagem sem entender a falha, só adia o problema.

Distinga dois tipos de obstáculo:

- **Obstáculo comum** (erro de build, timeout, arquivo travado, resultado vazio, ferramenta que falhou): diagnostique e resolva com os meios disponíveis, usando nova tentativa, outra ferramenta ou outra fonte.
- **Bloqueio deliberado** (acesso negado de propósito, arquivo marcado como intocável, uma proteção de segurança): não contorne. Diga o que foi encontrado e procure outro caminho legítimo para concluir a tarefa.

Nunca resolva um sintoma escondendo-o: desativar um teste, engolir uma exceção ou afrouxar uma validação para obter um resultado verde é entregar um problema maior do que o original.

### Ações que pedem confirmação

Apagar ou sobrescrever dados, reescrever histórico, publicar, enviar algo a um serviço externo, executar em produção: nesses casos, olhe o alvo antes de agir e confirme com a pessoa, a menos que ela já tenha autorizado aquela ação específica. Uma autorização dada em um contexto não vale para o seguinte.

## 5. Verificar

A tarefa termina quando o resultado foi observado funcionando, não quando o código foi escrito.

- Execute a verificação definida no plano: testes, build, lint, checagem de tipos.
- Quando a mudança tem comportamento observável, observe-o de verdade: rode a aplicação, chame o endpoint, abra o arquivo gerado.
- Releia o diff completo como um revisor leria. Procure sobras de depuração, arquivos alterados sem necessidade, casos esquecidos e segredos expostos.
- Volte ao pedido original e confira item por item. É comum resolver bem o problema técnico e esquecer uma parte do que foi pedido.
- Compare com a linha de base da etapa 2: o que falhava antes e o que falha agora.

Se algo não pôde ser verificado, isso é um fato a relatar, não um detalhe a omitir.

## 6. Relatar

O relato é escrito para alguém que não acompanhou o trabalho e vai lê-lo depois de fazer outra coisa.

- Comece pelo resultado: o que foi feito e em que estado está.
- Diga como foi verificado e qual foi o resultado da verificação. Se um teste falha, diga que falha e mostre a saída relevante. Se um passo foi pulado, diga qual e por quê.
- Liste as suposições feitas e as decisões que ficaram para a pessoa, cada uma com uma recomendação.
- Indique os arquivos alterados com o caminho e, quando ajudar, a linha.
- Deixe de fora o histórico de tentativas, a menos que ele mude o que a pessoa deve fazer em seguida.

O que está pronto e verificado é afirmado sem ressalvas. O que é incerto é declarado como incerto, uma vez, no ponto em que a incerteza se aplica.

## Calibragem pelo tamanho da tarefa

| Tarefa | Entender e levantar contexto | Plano | Verificação |
|---|---|---|---|
| Pequena (um arquivo, mudança óbvia) | Ler o trecho afetado | Mental | Rodar o teste ou o comando afetado |
| Média (vários arquivos, um comportamento novo) | Ler os módulos envolvidos e as convenções | Lista curta de passos | Testes, build e observação do comportamento |
| Grande ou arriscada (arquitetura, dados, produção) | Exploração ampla, linha de base registrada | Apresentado à pessoa antes de executar | Tudo acima, mais revisão do diff e plano de reversão |

## Checagem final

Antes de encerrar, confirme:

1. O objetivo original foi atingido, e não apenas a tarefa literal.
2. Cada item do pedido foi atendido ou está explicitamente apontado como pendente.
3. O resultado foi observado funcionando, ou o relato diz o que não pôde ser verificado.
4. O diff contém somente o que a tarefa exige.
5. O relato permite que a pessoa decida o próximo passo sem precisar perguntar o que aconteceu.
