#!/bin/sh
# lazstation wrapper: Cataclysm needs its data/ dir as cwd.
cd /home/lazi/Games/cdda || exit 1
exec ./cataclysm-tiles "$@"
