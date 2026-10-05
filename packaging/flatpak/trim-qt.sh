#!/bin/sh
# Убирает из установленного PySide6 то, что окну pywebview не нужно (QML, 3D, PDF, переводы, заголовки и примеры): ~650 МБ → ~450 МБ.
# Вызывается из манифеста Flatpak: sh packaging/flatpak/trim-qt.sh /app
set -e
PREFIX="${1:-/app}"
PS6=$(ls -d "$PREFIX"/lib/python3*/site-packages/PySide6)
cd "$PS6"
rm -rf include typesystems glue scripts qml Qt/qml
# модули Qt и их привязки, которых у FO76 DB нет в зависимостях
for m in Quick3D Pdf PdfWidgets ShaderTools QuickControls2 QuickDialogs2 QuickTemplates2 Charts Graphs GraphsWidgets \
         Multimedia MultimediaWidgets SpatialAudio Sensors Designer DesignerComponents Test Sql 3DCore 3DRender 3DInput 3DLogic \
         3DAnimation 3DExtras 3DQuick 3DQuickRender 3DQuickInput 3DQuickAnimation 3DQuickExtras 3DQuickScene2D Labs \
         DataVisualization VirtualKeyboard Location RemoteObjects Scxml StateMachine TextToSpeech WaylandCompositor \
         QuickParticles QuickTimeline QuickVectorImage QuickTest QmlLocalStorage QmlXmlListModel SerialPort SerialBus \
         WebView Bluetooth Nfc Help UiTools HttpServer NetworkAuth; do
    rm -f Qt/lib/libQt6$m.so* Qt/lib/libQt6${m}Private.so* ./Qt$m.abi3.so ./Qt$m.pyi
done
# переводы Qt WebEngine и Qt — только ru и en
find Qt/translations -type f ! \( -name '*_ru.qm' -o -name '*_en.qm' -o -name 'ru.pak' -o -name 'en-US.pak' \) -delete 2>/dev/null || true
find Qt/translations -type d -empty -delete 2>/dev/null || true
du -sh "$PS6" | cut -f1 | sed 's/^/PySide6 после чистки: /'
