#!/bin/sh
# Startskript im Flatpak: PySide6 der BaseApp und das Programmpaket in den Suchpfad aufnehmen.
for d in /app/lib/python3*/site-packages; do
    [ -d "$d" ] && PYTHONPATH="$d${PYTHONPATH:+:$PYTHONPATH}"
done
PYTHONPATH="/app/lib/tachoarchiv${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
exec python3 -m tachoarchiv "$@"
