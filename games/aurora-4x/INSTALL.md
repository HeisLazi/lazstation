# Aurora 4X on LAZSTATION (Wine)

Aurora is a free Windows game. It is not in any package manager, so the
install is manual — once. After that, the console boots it like anything.

## Steps

1. Grab the **full install** plus the **latest patch** from the official
   Aurora forums: <https://aurora2.pentarch.org> → Downloads.
   (If the forum is down, try again later — the files only live there.)
2. Unzip into `~/Games/aurora4x/` so that `~/Games/aurora4x/Aurora.exe`
   exists, then apply the patch over the same folder.
3. First boot needs a display (Aurora is a GUI game). Either play from a
   graphical session, or install `xorg-server-xvfb` for headless checks.
4. Wine setup the wrapper handles: it uses `~/Games/aurora4x/prefix` as
   `WINEPREFIX`. If fonts look broken: `winetricks corefonts`.

## Verify

```bash
ls ~/Games/aurora4x/Aurora.exe
lazstation play aurora-4x
```
