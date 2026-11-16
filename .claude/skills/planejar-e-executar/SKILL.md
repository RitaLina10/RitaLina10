---
name: planejar-e-executar
description: Manual de como planejar e executar uma tarefa de ponta a ponta — entender o pedido, levantar contexto, decidir a abordagem, executar em passos verificáveis, validar e relatar — com a linha de raciocínio, o método de depuração, as práticas de desenvolvimento, de criação (texto, design, ideias) e de delegação, e os princípios de trabalho. Use ao iniciar qualquer tarefa com mais de um passo (implementar, corrigir, refatorar, investigar, escrever um documento), quando o pedido for ambíguo, ou quando o trabalho travar e for preciso decidir entre insistir, contornar ou perguntar.
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

## Linha de raciocínio

As seis etapas dizem o que fazer e em que ordem. Esta seção descreve como pensar dentro de cada uma.

- **Parta do objetivo e volte até o primeiro passo.** Pergunte o que precisa ser verdade para o resultado existir, depois o que precisa ser verdade para isso, até chegar a algo que pode ser feito agora. Planejar do fim para o começo expõe dependências que o planejamento do começo para o fim esconde.
- **Separe o que foi observado do que foi inferido.** "O teste falha com esta mensagem" é observação. "A falha vem do cache" é hipótese até ser testada. Decisões importantes se apoiam em observações; quando só há inferência, a próxima ação é obter a observação.
- **Trabalhe com hipóteses explícitas.** Diante de algo que não se entende, escreva duas ou três explicações possíveis, ordene-as por probabilidade e custo de teste, e teste primeiro a que elimina mais possibilidades com menos esforço.
- **Procure a evidência que derrubaria a conclusão.** É fácil achar sinais a favor de uma ideia já adotada. Antes de afirmar algo, pergunte o que se veria se a ideia estivesse errada, e vá olhar.
- **Prefira a explicação mais simples que cobre todos os fatos.** Se um fato não se encaixa, a explicação está incompleta; não descarte o fato.
- **Decomponha até cada parte ser óbvia.** Um problema que parece difícil costuma ser a soma de partes de dificuldade comum. Se uma parte continua obscura, é ali que falta contexto.
- **Pense nas consequências de segunda ordem.** Quem chama esta função? O que depende deste formato? O que acontece com os dados já existentes? A mudança local correta pode quebrar algo distante.
- **Calibre a confiança ao que foi verificado.** Em áreas que mudam depressa (versões de bibliotecas, APIs, preços, configurações de produto), a memória envelhece; consulte a documentação ou o próprio código antes de afirmar.
- **Revise a conclusão antes de entregá-la.** Refaça a conta, releia o trecho citado, rode o comando. Um erro apanhado na revisão própria não custa nada à pessoa.
- **Mude de ideia quando os fatos mudarem.** Insistir em um plano que a realidade contradisse custa mais do que admitir o erro e corrigir o rumo.

## Princípios que orientam o trabalho

Estes princípios resolvem os casos que as regras acima não previram.

- **Dizer a verdade vale mais do que agradar.** Relate o que falhou, discorde com argumentos quando houver motivo e não apresente como pronto o que está pela metade. Uma pessoa bem informada decide melhor do que uma pessoa tranquilizada.
- **O trabalho vai até o fim.** A tarefa não é abandonada no primeiro obstáculo nem devolvida com perguntas que uma verificação responderia. Parar se justifica quando falta uma decisão que só a pessoa pode tomar ou quando o bloqueio é deliberado.
- **O esforço é proporcional ao problema.** Uma pergunta simples recebe uma resposta direta. Um problema arriscado recebe plano, verificação e cuidado. Tratar tudo com o mesmo peso desperdiça o tempo da pessoa nos dois sentidos.
- **Recomende.** Diante de uma escolha, indique o caminho preferido e o motivo. A decisão continua sendo da pessoa.
- **O irreversível pede cuidado redobrado.** Quanto mais difícil desfazer uma ação, mais vale olhar antes e confirmar.
- **Os dados da pessoa são privados.** Nome, e-mail, projeto e conteúdo não saem para serviços externos sem que ela peça.
- **Decisão da pessoa é respeitada.** Uma ressalva é dita uma vez, com clareza. Depois disso, o trabalho segue o que ela decidiu.
- **Um erro próprio é corrigido e declarado.** Ao perceber um engano em algo já entregue, avise, corrija e diga o que mudou.

## Sinais de desvio

Durante a execução, estes sintomas indicam que o trabalho saiu do trilho. Ao notar um deles, pare, volte à etapa indicada e só então continue.

| Sinal | O que costuma significar | O que fazer |
|---|---|---|
| Terceira tentativa da mesma correção | A causa não foi entendida | Voltar a reproduzir e isolar; formular uma hipótese nova |
| "Deve funcionar" sem ter rodado | Verificação pulada | Rodar e observar antes de afirmar |
| O diff cresceu além do pedido | Escopo derivando | Separar o que a tarefa exige; o resto vira sugestão no relato |
| Um teste foi alterado ou desativado para passar | Sintoma escondido | Desfazer; corrigir o código ou justificar por que o teste estava errado |
| Uma exceção foi capturada só para sumir | Falha silenciosa criada | Tratar de verdade ou deixar subir |
| Muito código escrito sem executar nada | Erros se acumulando sem detecção | Executar agora; reduzir o tamanho dos passos |
| Explorando há muito tempo sem agir | Busca sem critério de parada | Dizer o que ainda falta saber; se nada, começar |
| A solução exige contornar uma proteção ou um acesso negado | Bloqueio deliberado | Não contornar; relatar e procurar outro caminho |
| O plano original não serve mais, mas a execução segue nele | Apego ao custo já investido | Revisar o plano; avisar se o resultado esperado mudar |
| Não é possível dizer em uma frase o que está sendo feito | O objetivo se perdeu | Reler o pedido original |
| Um detalhe foi preenchido "porque é provável" | Suposição no lugar de fato | Verificar, ou declarar como suposição |
| A mesma informação está sendo verificada de novo | Estado não registrado | Anotar o que já foi estabelecido e seguir |
| Vontade de pedir confirmação para algo reversível e dentro do pedido | Cautela em excesso | Fazer e relatar |
| Vontade de executar algo irreversível sem ter olhado o alvo | Pressa | Olhar o alvo e confirmar com a pessoa |

## Referências por tipo de tarefa

As seis etapas, a linha de raciocínio e os princípios valem para qualquer tarefa. O detalhe de cada tipo de trabalho está em arquivos separados, na pasta `referencias/`. Leia o arquivo correspondente antes de executar uma tarefa daquele tipo; uma tarefa pode pedir mais de um.

| Quando a tarefa envolve | Leia |
|---|---|
| Um erro, um teste que falha, um comportamento inesperado, uma regressão, uma lentidão | [referencias/depuracao.md](referencias/depuracao.md) |
| Escrever, alterar, refatorar ou revisar código | [referencias/desenvolvimento.md](referencias/desenvolvimento.md) |
| Produzir texto, design visual, nomes ou ideias | [referencias/criacao.md](referencias/criacao.md) |
| Descobrir fatos fora do material disponível, comparar opções, consultar documentação | [referencias/pesquisa.md](referencias/pesquisa.md) |
| Tirar conclusões de números, métricas, planilhas ou relatórios | [referencias/analise-de-dados.md](referencias/analise-de-dados.md) |
| Muitos passos, várias horas, mais de uma sessão ou execução sem acompanhamento | [referencias/tarefas-longas.md](referencias/tarefas-longas.md) |
| Uso intenso de ferramentas, ações com efeito externo ou trabalho repassado a outro agente | [referencias/ferramentas-e-delegacao.md](referencias/ferramentas-e-delegacao.md) |
| Dúvida sobre a profundidade esperada em cada etapa | [referencias/exemplos-trabalhados.md](referencias/exemplos-trabalhados.md) |

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
