#!/bin/sh
# lazstation wrapper: boot Aurora 4X under Wine.
# Expects ~/Games/aurora4x/Aurora.exe — see INSTALL.md next to this file.
EXE="/home/lazi/Games/aurora4x/Aurora.exe"
if [ ! -f "$EXE" ]; then
  echo "Aurora 4X is not installed yet."
  echo "Read INSTALL.md in the aurora-4x game folder, then press enter."
  read -r _dummy
  exit 3
fi
export WINEPREFIX="/home/lazi/Games/aurora4x/prefix"
mkdir -p "$WINEPREFIX"
exec wine "$EXE" "$@"
