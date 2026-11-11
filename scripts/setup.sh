#!/usr/bin/env bash
# Installe edu-kb, récupère le graphe des programmes et branche le serveur MCP sur Claude.
#
#   ./scripts/setup.sh                      # télécharge la base publiée sur GitHub (rien à reconstruire)
#   ./scripts/setup.sh --build              # reconstruit la base à partir des PDF de Programmes/
#   EDU_KB_PROGRAMMES=~/Docs/BO ./scripts/setup.sh --build
#
# Relançable sans risque : chaque étape déjà faite est sautée ; la base est retéléchargée ou
# reconstruite (quelques secondes, l'OCR et les embeddings sont mis en cache).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROGRAMMES_DIR="${EDU_KB_PROGRAMMES:-$PROJECT_DIR/Programmes}"
MODEL="${EDU_KB_EMBED_MODEL:-bge-m3}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
DESKTOP_CONFIG="${HOME}/Library/Application Support/Claude/claude_desktop_config.json"

step() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }
ok() { printf '  ✓ %s\n' "$1"; }
warn() { printf '  ⚠ %s\n' "$1"; }
die() { printf '\n✗ %s\n' "$1" >&2; exit 1; }

BUILD=false
case "${1:-}" in
  "") ;;
  --build) BUILD=true ;;
  *) die "Option inconnue : $1 (seule option : --build)" ;;
esac

if $BUILD; then
  [[ -d "$PROGRAMMES_DIR" ]] || die "Dossier introuvable : $PROGRAMMES_DIR (dépose les PDF des programmes dans $PROJECT_DIR/Programmes)"
fi

# ------------------------------------------------------------------------ outils
step "Outils"
need_brew() { command -v brew >/dev/null || die "Homebrew est requis pour installer $1 : https://brew.sh"; }
TOOLS=(uv ollama)
if $BUILD; then TOOLS+=(ocrmypdf); fi
for tool in "${TOOLS[@]}"; do
  if command -v "$tool" >/dev/null; then
    ok "$tool présent"
  else
    need_brew "$tool"
    brew install "$tool"
    ok "$tool installé"
  fi
done
if $BUILD; then
  if command -v tesseract >/dev/null && tesseract --list-langs 2>/dev/null | grep -qx fra; then
    ok "tesseract (français) présent"
  else
    need_brew tesseract-lang
    brew install tesseract-lang
    ok "tesseract-lang installé (OCR des programmes de sciences, publiés scannés)"
  fi
fi
UV="$(command -v uv)"

# ------------------------------------------------------------------------ Ollama
step "Ollama et modèle d'embedding ($MODEL)"
ollama_up() { curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; }
if ! ollama_up; then
  if command -v brew >/dev/null && brew list ollama >/dev/null 2>&1; then
    brew services start ollama >/dev/null
  else
    (ollama serve >/dev/null 2>&1 &)
  fi
  for _ in $(seq 1 30); do ollama_up && break; sleep 1; done
fi
EMBED_FLAG=""
if ollama_up; then
  ok "Ollama répond sur $OLLAMA_URL"
  if ollama list | awk 'NR > 1 { print $1 }' | grep -Eq "^${MODEL}(:|$)"; then
    ok "$MODEL déjà téléchargé"
  else
    ollama pull "$MODEL"
    ok "$MODEL téléchargé"
  fi
elif $BUILD; then
  warn "Ollama ne répond pas : graphe construit en plein texte seulement."
  EMBED_FLAG="--no-embed"
else
  warn "Ollama ne répond pas : la recherche sera en plein texte seulement tant qu'il ne tourne pas."
fi

# ------------------------------------------------------------------------ projet
step "Dépendances du projet"
"$UV" sync --quiet --project "$PROJECT_DIR"
ok "environnement Python prêt"

if $BUILD; then
  step "Construction du graphe ($PROGRAMMES_DIR)"
  EDU_KB_PROGRAMMES="$PROGRAMMES_DIR" "$UV" run --quiet --project "$PROJECT_DIR" edu-kb build $EMBED_FLAG
else
  step "Téléchargement du graphe"
  "$UV" run --quiet --project "$PROJECT_DIR" edu-kb download
fi

# ------------------------------------------------------------------ branchement
step "Branchement du serveur MCP"
if command -v claude >/dev/null; then
  if claude mcp get edu-kb >/dev/null 2>&1; then
    ok "Claude Code : déjà configuré"
  else
    claude mcp add --scope user edu-kb -- "$UV" --directory "$PROJECT_DIR" run edu-kb serve >/dev/null
    ok "Claude Code : edu-kb ajouté"
  fi
else
  warn "Claude Code absent : étape ignorée"
fi

if [[ -d "$(dirname "$DESKTOP_CONFIG")" ]]; then
  result="$("$UV" run --quiet --project "$PROJECT_DIR" python - "$DESKTOP_CONFIG" "$UV" "$PROJECT_DIR" <<'PY'
import json, shutil, sys
from pathlib import Path

config, uv, project = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
data = json.loads(config.read_text(encoding="utf-8")) if config.exists() and config.read_text().strip() else {}
entry = {"command": uv, "args": ["--directory", project, "run", "edu-kb", "serve"]}
servers = data.setdefault("mcpServers", {})
if servers.get("edu-kb") == entry:
    print("unchanged")
else:
    if config.exists():
        shutil.copy2(config, config.with_name(config.name + ".bak"))
    servers["edu-kb"] = entry
    config.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("updated")
PY
)"
  if [[ "$result" == "updated" ]]; then
    ok "Claude Desktop : edu-kb ajouté (sauvegarde en .bak) — redémarre l'application"
  else
    ok "Claude Desktop : déjà configuré"
  fi
else
  warn "Claude Desktop absent : étape ignorée"
fi

# ---------------------------------------------------------------------- bilan
step "Bilan"
"$UV" run --quiet --project "$PROJECT_DIR" edu-kb status
printf '\nAprès un nouveau programme (PDF + bloc dans sources.toml) : ./scripts/setup.sh --build\n'
