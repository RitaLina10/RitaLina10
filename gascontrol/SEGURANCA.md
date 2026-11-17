# PB Gas Control — Relatório de segurança e pentest

**Versão avaliada:** 1.4.0 · **Data:** 17/11/2026 · **Escopo:**
- API e interface web.
- Servidor Windows, executado pelo próprio launcher em modo produção.
- App Android: revisão de código. O APK é compilado no CI.

**Método:**
- Análise estática (bandit) e varredura de CVEs nas dependências (pip-audit).
- Pentest caixa-cinza automatizado nas 57 rotas da API: `security/pentest_api.py`.
- Teste de XSS no navegador real: `security/xss_browser_check.js`.
- Suíte de testes de segurança: `tests/test_security.py`, que roda no CI a cada alteração.

## Resultado

| Verificação | Resultado |
|---|---|
| bandit (SAST) | 1 alerta, intencional: o servidor escuta na rede local (`HOST` configurável) |
| pip-audit (CVEs nas dependências) | Nenhuma vulnerabilidade conhecida |
| Pentest da API | **51/51 aprovados** após as correções abaixo |
| XSS armazenado no navegador | Não executa: o payload aparece como texto e não houve violação de CSP |

### Vulnerabilidades encontradas e corrigidas

| # | Severidade | Problema | Correção |
|---|---|---|---|
| 1 | **Alta (DoS)** | ID gigante na URL (`/api/customers/99999999999999999999999`) estourava o INTEGER do SQLite: erro 500 e conexão derrubada | Todos os IDs e offsets limitados na validação, mais um tratador que devolve 422. Teste `test_huge_ids_rejected_without_500` |
| 2 | Média | Após a troca de senha, sessões antigas (ex.: celular perdido) continuavam válidas por até 8 h | O token carrega a versão da senha; a troca revoga todas as sessões. Teste `test_password_change_revokes_old_sessions` |
| 3 | Média (DoS) | Sem limite de tamanho de requisição no servidor Windows (sem proxy na frente) | Middleware de limite (`MAX_BODY_BYTES`, padrão 2 MB), inclusive para corpo *chunked* |
| 4 | Baixa | `/metrics` aberto para a rede local sem token | Em produção, sem `METRICS_TOKEN`, só responde para a própria máquina |
| 5 | Baixa | Cabeçalho `server: uvicorn` revelava o software | Removido |
| 6 | Baixa | Campo "Servidor" do app recusava endereço digitado sem `http://` (achado pelo E2E) | Campo de texto livre, normalizado com validação |

### Verificações aprovadas (resumo)

- **Controle de acesso:**
  - Todas as 57 rotas recusam acesso anônimo.
  - O MOTORISTA não executa nenhuma ação administrativa.
  - Usuários, auditoria, fiscal e LGPD são bloqueados por perfil.
  - IDOR: um motorista não vê ocorrência de outro.
- **Injeção:**
  - SQL injection em buscas e filtros (consultas parametrizadas pelo ORM).
  - Mass assignment recusado (`extra="forbid"`).
  - Enum e JSON inválidos devolvem 422 sem stack trace.
- **Autenticação:**
  - JWT adulterado ou com `alg=none` é recusado.
  - Bloqueio após 5 tentativas.
  - Mesma mensagem e mesmo tempo de resposta para usuário inexistente e senha errada: não há enumeração de usuários.
- **Cabeçalhos:**
  - CSP sem `unsafe-inline`/`eval`, HSTS, `X-Frame-Options`, `nosniff`, `Referrer-Policy`.
  - `/docs` e `/openapi.json` desligados em produção.
- **Arquivos:** path traversal em `/static` bloqueado; o hash de senha nunca é exposto.
- **CORS:** lista fechada (só o app Android); nenhuma origem é refletida.
- **Logs:** não contêm CPF, e-mail nem senha.
- **Exportação CSV:** proteção contra injeção de fórmulas (`=HYPERLINK…` é neutralizado).

### App Android (revisão de código)

- **Dados no aparelho:** `allowBackup=false` e regras de extração que excluem os dados do backup em nuvem.
- **Componentes:** apenas a tela principal é exportada; o `FileProvider` não é exportado.
- **Ponte JS ⇄ nativo:**
  - Usa `addWebMessageListener`, restrita à origem do app. Não usa `addJavascriptInterface`.
  - Valida nome, tipo e tamanho dos arquivos (até 15 MB).
- **WebView:**
  - Sem acesso a `file://`/`content://`; captura de câmera via web negada (o leitor é nativo).
  - Depuração remota só no build de teste.
  - Navegação para outros endereços abre no navegador do sistema, só com esquemas http/https/mailto/tel.

## Riscos residuais (aceitos e documentados)

| Risco | Por quê | Mitigação recomendada |
|---|---|---|
| HTTP na rede local (servidor Windows) | Celulares acessam o PC sem certificado | Wi-Fi exclusivo da empresa com WPA2/WPA3 e rede de visitantes separada. Para internet, use Docker + Caddy (HTTPS) |
| APK permite HTTP e conteúdo misto | Necessário para o modo rede local | A interface recusa `http://` para endereços públicos |
| Banco SQLite sem criptografia própria | Simplicidade e backup | BitLocker no servidor; pasta restrita a Administradores |
| Bloqueio de força bruta em memória | Zera ao reiniciar o servidor | Suficiente para uma instância; com várias réplicas, usar Redis |
| Instalador e APK sem assinatura comercial | Certificado de assinatura de código é pago | Windows mostra o aviso do SmartScreen. Para o APK, configure a chave de release (README) |

## Como repetir

```bash
# na pasta gascontrol — análise estática e dependências
pip install bandit pip-audit && bandit -q -r app && pip-audit -r requirements.txt
python -m pytest -q tests/test_security.py
# pentest (em instalação de homologação, nunca em produção)
python security/pentest_api.py http://127.0.0.1:8000 admin@empresa.com.br '<senha>' . "$PBGAS_HOME/logs/pbgas.log"
```
