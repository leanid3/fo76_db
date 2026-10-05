#!/bin/sh
# Ярлык FO76 DB в меню приложений для распакованной десктоп-версии (fo76db-desktop-linux-x86_64.tar.gz).
# Запуск из распакованной папки: ./install-linux.sh        Удаление ярлыка: ./install-linux.sh --remove
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"
if [ "$1" = "--remove" ]; then
    rm -f "$APPS/fo76db-desktop.desktop" "$ICONS/fo76db.png"
    echo "Ярлык удалён"; exit 0
fi
mkdir -p "$APPS" "$ICONS"
cp "$DIR/_internal/fo76db/web/static/icons/icon-512.png" "$ICONS/fo76db.png"
cat > "$APPS/fo76db-desktop.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=FO76 DB
Comment=База предметов, инвентаря и событий Fallout 76
Exec="$DIR/fo76db-desktop"
Icon=fo76db
Terminal=false
Categories=Game;Utility;
DESKTOP
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
echo "Ярлык: $APPS/fo76db-desktop.desktop"
