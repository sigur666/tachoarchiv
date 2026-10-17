#!/bin/sh
# Baut TachoArchiv als Flatpak und erzeugt ein installierbares Bundle.
set -eu
APP=io.github.tachoarchiv.TachoArchiv
cd "$(dirname "$0")"

flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user -y --noninteractive flathub \
    org.kde.Platform//6.8 org.kde.Sdk//6.8 io.qt.PySide.BaseApp//6.8

flatpak-builder --user --force-clean --repo=repo build-dir flatpak/$APP.yml
flatpak build-bundle repo TachoArchiv.flatpak $APP \
    --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo

echo
echo "Fertig: TachoArchiv.flatpak"
echo "Installieren: flatpak install --user TachoArchiv.flatpak"
echo "Starten:      flatpak run $APP"
