#!/bin/bash
# ---------------------------------------------------------------------------
# Собирает macOS-приложение «Этикетки CNH.app» — двойной клик запускает
# scripts/launch.sh (обновление из git + запуск сервера + открытие браузера).
#
#   bash scripts/build_app.sh
#
# Приложение — тонкая обёртка: код обновляется через git, пересобирать .app
# после обновлений НЕ нужно. Пересобрать нужно только если папка проекта
# переехала в другое место.
# ---------------------------------------------------------------------------
set -eu

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Этикетки CNH"
BUILD="$ROOT/$APP_NAME.app"
SRC="$(mktemp -t label_launcher).applescript"

cat > "$SRC" <<EOF
on run
	set launcher to "$ROOT/scripts/launch.sh"
	try
		do shell script "/bin/bash " & quoted form of launcher & " start"
	on error errMsg
		display dialog "Не удалось запустить «Этикетки CNH»:" & return & return & errMsg ¬
			buttons {"OK"} default button 1 with icon caution with title "Этикетки CNH"
	end try
end run
EOF

rm -rf "$BUILD"
osacompile -o "$BUILD" "$SRC"
rm -f "$SRC"
echo "собрано: $BUILD"

mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/$APP_NAME.app"
cp -R "$BUILD" "$HOME/Applications/"
echo "скопировано: $HOME/Applications/$APP_NAME.app  (видно в Launchpad и Spotlight)"
echo
echo "Дальше: откройте ~/Applications, перетащите приложение в Dock."
