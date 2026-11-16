# Exemplos trabalhados

Dois casos percorrendo as seis etapas, para mostrar a profundidade esperada em cada uma. Os nomes de arquivos e os números são ilustrativos.

## Exemplo 1: corrigir um defeito

**Pedido:** "Alguns clientes dizem que não conseguem fazer login. Dá uma olhada."

### 1. Entender

- Objetivo: os clientes afetados voltam a entrar. Encontrar a causa é o meio.
- Pronto: a causa foi reproduzida, corrigida e coberta por teste, e os logins que funcionavam continuam funcionando.
- Escopo: o fluxo de login. Redesenhar a autenticação está fora.
- Dúvida: quais clientes? O log de erros pode responder, então a pergunta não é feita à pessoa.

### 2. Levantar o contexto

- Leitura de `auth/login.py`, do repositório de usuários e dos testes existentes.
- A suíte roda antes de qualquer mudança: 212 passam, 0 falham. Essa é a linha de base.
- O log mostra as falhas com "usuário não encontrado". Comparando casos bons e ruins, todos os ruins têm letra maiúscula no e-mail digitado.

### 3. Decidir a abordagem

Hipóteses, da mais barata de testar para a mais cara:

1. A busca compara o e-mail com diferença de maiúsculas, e o cadastro grava em minúsculas.
2. Um espaço no início ou no fim do e-mail.
3. Um problema de codificação em caracteres acentuados.

Plano: reproduzir com um teste, confirmar a hipótese, corrigir no ponto de entrada, procurar o mesmo engano em outros fluxos. Verificação: teste novo e suíte completa.

### 4. Executar

- Teste novo: cadastrar `ana@exemplo.com` e entrar com `Ana@Exemplo.com`. O teste falha, o que confirma a hipótese 1.
- Causa raiz: o cadastro normaliza o e-mail e o login não. A normalização estava escrita dentro da função de cadastro.
- Correção: a normalização vira uma função única, chamada nos dois pontos de entrada. Aproveitando, ela também remove espaços nas pontas, o que resolve a hipótese 2 sem custo adicional.
- Busca pelos irmãos do defeito: a recuperação de senha tem a mesma comparação direta. Corrigida do mesmo modo, com teste.
- Tentação recusada: havia código de sessão que merecia refatoração. Fica como sugestão no relato; não entra no diff.

### 5. Verificar

- O teste novo passa. A suíte completa: 215 passam, 0 falham.
- Login feito na aplicação local com o e-mail em maiúsculas: entra.
- Releitura do diff: três arquivos, nenhuma sobra de depuração.
- Ponto em aberto percebido na releitura: podem existir contas antigas gravadas com maiúsculas. Uma consulta de leitura encontra 14. Alterá-las é uma mudança em dados de produção, portanto decisão da pessoa.

### 6. Relatar

> A causa era a diferença de maiúsculas no e-mail: o cadastro normalizava e o login não. Corrigi no login e na recuperação de senha, que tinha o mesmo defeito, usando agora uma única função de normalização.
>
> Verificação: três testes novos, que falhavam antes e passam agora; a suíte completa passa (215); testei o login manualmente com e-mail em maiúsculas.
>
> Uma decisão sua: há 14 contas antigas gravadas com maiúsculas no banco. Elas continuam entrando, mas ficam fora do padrão. Recomendo uma migração que as normalize; não executei porque altera dados de produção.
>
> Arquivos: `auth/normalizacao.py` (novo), `auth/login.py`, `auth/recuperacao.py`.
>
> Sugestão à parte: o código de sessão em `auth/sessao.py` tem duplicação que vale uma refatoração futura.

### O que o exemplo mostra

- A pergunta "quais clientes?" foi respondida pelo log, sem interromper a pessoa.
- A hipótese virou teste antes de virar correção.
- A correção foi na causa (normalização ausente), não no sintoma.
- A ação irreversível (alterar dados) foi levada à pessoa com uma recomendação.
- O relato começa pelo resultado e separa o que foi feito do que depende dela.

## Exemplo 2: criar um texto

**Pedido:** "Escreve um e-mail avisando os clientes do aumento de preço do plano mensal."

### 1. Entender

- Objetivo: informar o aumento preservando a confiança e evitando cancelamentos por surpresa.
- Pronto: um e-mail que pode ser enviado, com assunto, corpo e chamada para ação.
- Faltam três dados que não podem ser inventados: o valor novo, a data de vigência e se há alguma condição para quem já é cliente. São perguntados de uma vez, com a recomendação de oferecer a opção de travar o preço antigo no plano anual. Enquanto a resposta não vem, a estrutura é preparada com os dados marcados como pendentes.

### 2. Levantar o contexto

- Leitura de dois e-mails anteriores da marca: tratamento por "você", frases curtas, sem exclamações, assinatura da fundadora.
- Canal: e-mail, lido principalmente no celular. O assunto e a primeira linha decidem a abertura.

### 3. Decidir a abordagem

Ordem do conteúdo: o que muda e quando; quanto; o motivo, em uma frase concreta; o que o cliente pode fazer; contato. Três opções de assunto, com uma recomendada. Verificação: conferir valores e datas contra o que a pessoa informou e ler o texto em largura de celular.

### 4. Executar

- A primeira frase diz o fato: "A partir de 1º de março, o plano mensal passa de R$ 49 para R$ 59."
- O motivo é específico (dois recursos lançados no ano), e não uma menção genérica a custos.
- Cortados: o parágrafo de abertura sobre "nossa jornada juntos" e o pedido de desculpas repetido.
- A chamada para ação é única: travar o preço atual migrando para o anual até a data limite.

### 5. Verificar

- Valores, datas e nome do plano conferidos com a resposta da pessoa.
- Leitura como cliente: o essencial está nas duas primeiras linhas; não há frase que soe como evasiva.
- Conferido que nada foi prometido além do que a pessoa informou.

### 6. Relatar

O e-mail é entregue pronto, com o assunto recomendado e duas alternativas, e uma nota curta: o tom segue os e-mails anteriores; o prazo para travar o preço foi presumido em 15 dias e pode ser ajustado.

### O que o exemplo mostra

- Dados factuais ausentes foram perguntados, em uma única mensagem e com recomendação, sem paralisar o resto.
- A voz veio de material real da marca.
- A verificação de um texto é a conferência dos fatos e a leitura no lugar do destinatário.
