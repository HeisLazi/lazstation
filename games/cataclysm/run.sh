#!/bin/sh
# lazstation wrapper: Cataclysm needs its data/ dir as cwd.
cd /home/lazi/games/cataclysm/cataclysmdda-0.I || exit 1
exec ./cataclysm "$@"
