# Desenvolvimento de software

Leia este arquivo ao escrever, alterar, refatorar ou revisar código.

## Antes de escrever

- Leia o código que será tocado e quem o chama. Uma função só é entendida junto com seus usos.
- Identifique as convenções do projeto: estrutura de pastas, nomes, estilo de erro, bibliotecas, forma dos testes, comandos de build, lint e teste.
- Procure algo que já resolva o problema, no projeto ou nas dependências existentes.
- Rode os testes antes de mudar qualquer coisa, para conhecer a linha de base.
- Defina como a mudança será verificada.

## Desenho

- **A solução simples vem primeiro.** Abstração, configuração e generalização entram quando há um segundo uso concreto. Código escrito para um futuro hipotético precisa ser mantido mesmo que esse futuro não chegue.
- **O código novo segue o código existente.** Consistência com o projeto vale mais do que a preferência de quem escreve. Se a convenção do projeto for ruim, proponha a mudança à parte; não crie um segundo estilo no meio do primeiro.
- **Cada unidade tem uma responsabilidade.** Uma função que precisa de "e" na descrição provavelmente são duas.
- **Dependências externas ficam atrás de uma interface** quando o projeto já trabalha assim ou quando o teste exige substituí-las. Banco, rede, relógio e sistema de arquivos são os casos típicos.
- **Estado mutável compartilhado é a origem mais comum de defeitos difíceis.** Prefira dados imutáveis e funções que recebem o que precisam e devolvem o resultado.
- **Torne o estado inválido difícil de representar.** Tipos, enumerações e validação na construção evitam checagens espalhadas.

## Implementação

- **Valide nas fronteiras.** Toda entrada que vem de fora (usuário, rede, arquivo, variável de ambiente, resposta de outro serviço) é validada onde entra no sistema. Dentro do sistema, confie nos tipos e nos invariantes já garantidos, sem repetir a mesma checagem em cada camada.
- **Trate os casos de borda que de fato ocorrem:** vazio, nulo, zero, negativo, valor no limite, duplicado, muito grande, caracteres especiais, entrada concorrente.
- **Nomes dizem o que a coisa é.** Um bom nome dispensa o comentário. O comentário fica para o porquê: a restrição, a decisão não óbvia, a armadilha.
- **Trabalho completo.** Sem marcadores de "a fazer", sem funções vazias, sem trecho omitido.
- **Use tipagem forte** onde a linguagem oferece. O verificador de tipos encontra erros sem que nenhum teste precise ser escrito.
- **Remova o que deixou de ser usado.** Código morto, flags obsoletas, imports e arquivos temporários saem no mesmo trabalho que os tornou desnecessários.

## Tratamento de erros

- Capture uma exceção para recuperar, traduzir ou acrescentar contexto. Em qualquer outro caso, deixe-a subir.
- Uma falha silenciosa é pior do que uma falha visível. Nunca capture para ignorar.
- A mensagem de erro diz o que falhou, com qual valor e, quando possível, o que fazer. Ela não expõe segredos nem detalhes internos a quem está de fora.
- Chamadas externas têm timeout. Novas tentativas usam espera crescente e um limite, e só se aplicam a operações que podem ser repetidas sem efeito duplicado.
- Recursos abertos (arquivo, conexão, trava) são liberados também no caminho de erro.

## Segurança

Trate toda entrada como hostil até ser validada.

- **Injeção:** consultas parametrizadas ou ORM; nunca montar SQL, comando de shell ou caminho de arquivo concatenando entrada.
- **Saída:** escape conforme o contexto de destino (HTML, atributo, URL, JSON).
- **Autenticação e autorização:** verifique em cada acesso que o usuário pode ver ou alterar aquele recurso específico, e não apenas que está autenticado.
- **Segredos:** fora do código, do repositório e dos logs. Vêm de variável de ambiente ou de um serviço de segredos.
- **Requisições feitas pelo servidor a URLs fornecidas pelo usuário:** valide o destino e bloqueie endereços internos e de metadados de nuvem.
- **Arquivos enviados:** valide tipo, tamanho e nome; não confie na extensão; não sirva do mesmo domínio sem cuidado.
- **Menor privilégio:** o processo, o usuário do banco e o token têm apenas as permissões necessárias.
- **Dependências:** versões fixadas, origem conhecida, atualização quando há correção de segurança.
- **Criptografia:** use as bibliotecas consagradas; não implemente algoritmo próprio.

Ao terminar um trecho que lida com dados, rede ou autenticação, releia-o como um atacante leria: o que acontece se eu mandar algo inesperado aqui?

## Testes

- Teste o comportamento que o código promete, de modo que uma refatoração interna não quebre os testes.
- Cubra o caminho normal, os casos de borda e os caminhos de erro.
- Cada teste verifica uma coisa e tem um nome que diz qual.
- Um teste deve falhar pelo motivo certo. Ao escrever um teste para um defeito, veja-o falhar antes de corrigir.
- Testes não dependem de ordem, de relógio real nem de rede, a menos que sejam testes de integração declarados.
- Nunca altere um teste só para que ele passe. Se o teste está errado, diga por quê; se o código está errado, corrija o código.

## Desempenho e observabilidade

- Meça antes de otimizar e depois de otimizar. Sem medição não há como afirmar ganho.
- Evite os custos conhecidos: consulta dentro de laço, carregar tudo para usar uma parte, trabalho repetido que poderia ser guardado.
- Registre eventos relevantes em formato estruturado, com um identificador que permita seguir uma requisição de ponta a ponta. Não registre segredos nem dados pessoais desnecessários.
- Serviços expõem verificação de saúde e as métricas básicas: tráfego, erros e latência.

## Dependências

Uma dependência é um custo permanente. Antes de adicionar:

- o projeto ou a biblioteca padrão já resolve?
- ela é mantida, tem licença compatível e tamanho razoável?
- a versão foi fixada no manifesto e o arquivo de lock foi atualizado?

Não troque uma biblioteca que o projeto já usa por outra preferida sem que isso tenha sido pedido.

## Controle de versão

- Cada commit faz uma coisa. Refatoração e mudança de comportamento ficam em commits separados.
- A mensagem diz o que mudou e por quê. O porquê é a parte que o diff não mostra.
- Confira o que está sendo commitado: sem arquivo gerado, sem segredo, sem sobra de depuração.
- Não reescreva histórico de branch compartilhada nem force push sem autorização explícita.
- Commit, push e pull request são ações da pessoa: faça quando ela pedir e na branch que ela indicar.

## Mudanças em dados e em produção

- Toda migração tem caminho de volta, ou o relato diz claramente que não tem.
- Mudanças de esquema são compatíveis com a versão anterior do código durante a transição.
- Antes de uma operação destrutiva, olhe o alvo: conte as linhas, liste os arquivos, confirme o ambiente.
- Operações em produção pedem confirmação da pessoa, mesmo quando parecem pequenas.

## Revisão do próprio trabalho

Antes de declarar pronto, leia o diff inteiro como um revisor:

- cada linha alterada é necessária para a tarefa?
- algum caso de borda ficou sem tratamento?
- algum nome, comentário ou documento ficou desatualizado pela mudança?
- os testes, o build, o lint e a checagem de tipos passam?
- o comportamento foi observado funcionando, e não apenas inferido?

## Revisão do trabalho de outra pessoa

- Comece pela correção: o código faz o que deveria, em todos os casos?
- Cada apontamento traz o cenário concreto de falha: com esta entrada, acontece isto.
- Separe o que impede a aprovação do que é sugestão ou preferência.
- Verifique o apontamento antes de fazê-lo. Um falso alarme custa a confiança nos próximos.
- Critique o código, com respeito por quem escreveu.

## Documentação

Atualize a documentação que a mudança tornou falsa. Documente o que alguém precisa para usar e operar: como instalar, configurar, executar, testar e o que fazer quando falha. Não descreva o que o código já diz por si.
