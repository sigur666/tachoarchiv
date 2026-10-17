#!/bin/sh
# TachoArchiv – Installation auf beliebigen Linux-Distributionen.
#
#   ./install.sh                 systemweit nach /usr/local (fragt per sudo nach Rechten)
#   ./install.sh --user          nur für den aktuellen Benutzer, nach ~/.local
#   ./install.sh --prefix=/opt   eigenes Ziel
#   ./install.sh --no-deps       nichts nachinstallieren, nur das Programm kopieren
#   ./install.sh --venv          Qt immer aus PyPI holen statt aus der Distribution
#
# Benötigt werden Python ab 3.10, PySide6 (Qt), die PC/SC-Bibliothek und Schriften
# für arabische und indische Schrift. Was davon fehlt, wird über die Paketverwaltung
# der Distribution nachinstalliert; findet sich dort kein PySide6, legt das Skript
# eine eigene Python-Umgebung an und holt Qt aus PyPI.
set -eu

APP=tachoarchiv
APP_ID=io.github.tachoarchiv.TachoArchiv
SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

MODE=system
PREFIX=
WITH_DEPS=1
FORCE_VENV=0

for arg in "$@"; do
    case "$arg" in
        --user) MODE=user ;;
        --system) MODE=system ;;
        --prefix=*) PREFIX=${arg#--prefix=} ;;
        --no-deps) WITH_DEPS=0 ;;
        --venv) FORCE_VENV=1 ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unbekannte Option: $arg" >&2; exit 2 ;;
    esac
done

[ "$MODE" = user ] && [ -z "$PREFIX" ] && PREFIX=$HOME/.local
[ -z "$PREFIX" ] && PREFIX=/usr/local
LIBDIR=$PREFIX/lib/$APP
MISSING=

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }

# ---------------------------------------------------------------- Rechte
if [ "$MODE" = system ] && [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        ROOT="sudo"
    else
        echo "Für die systemweite Installation werden Rechte benötigt." >&2
        echo "Entweder als root ausführen oder './install.sh --user' verwenden." >&2
        exit 1
    fi
else
    ROOT=""
fi
# Im Benutzermodus werden Pakete nur mit sudo installiert, sonst gar nicht.
if [ "$MODE" = user ]; then
    if command -v sudo >/dev/null 2>&1 || [ "$(id -u)" -eq 0 ]; then
        DEPROOT=$([ "$(id -u)" -eq 0 ] && echo "" || echo "sudo")
    else
        DEPROOT=
        [ "$WITH_DEPS" = 1 ] && say "Kein sudo gefunden – Abhängigkeiten werden übersprungen."
        WITH_DEPS=0
    fi
else
    DEPROOT=$ROOT
fi

# ---------------------------------------------------------------- Distribution
ID=""; ID_LIKE=""
[ -r /etc/os-release ] && . /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*) FAMILY=debian ;;
    *" fedora "*|*" rhel "*|*" centos "*) FAMILY=fedora ;;
    *" arch "*) FAMILY=arch ;;
    *" suse "*|*" opensuse "*) FAMILY=suse ;;
    *" alpine "*) FAMILY=alpine ;;
    *) FAMILY=unbekannt ;;
esac
if [ "$FAMILY" = unbekannt ]; then          # Rückfall über die Paketverwaltung
    for pm in apt-get dnf pacman zypper apk; do
        command -v $pm >/dev/null 2>&1 || continue
        case $pm in
            apt-get) FAMILY=debian ;; dnf) FAMILY=fedora ;; pacman) FAMILY=arch ;;
            zypper) FAMILY=suse ;; apk) FAMILY=alpine ;;
        esac
        break
    done
fi
say "Distribution: ${PRETTY_NAME:-unbekannt} (Familie: $FAMILY)"
say "Ziel:         $PREFIX"

# ---------------------------------------------------------------- Python
PYTHON=
FALLBACK=
# Bevorzugt wird eine Python-Version, die PySide6 schon mitbringt – das erspart
# den Umweg über PyPI, wenn die Distribution Qt für eine ältere Version paketiert.
for cand in python3 python3.13 python3.12 python3.11 python3.10; do
    command -v "$cand" >/dev/null 2>&1 || continue
    "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' || continue
    [ -z "$FALLBACK" ] && FALLBACK=$(command -v "$cand")
    if "$cand" -c 'import PySide6.QtWidgets' >/dev/null 2>&1; then
        PYTHON=$(command -v "$cand")
        break
    fi
done
[ -z "$PYTHON" ] && PYTHON=$FALLBACK
if [ -z "$PYTHON" ]; then
    echo "Es wird Python ab Version 3.10 benötigt, es wurde keine passende gefunden." >&2
    exit 1
fi
say "Python:       $PYTHON ($("$PYTHON" -c 'import platform;print(platform.python_version())'))"

# ---------------------------------------------------------------- Abhängigkeiten
pkg_install() {                              # je Paket einzeln, Fehlschlag wird gemerkt
    for p in "$@"; do
        printf '   %-34s' "$p"
        if $DEPROOT $PM_INSTALL "$p" >/dev/null 2>&1; then
            echo "ok"
        else
            echo "nicht verfügbar"
            MISSING="$MISSING $p"
        fi
    done
}

if [ "$WITH_DEPS" = 1 ]; then
    step "Abhängigkeiten"
    case $FAMILY in
        debian)
            PM_INSTALL="apt-get install -y -q"
            $DEPROOT apt-get update -q >/dev/null 2>&1 || true
            pkg_install libpcsclite1 pcscd fonts-noto-core python3-cryptography
            [ "$FORCE_VENV" = 0 ] && pkg_install python3-pyside6.qtwidgets \
                python3-pyside6.qtprintsupport python3-pyside6.qtgui python3-pyside6.qtcore
            ;;
        fedora)
            PM_INSTALL="$(command -v dnf >/dev/null 2>&1 && echo dnf || echo yum) install -y -q"
            pkg_install pcsc-lite pcsc-lite-ccid python3-cryptography google-noto-sans-fonts \
                google-noto-naskh-arabic-fonts google-noto-sans-devanagari-fonts \
                google-noto-sans-gurmukhi-fonts
            [ "$FORCE_VENV" = 0 ] && pkg_install python3-pyside6
            ;;
        arch)
            PM_INSTALL="pacman -S --needed --noconfirm"
            pkg_install pcsclite ccid python-cryptography noto-fonts noto-fonts-extra
            [ "$FORCE_VENV" = 0 ] && pkg_install pyside6
            ;;
        suse)
            PM_INSTALL="zypper --non-interactive install"
            pkg_install pcsc-lite pcsc-ccid python3-cryptography noto-sans-fonts \
                noto-naskh-arabic-fonts noto-sans-devanagari-fonts noto-sans-gurmukhi-fonts
            [ "$FORCE_VENV" = 0 ] && pkg_install python3-pyside6
            ;;
        alpine)
            PM_INSTALL="apk add"
            pkg_install pcsc-lite pcsc-lite-libs ccid py3-cryptography font-noto \
                font-noto-arabic font-noto-devanagari font-noto-gurmukhi
            [ "$FORCE_VENV" = 0 ] && pkg_install py3-pyside6
            ;;
        *)
            say "Unbekannte Paketverwaltung – bitte PC/SC-Bibliothek, pcscd und Noto-Schriften"
            say "selbst installieren. Qt holt das Skript gleich aus PyPI."
            ;;
    esac
fi

# ---------------------------------------------------------------- Qt bereitstellen
step "Qt (PySide6)"
VENV=0
if [ "$FORCE_VENV" = 0 ] && "$PYTHON" -c 'import PySide6.QtWidgets' >/dev/null 2>&1; then
    say "   PySide6 ist vorhanden."
else
    say "   PySide6 fehlt – eigene Python-Umgebung unter $LIBDIR/venv (Download ca. 100 MB)."
    $ROOT mkdir -p "$LIBDIR"
    if ! $ROOT "$PYTHON" -m venv "$LIBDIR/venv" >/dev/null 2>&1; then
        echo "Die Python-Umgebung ließ sich nicht anlegen." >&2
        case $FAMILY in
            debian) echo "Bitte 'python3-venv' installieren und erneut versuchen." >&2 ;;
            *) echo "Bitte das venv-Modul der Distribution installieren." >&2 ;;
        esac
        exit 1
    fi
    if ! $ROOT "$LIBDIR/venv/bin/pip" install --quiet --upgrade PySide6-Essentials cryptography; then
        echo "PySide6 ließ sich nicht aus PyPI installieren (Netzwerk? Proxy?)." >&2
        exit 1
    fi
    PYTHON="$LIBDIR/venv/bin/python"
    VENV=1
    say "   PySide6 aus PyPI installiert."
fi
# Fehlende Qt-Pakete der Distribution sind kein Mangel mehr, sobald Qt steht.
MISSING=$(printf '%s' "$MISSING" | tr ' ' '\n' | grep -v -i pyside | tr '\n' ' ')

# ---------------------------------------------------------------- Dateien
step "Programm"
$ROOT mkdir -p "$LIBDIR/$APP" "$PREFIX/bin" \
    "$PREFIX/share/applications" "$PREFIX/share/metainfo" \
    "$PREFIX/share/icons/hicolor/scalable/apps" "$PREFIX/share/man/man1"

$ROOT rm -rf "$LIBDIR/$APP"
$ROOT cp -r "$SRC/$APP" "$LIBDIR/$APP"
$ROOT find "$LIBDIR/$APP" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

tmp=$(mktemp)
cat > "$tmp" <<EOF
#!/bin/sh
# TachoArchiv – von install.sh erzeugt
PYTHONPATH="$LIBDIR\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPATH
exec "$PYTHON" -m $APP "\$@"
EOF
$ROOT install -m 755 "$tmp" "$PREFIX/bin/$APP"
rm -f "$tmp"

sed "s|^Exec=.*|Exec=$PREFIX/bin/$APP|" "$SRC/data/$APP_ID.desktop" > "$tmp.desktop"
$ROOT install -m 644 "$tmp.desktop" "$PREFIX/share/applications/$APP_ID.desktop"
rm -f "$tmp.desktop"
$ROOT install -m 644 "$SRC/data/$APP_ID.svg" "$PREFIX/share/icons/hicolor/scalable/apps/$APP_ID.svg"
$ROOT install -m 644 "$SRC/data/$APP_ID.metainfo.xml" "$PREFIX/share/metainfo/$APP_ID.metainfo.xml"
[ -f "$SRC/debian/$APP.1" ] && $ROOT install -m 644 "$SRC/debian/$APP.1" "$PREFIX/share/man/man1/$APP.1"

printf 'prefix=%s\nvenv=%s\npython=%s\n' "$PREFIX" "$VENV" "$PYTHON" > "$tmp"
$ROOT install -m 644 "$tmp" "$LIBDIR/installiert.conf"
rm -f "$tmp"

command -v update-desktop-database >/dev/null 2>&1 && \
    $ROOT update-desktop-database "$PREFIX/share/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    $ROOT gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true

# ---------------------------------------------------------------- Kartenleser
if [ "$WITH_DEPS" = 1 ] && command -v systemctl >/dev/null 2>&1; then
    step "Kartenleser-Dienst"
    if $DEPROOT systemctl enable --now pcscd.socket >/dev/null 2>&1; then
        say "   pcscd ist eingerichtet."
    else
        say "   pcscd konnte nicht gestartet werden – bitte von Hand prüfen."
    fi
fi

# ---------------------------------------------------------------- Abschluss
step "Fertig"
if "$PREFIX/bin/$APP" --version >/dev/null 2>&1; then
    say "   $("$PREFIX/bin/$APP" --version) ist installiert."
else
    say "   Achtung: Der Start schlug fehl. Bitte '$PREFIX/bin/$APP' von Hand aufrufen."
fi
MISSING=$(printf '%s' "$MISSING" | tr -s ' ' | sed 's/^ *//; s/ *$//')
if [ -n "$MISSING" ]; then
    say ""
    say "Diese Pakete waren nicht verfügbar und sollten nachgeholt werden:"
    say "  $MISSING"
fi
case ":$PATH:" in
    *":$PREFIX/bin:"*) ;;
    *) say ""; say "Hinweis: $PREFIX/bin liegt nicht im PATH – Aufruf über den vollen Pfad"; say "         oder über den Menüeintrag." ;;
esac
say ""
say "Starten:      $APP     (oder über das Anwendungsmenü)"
say "Entfernen:    $SRC/uninstall.sh$([ "$MODE" = user ] && echo ' --user')"
