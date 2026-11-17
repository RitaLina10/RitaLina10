"""Servidor PB Gas Control para Windows (empacotado com PyInstaller).

Responsabilidades (somente infraestrutura; nenhuma regra de negócio aqui):
  * Pasta de dados em %PROGRAMDATA%\\PB Gas Control (ou PBGAS_HOME).
  * Primeira execução: gera JWT_SECRET forte e a senha inicial do administrador,
    gravada em PRIMEIRO-ACESSO.txt (a pasta é restrita a SYSTEM/Administradores pelo instalador).
  * Logs JSON com rotação em arquivo (não há console quando roda como tarefa do Windows).
  * Backup diário do SQLite com verificação de integridade e rotação.
  * Sobe o Uvicorn em 0.0.0.0:<porta> para atender a rede local (celulares Android).

Uso:
  pbgas-server.exe serve            # padrão; usado pela tarefa agendada
  pbgas-server.exe info             # mostra pasta de dados, porta e endereços de rede
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import secrets
import socket
import string
import sys
import threading
import time
from pathlib import Path

APP_DIR_NAME = "PB Gas Control"
CONFIG_FILE = "config.env"
FIRST_ACCESS_FILE = "PRIMEIRO-ACESSO.txt"
DEFAULT_PORT = 8000
ALLOWED_KEYS = {
    "APP_ENV", "JWT_SECRET", "JWT_TTL_MINUTES", "ADMIN_EMAIL", "PORT", "LOG_LEVEL", "HYDRO_TEST_VALIDITY_YEARS",
    "HYDRO_ALERT_DAYS", "LOGIN_MAX_ATTEMPTS", "LOGIN_LOCKOUT_SECONDS", "METRICS_TOKEN", "FISCAL_PROVIDER",
    "FOCUS_TOKEN", "FOCUS_ENVIRONMENT", "EMITTER_CNPJ", "EMITTER_UF", "FISCAL_CANCEL_HOURS", "FISCAL_POLL_SECONDS",
    "CORS_ORIGINS", "BACKUP_KEEP", "BACKUP_INTERVAL_HOURS", "HOST", "MAX_BODY_BYTES", "LGPD_RETENTION_YEARS",
}

log = logging.getLogger("pbgas.desktop")


def data_dir() -> Path:
    override = os.getenv("PBGAS_HOME")
    if override:
        return Path(override)
    base = os.getenv("PROGRAMDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def read_env_file(path: Path) -> dict[str, str]:
    """Parser restrito KEY=VALUE: ignora chaves fora da lista permitida (não injeta PATH etc.)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip().upper()
        if not sep or key not in ALLOWED_KEYS:
            log.warning("config_line_ignored", extra={"line": lineno})
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def strong_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        core = "".join(secrets.choice(alphabet) for _ in range(length - 2))
        pwd = core[: length // 2] + "-" + secrets.choice(string.digits) + core[length // 2:]
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


def ensure_config(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    cfg_path = home / CONFIG_FILE
    cfg = read_env_file(cfg_path)
    changed = False
    if len(cfg.get("JWT_SECRET", "")) < 32:
        cfg["JWT_SECRET"] = secrets.token_urlsafe(48)
        changed = True
    for key, default in (("APP_ENV", "production"), ("PORT", str(DEFAULT_PORT)),
                         ("ADMIN_EMAIL", "admin@pbgascontrol.com.br"), ("BACKUP_KEEP", "30"),
                         ("BACKUP_INTERVAL_HOURS", "24")):
        if not cfg.get(key):
            cfg[key] = default
            changed = True
    if changed:
        body = "# PB Gas Control — configuração do servidor (gerada automaticamente)\n" + \
               "\n".join(f"{k}={v}" for k, v in sorted(cfg.items())) + "\n"
        tmp = cfg_path.with_suffix(".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(cfg_path)
    return cfg


def lan_addresses() -> list[str]:
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            ip = str(info[4][0])
            if not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    try:  # rota padrão: não envia pacotes (UDP connect apenas escolhe a interface)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(found)


def configure_file_logging(home: Path, level: str) -> None:
    from app.observability import JsonFormatter, configure_logging

    configure_logging(level)
    logs = home / "logs"
    logs.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(logs / "pbgas.log", maxBytes=10 * 1024 * 1024,
                                                   backupCount=10, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    if sys.stdout is None or not getattr(sys.stdout, "isatty", lambda: False)():
        root.handlers[:] = [handler]  # executável sem console: stdout pode ser None
    else:
        root.addHandler(handler)


def backup_loop(db: Path, dest: Path, keep: int, interval_h: float, stop: threading.Event) -> None:
    from app.tools.backup import run_backup

    if stop.wait(300):  # primeira cópia 5 min após subir: não compete com a inicialização
        return
    while not stop.is_set():
        try:
            if db.exists():
                run_backup(db, dest, keep)
        except Exception:
            log.exception("backup_failed")
        if stop.wait(interval_h * 3600):
            return


def write_first_access(home: Path, email: str, password: str, port: int) -> None:
    urls = [f"http://localhost:{port}"] + [f"http://{ip}:{port}" for ip in lan_addresses()]
    text = (
        "PB Tecnologia - PB Gas Control\n"
        "================================\n\n"
        f"Usuário administrador: {email}\n"
        f"Senha inicial:         {password}\n\n"
        "Troque esta senha no primeiro acesso (menu 'Minha senha') e apague este arquivo.\n\n"
        "Endereços do servidor (use no app Android, campo 'Servidor'):\n"
        + "\n".join(f"  {u}" for u in urls) + "\n"
    )
    (home / FIRST_ACCESS_FILE).write_text(text, encoding="utf-8")


def serve() -> int:
    home = data_dir()
    cfg = ensure_config(home)
    for key, value in cfg.items():
        os.environ[key] = value
    db_file = home / "pbgas.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
    port = int(cfg.get("PORT", DEFAULT_PORT))
    if not 1 <= port <= 65535:
        raise SystemExit("PORT inválida em config.env")
    configure_file_logging(home, cfg.get("LOG_LEVEL", "INFO").upper())

    first_run = not db_file.exists()
    if first_run:
        password = strong_password()
        os.environ["ADMIN_PASSWORD"] = password  # só no processo; nunca persiste em config.env
        write_first_access(home, cfg["ADMIN_EMAIL"], password, port)
        log.info("first_run_credentials_written", extra={"file": FIRST_ACCESS_FILE})

    import uvicorn

    from app.main import create_app

    app = create_app()
    os.environ.pop("ADMIN_PASSWORD", None)
    configure_file_logging(home, cfg.get("LOG_LEVEL", "INFO").upper())  # create_app redefine os handlers

    stop = threading.Event()
    threading.Thread(target=backup_loop, name="backup", daemon=True,
                     args=(db_file, home / "backups", int(cfg.get("BACKUP_KEEP", 30)),
                           float(cfg.get("BACKUP_INTERVAL_HOURS", 24)), stop)).start()
    log.info("server_starting", extra={"port": port, "home": str(home), "lan": lan_addresses()})
    try:
        # HOST=127.0.0.1 restringe ao próprio PC; o padrão atende a rede local (celulares).
        # Servidor de rede local por design (celulares acessam o PC).
        host = cfg.get("HOST", "0.0.0.0")  # nosec B104
        uvicorn.run(app, host=host, port=port, log_config=None, access_log=False, server_header=False,
                    timeout_keep_alive=10, limit_concurrency=200, h11_max_incomplete_event_size=64 * 1024)
    finally:
        stop.set()
    return 0


def info() -> int:
    home = data_dir()
    cfg = read_env_file(home / CONFIG_FILE)
    port = cfg.get("PORT", str(DEFAULT_PORT))
    print(f"Pasta de dados: {home}")
    print(f"Porta: {port}")
    for ip in lan_addresses():
        print(f"Endereço na rede: http://{ip}:{port}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pbgas-server", description="PB Tecnologia - PB Gas Control (servidor)")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "info"])
    args = parser.parse_args(argv)
    if args.command == "info":
        return info()
    while True:
        try:
            return serve()
        except SystemExit:
            raise
        except Exception:
            log.exception("server_crashed_restarting")
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
