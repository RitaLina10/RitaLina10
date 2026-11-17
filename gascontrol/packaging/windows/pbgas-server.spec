# PyInstaller: gera dist/pbgas-server/ (onedir: inicialização rápida, sem extrair em %TEMP%).
# Executar a partir da pasta gascontrol/:  pyinstaller packaging/windows/pbgas-server.spec
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("app")
    + ["email_validator", "sqlalchemy.dialects.sqlite"]
)

a = Analysis(
    ["../../app/desktop.py"],
    pathex=["../.."],
    datas=[("../../app/static", "app/static")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="pbgas-server",
    console=False,          # roda como tarefa em segundo plano; logs vão para arquivo JSON
    icon="pbgas.ico",
    version="version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, name="pbgas-server")
