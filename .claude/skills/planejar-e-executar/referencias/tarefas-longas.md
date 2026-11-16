# Tarefas longas e continuidade

Leia este arquivo quando o trabalho tem muitos passos, dura horas, atravessa mais de uma sessão ou roda sem a pessoa por perto.

Em uma tarefa longa, o risco é perder o fio: esquecer uma decisão, refazer uma exploração, afastar-se do pedido original ou perder trabalho não salvo. As práticas abaixo mantêm o estado fora da memória.

## No início

- **Divida em marcos.** Cada marco tem um resultado verificável e deixa o sistema em estado funcional. Assim, uma interrupção em qualquer ponto preserva algo utilizável.
- **Registre a linha de base:** branch, último commit, testes que passam e que falham.
- **Ordene pelo risco.** O marco que pode invalidar o plano vem primeiro.
- **Combine o que precisa de aprovação.** Se algum marco envolve ação irreversível ou externa, obtenha a decisão da pessoa antes, para não parar no meio.
- **Use uma lista de tarefas** quando houver mais passos do que cabe acompanhar de cabeça. Mantenha-a atualizada: em andamento ao começar, concluída ao verificar.

## Durante o trabalho

- **Commits como pontos de retorno.** Um commit a cada passo verificado permite voltar a um estado bom com um comando. Trabalho não commitado some com o ambiente.
- **Em ambiente efêmero, envie ao remoto** nos marcos, quando a pessoa autorizou o push. Um container reciclado leva junto tudo o que era local.
- **Registre as decisões e os motivos.** O código mostra o que foi feito; o motivo de ter descartado a alternativa só existe se for escrito. O lugar natural é a mensagem do commit ou a descrição do pull request.
- **Registre as descobertas que custaram caro:** o comando que funciona, a armadilha do ambiente, a premissa que se mostrou falsa.
- **Verifique a cada marco, não só no final.** Rode os testes antes de seguir. Um defeito de três marcos atrás é difícil de localizar.
- **Volte ao pedido original periodicamente.** Em tarefas longas o escopo deriva: confira se o que está sendo feito ainda serve ao objetivo.
- **Processos demorados rodam em segundo plano**, com o trabalho independente seguindo em paralelo. Não fique parado esperando nem consulte em laço curto.

### Onde guardar o estado

Prefira os registros que já existem: histórico de commits, lista de tarefas, descrição do pull request, issue. Um arquivo de notas no repositório se justifica quando a pessoa pede ou quando o trabalho vai atravessar sessões e nenhum desses registros comporta o que precisa ser lembrado. Notas temporárias ficam fora do repositório ou são removidas ao final.

Uma nota de estado útil responde a quatro perguntas:

1. O que está pronto e verificado?
2. O que está em andamento e em que ponto parou?
3. O que falta, em ordem?
4. O que foi decidido ou descoberto que quem retomar precisa saber?

## Comunicação com a pessoa

- Atualizações curtas nos marcos: o que ficou pronto e o que vem a seguir.
- Uma mensagem deve ser entendida por quem volta depois de fazer outra coisa, sem depender das anteriores.
- Uma dúvida que não bloqueia é registrada e levada ao relato; o trabalho continua no que não depende dela.
- Uma mudança de escopo ou uma descoberta que altera o resultado esperado é comunicada assim que aparece.

## Retomada

Ao voltar a um trabalho interrompido, reconstrua o estado a partir dos registros, e não da lembrança:

1. Leia as notas, a lista de tarefas e as últimas mensagens da conversa.
2. Veja o histórico e o estado do repositório: branch, commits recentes, alterações pendentes.
3. Rode os testes para confirmar que o estado é o que as notas dizem.
4. Confira se o ambiente mudou: dependências, serviços, acessos.
5. Releia o pedido original e continue do primeiro item pendente.

Uma ressalva antiga encontrada nas notas ("não mexer em X", "isto não funciona") merece ser reavaliada: o motivo ainda vale? Se a ressalva protege contra uma ação arriscada ou irreversível, ela permanece até que a pessoa a libere.

## Quando o plano muda no meio

- Se um marco mostrou que a abordagem está errada, pare de construir sobre ela. Custo já investido não é motivo para continuar.
- Reavalie os marcos restantes à luz do que foi aprendido.
- Se a mudança afeta o que a pessoa vai receber, o prazo ou o custo, avise antes de prosseguir.

## Encerramento

- Rode a verificação completa sobre o conjunto, e não apenas sobre o último marco.
- Remova arquivos temporários, instrumentação e processos em segundo plano.
- Confira que tudo o que deve permanecer está commitado e, quando autorizado, enviado.
- O relato final cobre a tarefa inteira: o que foi entregue, como foi verificado, o que ficou pendente e as decisões que cabem à pessoa.
