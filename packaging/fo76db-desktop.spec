# PyInstaller: десктоп-версия — окно вместо браузера (pywebview).
#   Windows: один файл fo76db-desktop.exe без консоли, движок — Edge WebView2 (есть в Windows 10/11).
#   Linux:   папка dist/fo76db-desktop/ (Qt WebEngine большой, распаковка одного файла при каждом запуске была бы долгой),
#            в релизе — архив fo76db-desktop-linux-x86_64.tar.gz.
# Сборка: pip install ".[desktop,build]" && pyinstaller --noconfirm --clean packaging/fo76db-desktop.spec
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = SPECPATH + "/.."
WIN = sys.platform == "win32"

# у pywebview модули движков подключаются по имени: берём только нужный
webview_mods = [m for m in collect_submodules("webview")
                if not m.startswith("webview.platforms.") or m.split(".")[2] in
                (("winforms", "edgechromium", "mshtml") if WIN else ("qt",))]

a = Analysis(
    [ROOT + "/packaging/desktop_entry.py"],
    pathex=[ROOT],
    datas=[
        (ROOT + "/fo76db/web/static", "fo76db/web/static"),
        (ROOT + "/fo76db/web/templates", "fo76db/web/templates"),
    ],
    hiddenimports=collect_submodules("fo76db") + collect_submodules("uvicorn") + ["tzdata"] + webview_mods
                  + ([] if WIN else ["qtpy", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebChannel"]),
    excludes=["tkinter", "test", "unittest", "pydoc_data", "PyQt5", "PyQt6", "PySide2", "gi", "cefpython3"]
             + ([] if WIN else ["PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtQuick3D",
                                "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtDesigner", "PySide6.QtGraphs"]),
    noarchive=False,
)
# Linux: Qt WebEngine тянет лишнее — QML-модули, переводы на 50 языков, 3D, PDF. Окну pywebview это не нужно (~150 МБ).
DROP_LIBS = ("libQt6Quick3D", "libQt6Pdf", "libQt6ShaderTools", "libQt6QuickControls2", "libQt6QuickDialogs2",
             "libQt6QuickTemplates2", "libQt6Charts", "libQt6Graphs", "libQt6Multimedia", "libQt6SpatialAudio",
             "libQt6Sensors", "libQt6Designer", "libQt6Test", "libQt6Sql", "libQt63D", "libQt6Labs", "libQt6DataVisualization",
             "libQt6VirtualKeyboard", "libQt6Location", "libQt6RemoteObjects", "libQt6Scxml", "libQt6StateMachine",
             "libQt6TextToSpeech", "libQt6WaylandCompositor", "libQt6QuickParticles", "libQt6QuickTimeline",
             "libQt6QuickVectorImage", "libQt6QuickShapesDesignHelpers", "libQt6SerialPort", "libQt6WebView",
             "libQt6QuickTest", "libQt6QmlLocalStorage", "libQt6QmlXmlListModel",
             # тема GTK3 тянет GTK, glycin и вторую копию ICU (~50 МБ); без неё — стиль Fusion
             "libqgtk3")
# Библиотеки только из системы (как excludelist AppImage). Взятые с машины сборки (Ubuntu 22.04) ломают графику на свежих
# дистрибутивах: старый libstdc++ не подходит системному Mesa («GLIBCXX_… not found (required by libSPIRV-Tools.so)» →
# нет контекста OpenGL → WebEngine падает с SIGABRT); libgbm/libdrm должны совпадать с драйвером. Есть в любом настольном Linux.
HOST_LIBS = ("libstdc++.so", "libgcc_s.so", "libgbm.so", "libdrm.so", "libEGL.so", "libGL.so", "libGLX.so", "libGLdispatch.so",
             "libglapi.so", "libOpenGL.so", "libvulkan.so", "libexpat.so", "libz.so", "libX11.so", "libX11-xcb.so", "libxcb.so",
             "libfontconfig.so", "libfreetype.so", "libharfbuzz.so", "libasound.so", "libdbus-1.so", "libudev.so", "libsystemd.so",
             "libglib-2.0.so", "libgobject-2.0.so", "libgio-2.0.so", "libgmodule-2.0.so", "libgthread-2.0.so",
             "libgtk-3.so", "libgdk-3.so", "libgdk_pixbuf-2.0.so", "libatk-1.0.so", "libatk-bridge-2.0.so", "libatspi.so",
             "libcairo.so", "libcairo-gobject.so", "libpango-1.0.so", "libpangocairo-1.0.so", "libpangoft2-1.0.so",
             "libnss3.so", "libnssutil3.so", "libsmime3.so", "libsoftokn3.so", "libfreebl3.so", "libfreeblpriv3.so",
             "libnssckbi.so", "libnspr4.so", "libplc4.so", "libplds4.so", "libcups.so", "libpulse.so", "libpulsecommon")


def keep(dest: str) -> bool:
    d = dest.replace("\\", "/")
    if "/translations/" in d:
        return d.endswith(("/ru.pak", "/en-US.pak", "_ru.qm", "_en.qm"))
    if "PySide6/Qt/qml/" in d:
        return False
    name = d.rsplit("/", 1)[-1]
    return not name.startswith(DROP_LIBS) and not name.startswith(HOST_LIBS)


if not WIN:
    a.datas = [e for e in a.datas if keep(e[0])]
    a.binaries = [e for e in a.binaries if keep(e[0])]
pyz = PYZ(a.pure)
opts = [("X utf8_mode=1", None, "OPTION")]
if WIN:
    exe = EXE(pyz, a.scripts, opts, a.binaries, a.datas, name="fo76db-desktop", console=False,
              icon=ROOT + "/packaging/icons/fo76db.ico", upx=False, strip=False)
else:
    exe = EXE(pyz, a.scripts, opts, [], exclude_binaries=True, name="fo76db-desktop", console=True, upx=False, strip=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="fo76db-desktop", upx=False, strip=False)
