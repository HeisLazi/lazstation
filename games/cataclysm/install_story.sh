#!/bin/sh
# Install (or refresh) the Haven Story mod + HavenStory world.
# Source of truth: this folder (games/cataclysm/haven_story/).
# Run from anywhere:  sh install_story.sh
set -eu
HERE="$(dirname "$0")"
CDDA="${CDDA_DIR:-/home/lazi/games/cataclysm/cataclysmdda-0.I}"
SRC="$HERE/haven_story"
MODDIR="$CDDA/data/mods/haven_story"
WORLD="$CDDA/save/HavenStory"

[ -d "$SRC" ] || { echo "mod source not found: $SRC"; exit 1; }
[ -x "$CDDA/cataclysm" ] || { echo "CDDA not found at $CDDA (set CDDA_DIR=...)"; exit 1; }

mkdir -p "$MODDIR"
cp "$SRC/modinfo.json" "$SRC/scenario.json" "$SRC/items.json" \
   "$SRC/missions_intro.json" "$SRC/missions_act1.json" \
   "$SRC/missions_side_vex.json" "$MODDIR/"

mkdir -p "$WORLD"
printf '[\n  "dda",\n  "haven_story"\n]\n' > "$WORLD/mods.json"
if [ ! -f "$WORLD/worldoptions.json" ]; then
  if [ -f "$CDDA/save/Swissvale/worldoptions.json" ]; then
    cp "$CDDA/save/Swissvale/worldoptions.json" "$WORLD/worldoptions.json"
  else
    printf '[]\n' > "$WORLD/worldoptions.json"
  fi
fi

if [ -t 1 ]; then
  cd "$CDDA" && ./cataclysm --check-mods haven_story
else
  echo "(skipping --check-mods: no terminal attached; run it by hand in a terminal)"
fi
echo "Haven Story installed. World: HavenStory (mods: dda + haven_story)."
