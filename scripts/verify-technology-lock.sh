#!/usr/bin/env bash
# Audit tracked source against the closed technology lock (spec 3.x).
set -euo pipefail
cd "$(dirname "$0")/.."
FAIL=0
# forbidden extensions
BAD_EXT=$(git ls-files | grep -E '\.(go|rs|java|cs|rb|php|swift|kt)$' || true)
[ -n "$BAD_EXT" ] && { echo "forbidden extensions: $BAD_EXT"; FAIL=1; }
# forbidden imports in python
BAD_IMP=$(git ls-files '*.py' | xargs grep -lE 'import (sqlalchemy|django|flask|pymongo|elasticsearch|kafka|tensorflow|torch)' 2>/dev/null || true)
[ -n "$BAD_IMP" ] && { echo "forbidden python imports: $BAD_IMP"; FAIL=1; }
# forbidden npm deps
for pkg in $(find . -name package.json -not -path '*/node_modules/*' -not -path './apps/web/*'); do
  BAD=$(python3 -c "import json;d=json.load(open('$pkg'));deps=list(d.get('dependencies',{}))+list(d.get('devDependencies',{}));bad=[p for p in deps if p not in ('express',)];print(' '.join(bad))" 2>/dev/null || true)
  [ -n "$BAD" ] && { echo "unexpected dep in $pkg: $BAD"; FAIL=1; }
done
# docker socket never mounted in compose for api/web/worker
if grep -A3 'services:' docker-compose.yml | grep -q 'docker.sock'; then echo "docker.sock mounted in compose services"; FAIL=1; fi
grep -q '/var/run/docker.sock' docker-compose.yml && { echo "docker.sock in compose"; FAIL=1; }
# no tracked .env or tokens
[ -f .env ] && { echo ".env tracked"; FAIL=1; }
git ls-files | grep -E '^\.env$' && { echo ".env tracked"; FAIL=1; }
LEAK=$(git ls-files | xargs grep -lE 'ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}' 2>/dev/null || true)
[ -n "$LEAK" ] && { echo "token leak in: $LEAK"; FAIL=1; }
[ "$FAIL" = "0" ] && echo "technology lock: OK" || exit 1
