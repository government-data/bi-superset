#!/bin/bash
# The repository's checks, run by CI and before every commit (AGENTS.md):
# shell scripts with shellcheck, Python files compiled, YAML parsed, and
# the size limits (a Python file at most 800 lines, a shell script 600, a
# function 100). Needs bash, python3, yq and shellcheck (CI installs it;
# locally it is skipped with a note when absent).
set -u
cd "$(dirname "$0")/.."
FAILED=0
fail() { printf '[FAIL] %s\n' "$*"; FAILED=1; }

mapfile -t SH < <(git ls-files '*.sh')
mapfile -t PY < <(git ls-files '*.py')
mapfile -t YML < <(git ls-files '*.yml' '*.yaml')

if command -v shellcheck >/dev/null; then
  [ "${#SH[@]}" -eq 0 ] || shellcheck -x "${SH[@]}" || fail "shellcheck"
else
  echo "[NOTE] shellcheck not installed: skipped"
fi
for f in "${PY[@]}"; do
  python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])' "$f" || fail "$f does not parse"
done
for f in "${YML[@]}"; do
  yq -e '.' "$f" >/dev/null || fail "$f is not valid YAML"
done

# Sizes: files, then Python functions (a def to the next line at its indent or less).
for f in "${PY[@]}"; do
  n=$(wc -l <"$f"); [ "$n" -le 800 ] || fail "$f: $n lines (hard limit 800)"
  python3 - "$f" <<'PY' || fail "$f: a function over 100 lines"
import ast, sys
tree = ast.parse(open(sys.argv[1]).read())
long = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.end_lineno - n.lineno + 1 > 100]
sys.exit(1 if long else 0)
PY
done
for f in "${SH[@]}"; do
  n=$(wc -l <"$f"); [ "$n" -le 600 ] || fail "$f: $n lines (hard limit 600)"
done

[ "$FAILED" = 0 ] && echo "checks: OK" || exit 1
