# PB Tecnologia - PB Gas Control — contexto para o Claude Code

Sistema de controle e rastreabilidade de cilindros de gases industriais e medicinais (inspirado em Oryx Place,
ERP SAG, RTSys SGI+SFA e OndeVou Gases). Código em `gascontrol/`. Idioma do produto e da documentação: português.

## Estado atual (versão 1.4.0)
- Backend Python 3.13 + FastAPI + SQLAlchemy (SQLite WAL), arquitetura em camadas:
  `app/domain` (regras puras) → `app/application` (serviços, portas) → `app/infra` (ORM, repositórios, gateways)
  → `app/api` (schemas, routers). Composição em `app/main.py`.
- Funcionalidades:
  - Rastreio por QR (`GC1:<serial>`), lotes com quarentena/liberação assinada e teste hidrostático.
  - Comodato e troca, app offline com fila de sincronização e auditoria encadeada por SHA-256.
  - CAPA/recall com bloqueio de lote, NF-e via Focus NFe e LGPD (exportar/anonimizar titular).
- Instaladores:
  - Windows: `packaging/windows` (PyInstaller + Inno Setup, tarefa SYSTEM, dados em `C:\ProgramData\PB Gas Control`).
  - Android: `android/` (WebView com a interface embarcada, leitor de QR nativo).
  - Ambos são gerados pelo GitHub Actions (`.github/workflows/installers.yml`).
- Identidade visual: arquivos originais em `branding/`. Ícone em `app/static/icon-*.png` e rodapé em `app/static/brand-footer.jpg`.
- Documentos: `README.md`, `CONFORMIDADE.md` (ANVISA RDC 887), `LGPD.md`, `SEGURANCA.md` (pentest 51/51).

## Pendências
- Confirmar no GitHub Actions que os jobs `windows` (teste do instalador) e `android` (APK) passaram.
  O teste do instalador Windows travou na 1ª execução; foram adicionados diagnósticos (setup.log, transcrição do
  `install-service.ps1`). Se falhar, ler a seção "Show-Diag" do log do job.
- APK oficial: criar keystore e cadastrar os segredos `PBGAS_KEYSTORE_*` (README → Android).
- Fora do sistema hoje: NF-e de remessa em comodato e notificação à ANVISA (Notivisa).

## Regras de trabalho
- Código production-ready, sem placeholders. Validar todas as entradas. Logs JSON sem dados pessoais.
- Rodar antes de commitar (na pasta `gascontrol`):
  `python -m pytest -q`, `bandit -q -r app -s B104` e `pip-audit -r requirements.txt`.
- Não renomear identificadores internos que quebram dados existentes: banco IndexedDB, prefixo `GC1:` do QR e issuer do JWT.
- Versão única em `app/__init__.py` (`__version__`): vale para servidor, instalador e APK.
