"""Backup consistente do SQLite (API de backup online: não trava o app) com rotação e verificação.

Uso:  python -m app.tools.backup --dest /backups            (uma vez)
      python -m app.tools.backup --dest /backups --loop     (a cada BACKUP_INTERVAL_HOURS)
Para PostgreSQL use pg_dump; este utilitário recusa URLs que não sejam SQLite.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.observability import configure_logging

log = logging.getLogger("gascontrol.backup")


def sqlite_path(url: str) -> Path:
    if not url.startswith("sqlite:///"):
        raise SystemExit("Backup embutido suporta apenas SQLite; use pg_dump para PostgreSQL")
    return Path(url.removeprefix("sqlite:///"))


def run_backup(db: Path, dest: Path, keep: int) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = dest / f"gascontrol-{stamp}.db"
    tmp = target.with_suffix(".tmp")
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    try:
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
            if out.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("integrity_check falhou na cópia")
        finally:
            out.close()
    finally:
        src.close()
    tmp.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".db.sha256").write_text(f"{digest}  {target.name}\n")
    backups = sorted(dest.glob("gascontrol-*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
        old.with_suffix(".db.sha256").unlink(missing_ok=True)
    log.info("backup_ok", extra={"file": target.name, "sha256": digest, "size": target.stat().st_size})
    return target


def main() -> int:
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    p = argparse.ArgumentParser()
    p.add_argument("--dest", required=True)
    p.add_argument("--loop", action="store_true")
    a = p.parse_args()
    db = sqlite_path(os.getenv("DATABASE_URL", "sqlite:///./data/gascontrol.db"))
    keep = int(os.getenv("BACKUP_KEEP", "56"))
    interval = max(1, int(os.getenv("BACKUP_INTERVAL_HOURS", "6"))) * 3600
    while True:
        try:
            if db.exists():
                run_backup(db, Path(a.dest), keep)
            else:
                log.warning("backup_skipped_no_db", extra={"path": str(db)})
        except Exception:
            log.exception("backup_failed")
            if not a.loop:
                return 1
        if not a.loop:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
