# Rebuilding the Rogue Collection entry

The `rogue` shelf entry points at a local build of
[mikeyk730/Rogue-Collection](https://github.com/mikeyk730/Rogue-Collection)
(v3.1.0 source zip) at `~/Games/Rogue-Collection-main`. It is not in the
repo — rebuild it on a new machine like this.

## Deps

```bash
sudo pacman -S --needed base-devel qt5-base qt5-declarative qt5-multimedia
```

## Patches (upstream assumes old GCC/MSVC)

1. `src/MyCurses/curses.h` — guard the PDCurses bool typedef for C23:
   ```c
   #if defined(__cplusplus) || !defined(__STDC_VERSION__) || __STDC_VERSION__ < 202311L
   typedef unsigned char bool;
   #endif
   ```
2. `src/RogueVersions/*/rogue.h` (+ `Rogue_5_3/daemon.c`) — K&R `()` function
   pointer types for the daemon system must name the arg:
   `void (*d_func)()` → `void (*d_func)(int)`, same for `(*func)()` in
   `start_daemon` / `fuse` / `extinguish` / `find_slot` (+ header prototypes).
3. `src/Shared/Frontend/environment.cpp` — add `#include <cstdint>`.
4. `src/RogueCollectionQml/{RogueCollection/app.pro,RetroRogueCollection/app.pro,RoguePlugin/import.pro}`
   — drop `-Werror` from `QMAKE_CXXFLAGS` (Qt deprecation warnings are fatal
   otherwise).

## Build

```bash
cd ~/Games/Rogue-Collection-main/src
export CF="-Wall -pedantic -shared -fPIC -fvisibility=hidden -fcommon -Wno-error \
  -Wno-error=implicit-function-declaration -Wno-error=implicit-int \
  -Wno-error=incompatible-pointer-types -Wno-error=declaration-missing-parameter-type \
  -Wno-error=return-mismatch -Uunix -Ulinux -std=gnu17"
# Pure-C dirs first (gnu17 keeps their K&R idioms compiling):
for d in Rogomatic RogueVersions/Rogue_3_6_3 RogueVersions/Rogue_5_2_1 \
         RogueVersions/Rogue_5_3 RogueVersions/Rogue_5_4_2; do
  make -C $d clean && make -C $d CFLAGS="$CF"
done
# Then the top-level build (C++ dirs + Qt app, no -std override):
make CFLAGS="-Wall -pedantic -shared -fPIC -fvisibility=hidden -Wno-error -Uunix -Ulinux"
```

Result: `../build/release/rogue-collection`. Needs a real display — it
crashes headless (`primaryScreen()` null), which is an upstream bug, not a
build problem.
