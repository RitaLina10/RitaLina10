# Resolução de problemas e depuração

Leia este arquivo quando algo falha e a causa não é evidente: um erro, um teste vermelho, um comportamento diferente do esperado, uma regressão, uma lentidão.

A depuração é uma busca. O método abaixo reduz o espaço de busca a cada passo, em vez de depender de um palpite certeiro.

## Antes de começar

Reúna os fatos, com as palavras exatas:

- a mensagem de erro completa e o stack trace inteiro;
- o que era esperado e o que aconteceu;
- desde quando acontece e o que mudou por volta desse momento (deploy, dependência, configuração, dados);
- com que frequência ocorre: sempre, às vezes, só para alguns usuários, só em um ambiente;
- o que já foi tentado.

Uma descrição vaga ("não funciona") precisa virar uma descrição observável antes de qualquer investigação.

## O método

1. **Reproduza.** Obtenha o comando, a entrada ou a sequência de passos que provoca a falha de modo confiável. Um defeito que não se reproduz não pode ser declarado corrigido. Se a reprodução for impossível no momento, instrumente o sistema para capturar a próxima ocorrência e diga que a causa ainda é hipótese.
2. **Reduza.** Corte o caso até o menor exemplo que ainda falha: menos dados, menos passos, menos código. Cada elemento removido é um suspeito a menos, e o caso mínimo costuma tornar a causa visível.
3. **Isole por bisseção.** Entre uma versão que funciona e uma que falha, ou entre a entrada e a saída de um fluxo, divida ao meio e verifique o ponto central. Repita na metade que contém o defeito. Isso encontra a origem em poucos passos, mesmo sem nenhuma intuição sobre a causa.
4. **Formule hipóteses e teste a mais barata primeiro.** Escreva duas ou três explicações. Para cada uma, diga o que se observaria se fosse verdadeira. Comece pelo teste que elimina mais possibilidades com menos esforço.
5. **Mude uma variável por vez.** Duas mudanças simultâneas impedem saber qual delas produziu o efeito. Se uma tentativa não resolveu, desfaça-a antes da próxima.
6. **Chegue à causa raiz.** Pergunte por que a falha ocorre, e por que essa causa ocorre, até encontrar algo cuja correção impede o defeito de voltar. Corrigir só o ponto onde o erro aparece deixa a causa ativa.
7. **Prove a correção.** Escreva o teste que falhava antes e passa depois. Rode também a reprodução original. Sem isso, a correção é uma opinião.
8. **Procure os irmãos do defeito.** O mesmo engano costuma estar repetido em código parecido. Uma busca pelo padrão encontra os outros casos enquanto o contexto está fresco.

## Técnicas

- **Leia o stack trace inteiro.** A primeira linha diz o que falhou; os quadros do próprio projeto dizem onde; a exceção encadeada ("caused by") costuma conter a causa real.
- **Compare o caso bom com o caso ruim.** Duas requisições, dois ambientes, dois usuários, duas versões: liste as diferenças. A causa está em uma delas.
- **`git bisect`** quando existe um commit conhecido em que funcionava. Ele automatiza a bisseção no histórico.
- **Instrumentação pontual.** Um log ou uma asserção no ponto certo vale mais do que ler o código tentando simular a execução de cabeça. Remova a instrumentação ao terminar.
- **Verifique o valor real.** Imprima o dado, o tipo e o tamanho. Muitos defeitos são um valor diferente do presumido: `None` em vez de lista vazia, texto em vez de número, espaço no fim, codificação diferente.
- **Explique o problema por escrito.** Descrever passo a passo o que o código deveria fazer costuma revelar o passo em que a descrição e o código divergem.

## Onde olhar, por tipo de sintoma

| Sintoma | Suspeitos mais comuns |
|---|---|
| Funciona em um ambiente e falha em outro | Configuração e variáveis de ambiente, versões de dependências e do runtime, dados diferentes, permissões, rede e DNS, fuso horário e localidade, caminhos de arquivo |
| Falha intermitente | Concorrência e condição de corrida, dependência da ordem de execução, estado compartilhado entre testes, relógio e datas, serviço externo instável, limite de recursos, cache |
| Começou a falhar sem mudança no código | Dependência atualizada sem versão fixada, certificado ou credencial expirados, dados novos em formato inesperado, cota ou limite atingido, mudança em serviço externo |
| Regressão após uma mudança | O diff da mudança, quem chama o código alterado, comportamento implícito do qual outro código dependia |
| Lentidão | Consulta repetida em laço (N+1), falta de índice, carga de dados maior que o necessário, chamada externa sem timeout, trabalho síncrono que poderia ser adiado |
| Resultado errado sem erro | Caso de borda (vazio, zero, negativo, limite), arredondamento, fuso horário, ordenação presumida, exceção engolida em algum ponto |
| Erro só com certos dados | Caracteres especiais e codificação, campos nulos, tamanho, duplicatas, formato de data e número |

Para lentidão, meça antes de mexer. Otimizar sem medição costuma melhorar um trecho que não era o gargalo.

## Premissas a conferir quando a investigação empaca

Boa parte dos defeitos "impossíveis" vem de uma premissa falsa que ninguém verificou:

- O código que está rodando é o que foi editado? (build antigo, cache, outro processo, outra branch, container não reconstruído)
- A configuração lida é a que se imagina? (arquivo errado, variável sobrescrita, valor padrão)
- O dado tem o formato presumido?
- O teste testa o que o nome dele diz?
- A falha é mesmo neste componente, ou ele apenas a revela?
- A documentação consultada corresponde à versão instalada?

## Quando parar e relatar

Insista enquanto cada passo reduz o espaço de busca. Pare e relate quando as hipóteses plausíveis se esgotaram, quando o próximo passo exige um acesso ou uma informação que só a pessoa tem, ou quando a correção implica uma decisão dela (mudar um comportamento, aceitar um custo).

O relato de uma investigação inconclusiva contém: o que foi reproduzido, o que foi descartado e com qual evidência, as hipóteses que restam e o próximo teste recomendado.

## Depois da correção

- Remova logs, asserções temporárias e arquivos de reprodução que não devem ficar.
- Rode a suíte inteira, não só o teste novo: a correção pode ter quebrado outra coisa.
- Diga no relato a causa raiz em uma frase, a correção e como foi provada.
- Nunca feche um defeito escondendo o sintoma. Desativar o teste, capturar e ignorar a exceção ou afrouxar a validação cria um problema maior do que o original.
