#!/usr/bin/env bash
# Publie la base construite en release GitHub, pour l'installer sans reconstruire
# (`./scripts/setup.sh` ou `uv run edu-kb download`).
#
#   ./scripts/setup.sh --build && ./scripts/publier-base.sh
#
# La release pointe sur le commit courant, qui doit être dans origin/main et sans modification
# locale : la base correspond au code qui la lit, et la release ne se détache pas (GitHub la
# repasse en brouillon si son tag est supprimé ou déplacé, par exemple après la réécriture de
# la branche qui la portait).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${EDU_KB_DB:-${EDU_KB_HOME:-$HOME/.edu-kb}/kb.sqlite}"

ok() { printf '  ✓ %s\n' "$1"; }
die() { printf '\n✗ %s\n' "$1" >&2; exit 1; }

command -v gh >/dev/null || die "gh (GitHub CLI) est requis : brew install gh"
[[ -f "$DB" ]] || die "Aucune base à publier : $DB (lance ./scripts/setup.sh --build)"
cd "$PROJECT_DIR"
[[ -z "$(git status --porcelain)" ]] || die "Modifications non commitées : la release doit pointer sur le code qui a construit la base"
COMMIT="$(git rev-parse HEAD)"
git fetch --quiet origin main
git merge-base --is-ancestor "$COMMIT" origin/main \
  || die "Le commit ${COMMIT:0:7} n'est pas dans origin/main : fusionne et pousse d'abord, puis publie depuis main"

OUT_DIR="$(mktemp -d)"
trap 'rm -rf "$OUT_DIR"' EXIT
# Copie compacte et autonome (sans journal WAL à côté), lisible par n'importe quel SQLite.
BUILT_AT="$(uv run --quiet python - "$DB" "$OUT_DIR/kb.sqlite" <<'PY'
import sqlite3, sys
from contextlib import closing

src, out = sys.argv[1], sys.argv[2]
with closing(sqlite3.connect(src)) as con:
    con.execute("VACUUM INTO ?", (out,))
with closing(sqlite3.connect(out)) as con:
    con.execute("PRAGMA journal_mode = DELETE")
    built_at = con.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
if built_at is None:
    sys.exit("la base n'a pas de date de construction : reconstruis-la")
print(built_at[0])
PY
)"
ok "base construite le $BUILT_AT ($(du -h "$OUT_DIR/kb.sqlite" | cut -f1))"

TAG="base-$(date -u +%Y%m%d-%H%M)"
NOTES="Graphe des programmes construit le ${BUILT_AT} à partir du commit ${COMMIT:0:7}.

Installation sans reconstruire : \`./scripts/setup.sh\`, ou \`uv run edu-kb download\` dans un clone à jour."
gh release create "$TAG" "$OUT_DIR/kb.sqlite" --target "$COMMIT" --title "Base du ${BUILT_AT:0:10}" --notes "$NOTES" --latest
ok "release $TAG publiée : $(gh repo view --json url -q .url)/releases/latest/download/kb.sqlite"
