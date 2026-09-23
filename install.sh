#!/usr/bin/env bash
# Put `lazstation` (and the short `laz`) on your PATH.
set -euo pipefail
ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"
mkdir -p "$BIN"

for name in lazstation laz; do
  ln -sfn "$ROOT/bin/lazstation" "$BIN/$name"
  echo "  linked $BIN/$name"
done

echo
if command -v lazstation >/dev/null 2>&1; then
  echo "  ready — type 'lazstation' to boot."
else
  echo "  $BIN is not on your PATH yet. Add it:"
  echo
  case "${SHELL##*/}" in
    fish) echo "    fish_add_path $BIN" ;;
    zsh)  echo "    echo 'export PATH=\"$BIN:\$PATH\"' >> ~/.zshrc && exec zsh" ;;
    *)    echo "    echo 'export PATH=\"$BIN:\$PATH\"' >> ~/.bashrc && exec bash" ;;
  esac
  echo
  echo "  then type 'lazstation' to boot."
fi
