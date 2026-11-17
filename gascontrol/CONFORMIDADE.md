# Conformidade regulatória — o que o software resolve e o que depende da empresa

> Este documento **não é parecer jurídico nem regulatório**. Ele mapeia funções do sistema para
> exigências típicas de boas práticas. A interpretação final cabe ao responsável técnico (RT) e,
> se necessário, a uma consultoria regulatória. Confirme sempre o texto oficial vigente no DOU.

## Normas de referência

- **RDC ANVISA nº 887/2024**: boas práticas de distribuição, armazenagem, transporte e dispensação de gases medicinais. Exige um sistema de gestão da qualidade capaz de documentar e manter a rastreabilidade, e de executar recolhimento (recall).
- **RDC ANVISA nº 870/2024**: notificação e registro de gases medicinais. Os prazos foram alterados por normas posteriores. Confira a versão vigente.
- **ABNT NBR 12176**: identificação de cilindros por cores. É usada no checklist pré-envase.
- **Teste hidrostático periódico**: a periodicidade é configurável (`HYDRO_TEST_VALIDITY_YEARS`). Confirme com a norma aplicável ao seu tipo de cilindro.

## Matriz: requisito → como o PB Gas Control atende

| Requisito de boas práticas | O que o sistema faz | Onde |
|---|---|---|
| Rastreabilidade individual do recipiente | Série única + QR por cilindro. Histórico completo de cadastro, envase, entrega, coleta, manutenção e condenação | Cilindros → Rastrear |
| Rastreabilidade de lote até o cliente | O envase vincula o lote. A entrega herda o lote. Relatório de recall por lote | Lotes → Recall / Dossiê CSV |
| Liberação de lote pelo responsável | Lote nasce em QUARENTENA. Só o GESTOR libera, com **assinatura eletrônica** (reconfirma a senha, registra o significado do ato e grava um hash da assinatura) | Lotes → Aprovar |
| Impedir uso de produto não liberado | Bloqueio automático: medicinal sem lote aprovado e válido não é entregue | Regra de domínio |
| Inspeção do recipiente antes do envase | **Checklist pré-envase obrigatório** para medicinal (visual, válvula, rótulo, cor NBR 12176, purga). O resultado fica gravado na movimentação | Operação → Envase |
| Recipiente com ensaio vencido | Envase bloqueado. Alerta antecipado no painel | Painel |
| Integridade dos registros (ALCOA+) | Movimentações e cadastros são encadeados por SHA-256. A verificação detecta edição direta no banco. Nenhuma tela edita ou apaga movimentações | Auditoria |
| Atribuição (quem fez) | Usuário individual por pessoa e perfil mínimo. A sessão é revalidada a cada requisição | Usuários |
| Contemporaneidade (quando fez) | Grava a hora do servidor **e** a hora do campo (operação offline), com GPS e NF-e/romaneio | Movimentações |
| Trilha de alterações de cadastro | Cada criação ou alteração de usuário, cliente, lote, gás e cilindro gera evento com antes e depois | Auditoria |
| Disponibilidade para inspeção | Exportação CSV do dossiê de lote e do histórico do cilindro (protegida contra injeção de fórmula) | Lotes / Cilindros |
| Reclamações, desvios e CAPA | Registro com prazo por gravidade, investigação com causa raiz, ações com responsável/prazo/evidência, verificação de eficácia e encerramento assinado | Qualidade |
| Recolhimento (recall) | Bloqueio do lote a partir da ocorrência (assinado). Envase e entrega param na hora. O dossiê CSV lista os clientes atingidos. A volta exige nova liberação do RT | Qualidade + Lotes |
| Preservação dos registros | Backup automático a cada 6 h, com verificação de integridade e hash (`backup` no docker-compose) | Operação de TI |

## O que **não** se resolve só com software (responsabilidade da empresa)

1. **Licenciamento**: AFE/AE na ANVISA, licença sanitária local, CBPDA quando aplicável, e o RT habilitado no conselho profissional.
2. **POPs escritos** que reflitam o uso do sistema: recebimento, envase, inspeção, liberação, expedição, recall, reclamações, calibração e limpeza.
3. **Validação do sistema computadorizado**: um documento que prove que o sistema faz o que deve. Os 41 testes automatizados (`pytest`) servem de evidência de teste (OQ). Falta o plano de validação, os requisitos do usuário e o relatório assinado pelo RT.
4. **Treinamento registrado** de cada usuário antes de receber acesso.
5. **Comunicação à autoridade sanitária**: queixas técnicas e eventos adversos podem exigir notificação no sistema oficial da ANVISA. O PB Gas Control registra e investiga, mas não envia a notificação.
6. **Análise do produto**: o sistema registra o laudo, mas não substitui o controle de qualidade.
7. **Cópia de segurança fora do servidor**: copie a pasta `backups/` para outro local, como nuvem ou disco externo. Teste a restauração periodicamente.

## Roteiro recomendado (curto prazo)

| Prazo | Ação | Responsável |
|---|---|---|
| Semana 1 | Criar um usuário por pessoa (nada de login compartilhado). Definir quem é GESTOR/RT | Admin |
| Semana 1 | Escrever o POP "Uso do PB Gas Control" (envase com checklist, liberação assinada, entrega/coleta, uso offline) | RT |
| Semana 2 | Cadastrar o parque de cilindros com a data real do último teste hidrostático | Operação |
| Semana 2 | Simular um recall: abrir uma ocorrência, bloquear o lote, exportar o dossiê, conferir os clientes e devolver o lote à quarentena | RT |
| Semana 3 | Documento de validação: requisitos → teste → evidência (os testes automatizados e os prints) | RT + TI |
| Mensal | Rodar "Verificar agora" na tela Auditoria e restaurar um backup em teste | TI |
