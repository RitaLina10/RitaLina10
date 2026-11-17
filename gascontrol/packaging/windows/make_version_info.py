"""Gera version_info.txt (metadados do .exe no Windows) a partir de app/__init__.py."""
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
match = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', (root / "app" / "__init__.py").read_text())
if not match:
    sys.exit("__version__ não encontrado")
major, minor, patch = (int(x) for x in match.groups())
version = f"{major}.{minor}.{patch}"
template = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({major}, {minor}, {patch}, 0), prodvers=({major}, {minor}, {patch}, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'PB Tecnologia'),
      StringStruct('FileDescription', 'PB Gas Control - Servidor'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'pbgas-server'),
      StringStruct('OriginalFilename', 'pbgas-server.exe'),
      StringStruct('ProductName', 'PB Tecnologia - PB Gas Control'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('LegalCopyright', 'PB Tecnologia')])]),
    VarFileInfo([VarStruct('Translation', [0x0416, 1200])])
  ]
)
"""
Path(__file__).with_name("version_info.txt").write_text(template, encoding="utf-8")
print(version)
