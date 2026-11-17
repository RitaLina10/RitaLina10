# PB Gas Control — Adequação à LGPD (Lei 13.709/2018)

O software fornece os **controles técnicos**. A adequação completa também depende de atos da empresa
que usa o sistema (a controladora), listados na seção 6.

## 1. Inventário de dados pessoais (registro das operações — art. 37)

| Dado | Titular | Finalidade | Base legal (art. 7º) | Onde fica | Retenção |
|---|---|---|---|---|---|
| Nome, CPF/CNPJ, telefone, e-mail, endereço, IE | Cliente | Entrega, comodato, faturamento, rastreabilidade | Execução de contrato (V); obrigação legal/regulatória (II) | Banco do servidor | Enquanto houver relação + prazo legal |
| Vínculo cliente ↔ cilindro ↔ lote | Cliente | Rastreabilidade e recall de gás medicinal (ANVISA) | Obrigação regulatória (II); tutela da saúde (VIII) | Movimentações (encadeadas por hash) | Prazo regulatório (padrão 5 anos) |
| Dados da NF-e | Cliente | Obrigação fiscal | Obrigação legal (II) | Banco + emissor (Focus NFe) + SEFAZ | 5 anos (CTN art. 173/174) |
| Nome, e-mail, perfil, hash da senha | Funcionário | Controle de acesso e assinatura eletrônica | Execução de contrato de trabalho (V); obrigação legal (II) | Banco | Enquanto ativo + prazo de auditoria |
| Autoria de cada operação e assinatura | Funcionário | Trilha de auditoria (Boas Práticas, RDC) | Obrigação regulatória (II) | Movimentações e auditoria | Igual à rastreabilidade |
| Localização (lat/long) no momento da operação | Funcionário (motorista) | Comprovar local da entrega | Legítimo interesse (IX), com aviso na tela | Movimentação | Igual à rastreabilidade |
| Endereço IP | Usuário | Segurança (bloqueio de força bruta) | Legítimo interesse (IX) | Só em memória (bloqueio) e logs técnicos | Logs: rotação de 10 × 10 MB |

**Não coletamos** dados de saúde de pacientes. O sistema registra o *estabelecimento* (home care ou hospital), nunca o paciente.
Em reclamações e eventos adversos, oriente a equipe a não digitar o nome do paciente.

## 2. Direitos do titular (art. 18) — como atender

| Direito | Como fazer no sistema |
|---|---|
| Confirmação e acesso (I, II) | **Clientes → Dados (LGPD)** (ADMIN): baixa um JSON com cadastro, movimentações e notas. A ação fica registrada na auditoria |
| Correção (III) | **Clientes → Endereço fiscal** (GESTOR/OPERADOR) |
| Portabilidade (V) | O mesmo JSON do acesso, em formato estruturado |
| Anonimização ou eliminação (IV, VI) | **Clientes → Anonimizar** (ADMIN, com assinatura eletrônica). Irreversível. Mantém a rastreabilidade sem identificar o titular |
| Revogação / oposição (IX) | Desativar o cliente. A anonimização vem depois do prazo de guarda |

**Retenção legal (art. 16, I).** O sistema **recusa** anonimizar enquanto houver:
- cilindro com o cliente;
- nota em rascunho ou processamento;
- movimentação ou NF-e dentro do prazo `LGPD_RETENTION_YEARS` (padrão 5 anos).

Nesses casos, responda ao titular que os dados são mantidos por obrigação legal (rastreabilidade sanitária e fiscal) e informe a data prevista de anonimização.

## 3. Medidas de segurança (art. 46)

- **Senhas.** Hash scrypt com sal. Regra de força mínima e bloqueio após tentativas.
- **Sessões.** A troca de senha encerra as sessões em todos os aparelhos.
- **Perfis.** ADMIN, GESTOR, OPERADOR e MOTORISTA. O motorista vê só as próprias ocorrências.
- **Assinatura eletrônica.** Reautenticação nos atos críticos: liberar lote, encerrar CAPA, cancelar NF-e, anonimizar.
- **Auditoria.** Cadeia SHA-256 detecta alteração ou exclusão de registros (`/api/audit/verify`).
- **Em trânsito.**
  - Na internet: HTTPS (Caddy/Let's Encrypt).
  - Na rede local (servidor Windows): HTTP. O app Android recusa `http://` para endereços públicos.
- **Em repouso.**
  - No servidor Windows, a pasta de dados é restrita a SYSTEM e Administradores.
  - No celular, os dados ficam excluídos do backup em nuvem, e o cache de clientes é apagado ao sair.
  - **Recomendado:** BitLocker no servidor e bloqueio de tela nos celulares.
- **Logs.** JSON sem CPF, e-mail ou senha, verificado no pentest.
- **Backups.** Diários, com verificação de integridade e rotação de 30 cópias. Guarde uma cópia fora do servidor, criptografada.
- **Minimização.**
  - Localização: só no momento da operação, sem rastreamento contínuo.
  - Exportações: só sob ação do usuário.

## 4. Incidentes de segurança (art. 48)

1. Isolar: desligar a tarefa "PB Gas Control" ou o container e trocar `JWT_SECRET` no `config.env`. Isso derruba todas as sessões.
2. Preservar evidências: `logs/pbgas.log` e uma cópia do banco.
3. Rodar `/api/audit/verify` para saber se houve alteração de registros.
4. Avaliar o risco aos titulares e comunicar à ANPD e aos titulares em prazo razoável (Resolução CD/ANPD nº 15/2024: 3 dias úteis).

## 5. Operadores (terceiros que tratam dados)

| Operador | Dados | Providência |
|---|---|---|
| Focus NFe (se ativado) | Dados da NF-e | Contrato com cláusulas LGPD (art. 39) |
| Provedor de nuvem/VPS (se usado) | Banco inteiro | Contrato e região de hospedagem; transferência internacional (art. 33) |
| GitHub (código, sem dados) | Nenhum dado pessoal | — |

## 6. Responsabilidades da empresa (não resolvidas por software)

- [ ] Nomear o **Encarregado (DPO)** e publicar o contato (art. 41).
- [ ] **Aviso de privacidade** para clientes (contrato ou site) e **comunicado interno** aos motoristas sobre a geolocalização.
- [ ] Termo de confidencialidade e treinamento de quem usa o sistema.
- [ ] Política de retenção aprovada. Ajuste `LGPD_RETENTION_YEARS` se o jurídico definir outro prazo.
- [ ] Contratos com operadores (seção 5).
- [ ] Processo para receber pedidos de titulares (e-mail do DPO) e responder em até 15 dias (art. 19, II).
- [ ] RIPD (relatório de impacto) se a ANPD solicitar. O inventário da seção 1 é a base.
