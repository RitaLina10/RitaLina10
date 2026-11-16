# Análise de dados

Leia este arquivo quando a tarefa envolve tirar conclusões de números: desempenho de campanhas, vendas, métricas de produto, relatórios, planilhas, resultados de teste A/B.

O risco próprio desta tarefa é produzir um número com aparência de exato e conteúdo errado. O método abaixo existe para impedir isso.

## Começar pela decisão

- Qual decisão esta análise vai apoiar? Aumentar o orçamento, pausar um anúncio, mudar um preço.
- Qual resultado levaria a cada decisão? Definir isso antes de olhar os dados evita ajustar a interpretação ao que apareceu.
- Qual é a métrica que representa o objetivo de verdade? Cliques não são vendas; vendas não são lucro.

## Conhecer os dados antes de analisar

- **Origem:** de qual sistema vieram, por qual consulta, em que momento.
- **Granularidade:** o que é uma linha (um pedido, um item, um dia, um usuário).
- **Período e fuso horário**, e se o período final está completo.
- **Definição de cada métrica:** como a fonte calcula conversão, receita, usuário ativo. Fontes diferentes usam o mesmo nome para contas diferentes.
- **Moeda e unidade.**
- **Qualidade:** quantas linhas, quantos nulos, duplicatas, valores impossíveis, lacunas no tempo.

Olhe uma amostra das linhas brutas antes de agregar. A agregação esconde os problemas que a amostra mostra.

## Checagens de sanidade

- O total bate com um número conhecido de outra fonte (o painel da plataforma, o financeiro)?
- A soma das partes é igual ao todo?
- A contagem de linhas mudou depois de uma junção? Um aumento indica duplicação; uma queda indica perda.
- A ordem de grandeza faz sentido? Uma taxa de conversão de 40% ou um custo por clique de R$ 0,001 pedem investigação antes de comemoração.

Um resultado bom demais quase sempre é um erro: filtro errado, duplicata, período incompleto, métrica mal definida.

## Analisar

- **Denominador sempre à vista.** Uma taxa só significa algo com a base: 50% de 4 e 50% de 4.000 são coisas diferentes.
- **Compare períodos equivalentes.** Mesmos dias da semana, mesma sazonalidade, mesma duração. Um mês parcial contra um mês cheio não é comparação.
- **Segmente.** Uma média geral pode esconder segmentos que vão em direções opostas; a tendência do todo pode se inverter dentro de cada parte.
- **Média e mediana.** Com poucos valores extremos, a média engana; mostre a mediana ou a distribuição.
- **Tamanho da amostra.** Com poucos eventos, a diferença pode ser acaso. Diga quando o volume é insuficiente para concluir.
- **Correlação e causa.** Dois números que andam juntos podem ter uma causa comum ou nenhuma relação. Afirmar causa exige um experimento ou a eliminação das explicações alternativas.
- **Atribuição e atraso.** Conversões chegam depois do clique; os dias mais recentes ainda vão mudar. Janelas e modelos de atribuição diferentes dão números diferentes.
- **Efeitos externos.** Promoção, feriado, mudança de preço, falha de rastreamento, alteração no produto.

## Nunca inventar

- Apresente apenas valores que vieram da fonte ou de um cálculo mostrado.
- Uma estimativa é rotulada como estimativa, com a premissa usada.
- Um dado ausente é declarado ausente. Não preencha lacuna com valor plausível.
- Se a fonte não pôde ser acessada, diga isso; não substitua por exemplo fictício, a menos que a pessoa peça.

## Apresentar

- A conclusão e a recomendação vêm antes da tabela.
- Todo número traz unidade, período e fonte.
- Arredonde de acordo com a precisão real. Seis casas decimais sugerem uma exatidão que não existe.
- Mostre a comparação que dá sentido ao número: contra o período anterior, a meta ou o segmento vizinho.
- Escolha o gráfico pela pergunta: linha para evolução no tempo, barra para comparação entre categorias, dispersão para relação entre duas medidas.
- Separe o que os dados mostram, o que é interpretação e o que é recomendação.
- Declare os limites: o que os dados não cobrem, o que pode estar distorcido, o que seria preciso para ter certeza.

## Reprodutibilidade

Guarde a consulta, o filtro ou o script que gerou cada número. Quem ler deve conseguir refazer a conta e chegar ao mesmo valor. Ao repetir uma análise periódica, use as mesmas definições da vez anterior ou diga o que mudou.
