#!/usr/bin/env bash
# Smoke test: render every game and the console, check the bezel survives,
# and re-run the headless logic checks. Run after any change to sdk/ or
# termstation/, which every game depends on.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
fail=0
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=1; }

echo "manifests"
if ./bin/lazstation doctor >/tmp/smoke_doctor.txt 2>&1; then pass "doctor"; else bad "doctor"; cat /tmp/smoke_doctor.txt; fi

render() { # slug cols rows keys
  local slug=$1 cols=$2 rows=$3 keys=$4
  ( cd "games/$slug" && TERMSTATION=1 TERMSTATION_NAME="$slug" \
      TERMSTATION_SAVE_DIR="/tmp/smoke_$slug" PYTHONPATH="$ROOT/sdk" \
      timeout 25 python3 "$ROOT/tools/ptytest.py" "$cols" "$rows" "$keys" 2>&1 )
}

echo "console"
for size in "80 24" "110 30"; do
  set -- $size
  out=$(cd "$ROOT" && timeout 25 python3 tools/ptytest.py "$1" "$2" "" 2>&1 <<PY
PY
)
  out=$(cd "$ROOT" && timeout 25 python3 - "$1" "$2" <<'PY' 2>&1
import sys; sys.path.insert(0,"tools")
from ptytest import run; from vt import render
c,r = int(sys.argv[1]), int(sys.argv[2])
print(render(run(["python3","-m","termstation"], c, r, [], settle=1.0), c, r))
PY
)
  if grep -q "╔" <<<"$out" && grep -q "╚" <<<"$out" && grep -q "LAZSTATION" <<<"$out"; then
    pass "console renders at $1x$2"
  else bad "console at $1x$2"; fi
done

echo "games"
for dir in games/*/; do
  slug=$(basename "$dir")
  [ -f "$dir/game.toml" ] || continue
  out=$(render "$slug" 80 24 $'\n\n1\n')
  if grep -q "╔" <<<"$out" && grep -q "╚" <<<"$out"; then
    pass "$slug renders with its frame intact"
  else bad "$slug frame missing"; fi
done

echo "logic"
if (cd games/beastling && python3 - <<'PY' >/dev/null 2>&1
import sys,types,random
sys.path.insert(0,"."); sys.path.insert(0,"../../sdk")
src=open("main.py").read().split("# ---------------------------------------------------------------- presentation")[0]
m=types.ModuleType("b"); exec(compile(src,"m","exec"),m.__dict__)
random.seed(1)
a,b=m.Beast("cindermole",10),m.Beast("sproutling",10)
se=sum(m.damage(a,b,"Cinder Spit")[0] for _ in range(50))/50
rs=sum(m.damage(a,b,"Scratch")[0] for _ in range(50))/50
assert se > rs*2, (se,rs)
PY
); then pass "beastling type effectiveness"; else bad "beastling type effectiveness"; fi

if (cd games/ashclimb && python3 - <<'PY' >/dev/null 2>&1
import sys,os,random,importlib.util
sys.path.insert(0,"."); sys.path.insert(0,"../../sdk")
os.environ["TERMSTATION_SAVE_DIR"]="/tmp/smoke_ac"
import termstation_sdk as ts
for f in ("tv_print","tv_clear","tv_pause","tv"): setattr(ts,f,lambda *a,**k: None)
ts.title=lambda t,**k:t; ts.box=lambda l,**k:""; ts.rule=lambda *a,**k:""
ts.color=lambda t,*a,**k:t; ts.size=lambda:(76,20)
spec=importlib.util.spec_from_file_location("ac","main.py")
ac=importlib.util.module_from_spec(spec); spec.loader.exec_module(ac)
random.seed(5)
run=ac.Run({}); c=ac.Combat(run,[ac.Enemy("Ash Rat")],"t")
def pick(p,lo=0,hi=0,d=None):
    if "which" in p: return 1
    for i,n in enumerate(c.hand,1):
        if ac.CARDS[n]["cost"]<=c.energy: return i
    return 0
ts.ask_int=pick
c.fight()
total=len(c.draw_pile)+len(c.hand)+len(c.discard)+len(c.exhausted)
assert total==len(run.deck), (total,len(run.deck))
PY
); then pass "ashclimb card conservation"; else bad "ashclimb card conservation"; fi

echo
[ $fail -eq 0 ] && echo "  all good" || echo "  FAILURES above"
exit $fail
