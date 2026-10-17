#!/bin/sh
# TachoArchiv – entfernen.
#
#   ./uninstall.sh             systemweite Installation unter /usr/local entfernen
#   ./uninstall.sh --user      Installation unter ~/.local entfernen
#   ./uninstall.sh --prefix=/opt
#   ./uninstall.sh --purge     zusätzlich Archiv und Einstellungen löschen (fragt nach)
#
# Ohne --purge bleiben das Archiv mit den DDD-Dateien und die Einstellungen erhalten.
set -eu

APP=tachoarchiv
APP_ID=io.github.tachoarchiv.TachoArchiv

MODE=system
PREFIX=
PURGE=0

for arg in "$@"; do
    case "$arg" in
        --user) MODE=user ;;
        --system) MODE=system ;;
        --prefix=*) PREFIX=${arg#--prefix=} ;;
        --purge) PURGE=1 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unbekannte Option: $arg" >&2; exit 2 ;;
    esac
done

[ "$MODE" = user ] && [ -z "$PREFIX" ] && PREFIX=$HOME/.local
[ -z "$PREFIX" ] && PREFIX=/usr/local
LIBDIR=$PREFIX/lib/$APP

if [ ! -d "$LIBDIR" ]; then
    echo "Unter $PREFIX ist TachoArchiv nicht installiert." >&2
    echo "Vielleicht '--user' oder '--prefix=…' angeben?" >&2
    exit 1
fi

if [ "$MODE" = system ] && [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then ROOT="sudo"; else
        echo "Zum Entfernen werden Rechte benötigt (als root ausführen)." >&2
        exit 1
    fi
else
    ROOT=""
fi

echo "Entferne TachoArchiv aus $PREFIX"
$ROOT rm -rf "$LIBDIR"
$ROOT rm -f "$PREFIX/bin/$APP" \
    "$PREFIX/share/applications/$APP_ID.desktop" \
    "$PREFIX/share/icons/hicolor/scalable/apps/$APP_ID.svg" \
    "$PREFIX/share/metainfo/$APP_ID.metainfo.xml" \
    "$PREFIX/share/man/man1/$APP.1"

command -v update-desktop-database >/dev/null 2>&1 && \
    $ROOT update-desktop-database "$PREFIX/share/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    $ROOT gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true

# Bei einem eigenen Zielpfad bleiben sonst leere Verzeichnisse zurück. Standardpfade
# wie /usr/local oder ~/.local bleiben unangetastet – dort liegen andere Programme.
case "$PREFIX" in
    /usr|/usr/local|"$HOME/.local") ;;
    *)
        for d in applications metainfo "icons/hicolor/scalable/apps" "icons/hicolor/scalable" \
                 "icons/hicolor" icons "man/man1" man; do
            dir=$PREFIX/share/$d
            [ -d "$dir" ] || continue
            rest=$(ls -A "$dir" 2>/dev/null | grep -v -e '^mimeinfo\.cache$' -e '^icon-theme\.cache$' || true)
            if [ -z "$rest" ]; then
                $ROOT rm -f "$dir/mimeinfo.cache" "$dir/icon-theme.cache" 2>/dev/null || true
                $ROOT rmdir "$dir" 2>/dev/null || true
            fi
        done
        for d in share lib bin ""; do
            $ROOT rmdir "$PREFIX${d:+/$d}" 2>/dev/null || true
        done
        ;;
esac

DATA=${XDG_DATA_HOME:-$HOME/.local/share}/TachoArchiv
CONF=${XDG_CONFIG_HOME:-$HOME/.config}/TachoArchiv

if [ "$PURGE" = 1 ]; then
    echo ""
    echo "Dabei werden das Archiv und die Einstellungen unwiderruflich gelöscht:"
    [ -d "$DATA" ] && echo "  $DATA"
    [ -d "$CONF" ] && echo "  $CONF"
    printf "Wirklich löschen? [j/N] "
    read -r answer
    case "$answer" in
        j|J|y|Y) rm -rf "$DATA" "$CONF"; echo "Gelöscht." ;;
        *) echo "Archiv bleibt erhalten." ;;
    esac
else
    echo ""
    echo "Das Archiv bleibt erhalten:"
    [ -d "$DATA" ] && echo "  $DATA"
    [ -d "$CONF" ] && echo "  $CONF"
    echo "Mit './uninstall.sh --purge' lässt es sich ebenfalls löschen."
fi

echo ""
echo "Nicht entfernt wurden pcscd, Qt und die Schriften – die können andere Programme brauchen."
