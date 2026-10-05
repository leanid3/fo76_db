# PyInstaller: один файл fo76db (Linux) или fo76db.exe (Windows).
# Сборка: pyinstaller --noconfirm --clean packaging/fo76db.spec  (из корня репозитория; результат — dist/)
# Подробности — docs/packaging.md.
from PyInstaller.utils.hooks import collect_submodules

ROOT = SPECPATH + "/.."

a = Analysis(
    [ROOT + "/packaging/entry.py"],
    pathex=[ROOT],
    datas=[
        (ROOT + "/fo76db/web/static", "fo76db/web/static"),
        (ROOT + "/fo76db/web/templates", "fo76db/web/templates"),
    ],
    # модули, которые импортируются внутри функций или по строке (uvicorn выбирает протоколы и циклы на лету)
    hiddenimports=collect_submodules("fo76db") + collect_submodules("uvicorn") + ["tzdata"],
    excludes=["tkinter", "test", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    # UTF-8 mode (python -X utf8): кодировка по умолчанию для open(), stdout и pipe на Windows — UTF-8, а не cp1252
    [("X utf8_mode=1", None, "OPTION")],
    a.binaries,
    a.datas,
    name="fo76db",
    console=True,  # консоль нужна: команды, журнал сервера; двойной клик открывает браузер
    icon=ROOT + "/packaging/icons/fo76db.ico",  # Windows; на Linux не используется
    upx=False,
    strip=False,
)
