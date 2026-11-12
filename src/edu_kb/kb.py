"""Base de connaissance : graphe des programmes dans SQLite, recherche hybride et requêtes."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from .embed import Embedder, EmbeddingUnavailable
from .graph import COMPETENCE_FIELDS, FIELD_LABELS, LEVELS, Graph, slug

RRF_K = 60
CANDIDATES = 80
# Écart de similarité maximal avec le meilleur résultat sémantique pour qu'un résultat reste proposé.
SEMANTIC_MARGIN = 0.06
# Similarité minimale du meilleur résultat quand aucun mot de la requête n'apparaît dans le programme.
SEMANTIC_FLOOR = 0.5
# Résultats purement lexicaux gardés quand la recherche sémantique est disponible (mots rares, sigles).
LEXICAL_ONLY_KEPT = 3
EMBEDDED_KINDS = ("item", "theme", "objectif", "competence", "seance", "sequence_guide")
GUIDE_KINDS = ("seance", "sequence_guide")
# Similarité minimale entre une séance d'un guide et un objectif du programme pour les relier par le sens,
# et nombre d'objectifs gardés par séance.
# Ce sont des propositions : un mot commun suffit parfois (« suite gestuelle » / « suite des nombres »).
GUIDE_LINK_MIN_SIMILARITY = 0.6
GUIDE_LINK_TOP = 3
GUIDE_LINK_MARGIN = 0.04  # écart maximal avec le meilleur objectif de la séance
# Similarité minimale entre un item et le thème qui porte une notion pour garder le lien « mentionne »
# (calibrée sur la base : sous 0,45 presque tout est homonyme ou mot courant, au-dessus de 0,5 presque tout est pertinent).
MENTION_MIN_SIMILARITY = 0.5

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS nodes(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    discipline TEXT NOT NULL DEFAULT '',
    levels TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    page INTEGER,
    position INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind, discipline);
CREATE TABLE IF NOT EXISTS edges(
    src TEXT NOT NULL,
    rel TEXT NOT NULL,
    dst TEXT NOT NULL,
    data TEXT,
    PRIMARY KEY (src, rel, dst)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, rel);
CREATE TABLE IF NOT EXISTS embeddings(
    hash TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    vector BLOB NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    title, text, discipline, kind UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

STOPWORDS = set(
    """au aux avec ce ces comme comment dans de des du elle en est et il ils je la le les leur mais ne
    ou où par pas plus pour quand que qui quoi sa se ses son sur un une être d l qu s c n""".split()
)


def school_year(value: str | int | None = None, today: date | None = None) -> int:
    """Année de rentrée : « 2026-2027 » → 2026 ; 2026 → 2026 ; None → année scolaire en cours."""
    if value is None or value == "":
        today = today or date.today()
        return today.year if today.month >= 8 else today.year - 1
    if isinstance(value, int):
        return value
    m = re.match(r"\s*(\d{4})", str(value))
    if not m:
        raise ValueError(f"Année scolaire illisible : {value!r} (attendu : 2026 ou 2026-2027)")
    return int(m.group(1))


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_level(level: str | None) -> str | None:
    if not level:
        return None
    up = level.strip().upper().replace("È", "E")
    aliases = {"6E": "6e", "SIXIEME": "6e", "6EME": "6e"}
    up = aliases.get(up, up)
    if up not in LEVELS:
        raise ValueError(f"Niveau inconnu : {level!r} (attendu : {', '.join(LEVELS)})")
    return up


def fts_phrase(query: str) -> str | None:
    """Requête sur l'expression entière (« moyen age »), pour une requête de plusieurs mots."""
    tokens = [t for t in norm(query).split() if t not in STOPWORDS and len(t) > 1]
    return '"' + " ".join(tokens) + '"' if len(tokens) > 1 else None


def fts_query(query: str) -> str | None:
    """Mots de la requête, avec une troncature simple pour le pluriel et les flexions françaises."""
    tokens = [t for t in norm(query).split() if t not in STOPWORDS and len(t) > 1]
    if not tokens:
        return None
    terms = []
    for t in dict.fromkeys(tokens):
        if len(t) > 4:
            stem = re.sub(r"(es|s|x|e)$", "", t)
            terms.append(f'"{stem}"*')
        else:
            terms.append(f'"{t}"')
    if len(tokens) > 1:
        terms.insert(0, '"' + " ".join(tokens) + '"')
    return " OR ".join(terms)


@dataclass
class Hit:
    id: str
    kind: str
    title: str
    discipline: str
    levels: list[str]
    context: str
    source_id: str
    page: int | None
    score: float


@dataclass
class SearchResult:
    mode: str
    hits: list[Hit] = field(default_factory=list)
    warning: str | None = None


def _text_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


class KnowledgeBase:
    def __init__(self, db_path: Path, embedder: Embedder | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self._lock = threading.Lock()
        self._vectors: tuple[list[str], np.ndarray] | None = None
        self._eligible_cache: dict = {}
        self._applies: dict[str, dict[str, dict]] | None = None
        with self._conn() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode = WAL")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------ écriture
    def replace_graph(self, graph: Graph) -> None:
        """Remplace tout le graphe (la reconstruction complète prend quelques secondes)."""
        with self._conn() as con:
            con.execute("DELETE FROM nodes")
            con.execute("DELETE FROM edges")
            con.execute("DELETE FROM nodes_fts")
            for n in graph.nodes.values():
                cur = con.execute(
                    "INSERT INTO nodes(id, kind, title, text, discipline, levels, source_id, page, position, data)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (n.id, n.kind, n.title, n.text, n.discipline, "," + ",".join(n.levels) + "," if n.levels else "",
                     n.source_id, n.page, n.position, json.dumps(n.data, ensure_ascii=False)),
                )
                con.execute(
                    "INSERT INTO nodes_fts(rowid, title, text, discipline, kind) VALUES (?,?,?,?,?)",
                    (cur.lastrowid, n.title, n.text, n.discipline, n.kind),
                )
            con.executemany(
                "INSERT INTO edges(src, rel, dst, data) VALUES (?,?,?,?)",
                [(s, r, d, json.dumps(graph.edge_data[(s, r, d)], ensure_ascii=False) if (s, r, d) in graph.edge_data else None)
                 for s, r, d in graph.edges],
            )
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('built_at', ?)", (datetime.now(timezone.utc).isoformat(),))
            con.execute("DELETE FROM meta WHERE key = 'mentions_filtrees'")  # liens redevenus lexicaux
        self._vectors = None
        self._eligible_cache = {}
        self._applies = None

    def embed_missing(self, progress=None) -> int:
        """Calcule les embeddings des nœuds qui n'en ont pas encore (cache par texte)."""
        if self.embedder is None:
            raise EmbeddingUnavailable("aucun modèle d'embedding configuré")
        model = self.embedder.model
        with self._conn() as con:
            rows = con.execute(
                f"SELECT id, kind, title, text, discipline, levels FROM nodes WHERE kind IN ({','.join('?' * len(EMBEDDED_KINDS))})",
                EMBEDDED_KINDS,
            ).fetchall()
            known = {r["hash"] for r in con.execute("SELECT hash FROM embeddings WHERE model = ?", (model,))}
        todo = []
        for r in rows:
            text = self._embed_text(r)
            h = _text_hash(model, text)
            if h not in known:
                todo.append((h, text))
                known.add(h)
        done = 0
        for i in range(0, len(todo), 64):
            batch = todo[i : i + 64]
            vectors = self.embedder.embed([t for _, t in batch])
            with self._conn() as con:
                con.executemany(
                    "INSERT OR REPLACE INTO embeddings(hash, model, vector) VALUES (?,?,?)",
                    [(h, model, v.astype(np.float32).tobytes()) for (h, _), v in zip(batch, vectors)],
                )
            done += len(batch)
            if progress:
                progress(done, len(todo))
        with self._conn() as con:
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('embed_model', ?)", (model,))
        self._vectors = None
        self._eligible_cache = {}
        return done

    def prune_mentions(self, threshold: float = MENTION_MIN_SIMILARITY) -> tuple[int, int]:
        """Garde les liens « mentionne » qui ont du sens : l'item doit ressembler à un thème qui porte
        la notion en mot-clé. Écarte les homonymes (« égalité » en maths, « carte » d'anniversaire)
        et les mots trop courants (« jour », « présent »). Renvoie (gardés, retirés)."""
        loaded = self._load_vectors()
        if not loaded or not loaded[0]:
            raise EmbeddingUnavailable("aucun embedding : les liens entre disciplines restent lexicaux")
        ids, matrix = loaded
        index = {nid: i for i, (nid, _) in enumerate(ids)}
        with self._conn() as con:
            themes: dict[str, list[str]] = {}
            for r in con.execute("SELECT src, dst FROM edges WHERE rel = 'mot_cle'"):
                themes.setdefault(r["dst"], []).append(r["src"])
            mentions = con.execute("SELECT src, dst FROM edges WHERE rel = 'mentionne'").fetchall()
            drop = []
            for r in mentions:
                sims = [float(matrix[index[r["src"]]] @ matrix[index[t]])
                        for t in themes.get(r["dst"], []) if r["src"] in index and t in index]
                if not sims or max(sims) < threshold:
                    drop.append((r["src"], r["dst"]))
            con.executemany("DELETE FROM edges WHERE src = ? AND rel = 'mentionne' AND dst = ?", drop)
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('mentions_filtrees', ?)", (str(threshold),))
        return len(mentions) - len(drop), len(drop)

    def import_embeddings(self, other_db: Path) -> int:
        """Reprend les vecteurs d'une autre base (cache indexé par le texte), ouverte en lecture seule :
        rien n'est recalculé pour les nœuds qu'elles ont en commun. Renvoie le nombre de vecteurs ajoutés."""
        other_db = Path(other_db)
        if not other_db.exists() or other_db.resolve() == self.db_path.resolve():
            return 0
        # immutable : aucune écriture, pas même les fichiers -wal et -shm à côté de l'autre base
        with closing(sqlite3.connect(f"{other_db.resolve().as_uri()}?mode=ro&immutable=1", uri=True)) as src:
            rows = src.execute("SELECT hash, model, vector FROM embeddings").fetchall()
        with self._conn() as con:
            before = con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            con.executemany("INSERT OR IGNORE INTO embeddings(hash, model, vector) VALUES (?,?,?)", rows)
            after = con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        self._vectors = None
        return after - before

    def link_guides(self, threshold: float = GUIDE_LINK_MIN_SIMILARITY, top: int = GUIDE_LINK_TOP) -> int:
        """Relie chaque séance d'un guide aux objectifs du programme qu'elle travaille, par le sens
        (plus proches voisins parmi les objectifs du même niveau et de la même discipline, dans le
        programme sur lequel s'appuie le guide). Ce sont des propositions, à distinguer des objectifs
        que le guide cite lui-même. Renvoie le nombre de liens créés."""
        loaded = self._load_vectors()
        if not loaded or not loaded[0]:
            raise EmbeddingUnavailable("aucun embedding : les séances des guides ne sont pas reliées au programme")
        ids, matrix = loaded
        index = {nid: i for i, (nid, _) in enumerate(ids)}
        links = []
        with self._conn() as con:
            con.execute("DELETE FROM edges WHERE rel = 'travaille' AND data LIKE '%rapprochement par le sens%'")
            guides = [self._row(r) for r in con.execute("SELECT * FROM nodes WHERE kind = 'guide'")]
            for guide in guides:
                year = guide["data"].get("programme")
                targets = [self._row(r) for r in con.execute(
                    "SELECT * FROM nodes WHERE kind = 'objectif' AND discipline = ?", (guide["discipline"],))]
                targets = [t for t in targets if t["id"] in index and any(
                    lv in t["levels"] and (year is None or self.applicable(t["source_id"], lv, year)) for lv in guide["levels"])]
                seances = [r["id"] for r in con.execute(
                    "SELECT id, data FROM nodes WHERE kind = 'seance' AND source_id = ?", (guide["source_id"],))
                    if r["id"] in index and json.loads(r["data"]).get("type") not in ("introduction",)]
                if not targets or not seances:
                    continue
                sims = matrix[[index[s] for s in seances]] @ matrix[[index[t["id"]] for t in targets]].T
                for row, sid in zip(sims, seances):
                    best = float(row.max())
                    for k in np.argsort(-row)[:top]:
                        if row[k] >= threshold and row[k] >= best - GUIDE_LINK_MARGIN:
                            links.append((sid, "travaille", targets[k]["id"], json.dumps(
                                {"origine": "rapprochement par le sens", "similarite": round(float(row[k]), 3)}, ensure_ascii=False)))
            con.executemany("INSERT OR REPLACE INTO edges(src, rel, dst, data) VALUES (?,?,?,?)", links)
        return len(links)

    @staticmethod
    def _embed_text(row: sqlite3.Row) -> str:
        levels = row["levels"].strip(",").replace(",", ", ")
        return f"{row['discipline']} · {levels} · {row['title']}\n{row['text']}"[:2000]

    # ------------------------------------------------------------------ lecture de base
    def stats(self) -> dict:
        with self._conn() as con:
            kinds = {r["kind"]: r["n"] for r in con.execute("SELECT kind, COUNT(*) n FROM nodes GROUP BY kind ORDER BY n DESC")}
            rels = {r["rel"]: r["n"] for r in con.execute("SELECT rel, COUNT(*) n FROM edges GROUP BY rel ORDER BY n DESC")}
            meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
            model = meta.get("embed_model")
            vectors = con.execute("SELECT COUNT(*) FROM embeddings WHERE model = ?", (model,)).fetchone()[0] if model else 0
        return {"noeuds": kinds, "aretes": rels, "construit_le": meta.get("built_at"), "modele": model, "vecteurs": vectors,
                "mentions_filtrees": meta.get("mentions_filtrees")}

    def node(self, node_id: str) -> dict | None:
        with self._conn() as con:
            row = con.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["levels"] = [lv for lv in d["levels"].split(",") if lv]
        d["data"] = json.loads(d["data"])
        return d

    def neighbours(self, node_id: str, rel: str, reverse: bool = False) -> list[dict]:
        """Voisins par une relation : cibles des arêtes sortantes, ou sources des entrantes (reverse)."""
        a, b = ("src", "dst") if reverse else ("dst", "src")
        with self._conn() as con:
            rows = con.execute(
                f"SELECT n.*, e.data AS edge_data FROM edges e JOIN nodes n ON n.id = e.{a} WHERE e.{b} = ? AND e.rel = ? ORDER BY n.position",
                (node_id, rel),
            ).fetchall()
        out = []
        for r in rows:
            d = self._row(r)
            d["edge_data"] = json.loads(r["edge_data"]) if r["edge_data"] else None
            out.append(d)
        return out

    def sources(self) -> list[dict]:
        with self._conn() as con:
            return [self._row(r) for r in con.execute("SELECT * FROM nodes WHERE kind = 'source' ORDER BY position, id")]

    def applies_map(self) -> dict[str, dict[str, dict]]:
        if self._applies is None:
            self._applies = {s["source_id"]: s["data"].get("application", {}) for s in self.sources()}
        return self._applies

    def applicable(self, source_id: str, level: str, year: int) -> bool:
        rule = self.applies_map().get(source_id, {}).get(level)
        if rule is None:
            return False
        return rule["depuis"] <= year and (rule["jusqu_a"] is None or year < rule["jusqu_a"])

    def node_applicable(self, node: dict, level: str | None, year: int | None) -> bool:
        if year is None:
            return level is None or level in node["levels"]
        levels = [level] if level else node["levels"]
        return any(lv in node["levels"] and self.applicable(node["source_id"], lv, year) for lv in levels)

    def disciplines(self) -> list[str]:
        with self._conn() as con:
            return [r["title"] for r in con.execute("SELECT title FROM nodes WHERE kind = 'discipline' ORDER BY title")]

    def resolve_discipline(self, name: str | None) -> str | None:
        if not name:
            return None
        wanted = norm(name)
        aliases = {"maths": "mathematiques", "math": "mathematiques", "hg": "histoire geographie", "histoire": "histoire geographie",
                   "geographie": "histoire geographie", "sciences": "sciences et technologie", "qlm": "questionner le monde",
                   "anglais": "langues vivantes", "lv": "langues vivantes", "lve": "langues vivantes", "musique": "education musicale",
                   "arts": "arts plastiques", "art": "arts plastiques", "education civique": "emc", "enseignement moral et civique": "emc",
                   "sport": "eps", "education physique et sportive": "eps", "hda": "histoire des arts"}
        wanted = aliases.get(wanted, wanted)
        for d in self.disciplines():
            if norm(d) == wanted:
                return d
        for d in self.disciplines():
            if wanted in norm(d):
                return d
        raise ValueError(f"Discipline inconnue : {name!r} (disponibles : {', '.join(self.disciplines())})")

    # ------------------------------------------------------------------ recherche
    def search(self, query: str, level: str | None = None, discipline: str | None = None, year: int | None = None,
               kinds: tuple[str, ...] = ("item", "theme", "objectif"), limit: int = 10,
               margin: float = SEMANTIC_MARGIN) -> SearchResult:
        level = normalize_level(level)
        discipline = self.resolve_discipline(discipline)
        allowed = self._eligible(kinds, level, discipline, year)
        lexical = self._lexical(query, kinds, allowed)
        semantic, warning, best_similarity = self._semantic(query, kinds, allowed, margin)
        if semantic and best_similarity < SEMANTIC_FLOOR:
            # le sens ne trouve rien d'assez proche : seuls comptent les mots de la requête, s'il y en a
            if not lexical:
                return SearchResult("hybride", [], f"aucun passage du programme n'est assez proche de « {query} »")
            semantic = []
        mode = "hybride" if semantic else "plein texte"
        scores: dict[str, float] = {}
        for ranking in (lexical, semantic):
            for rank, nid in enumerate(ranking):
                scores[nid] = scores.get(nid, 0.0) + 1.0 / (RRF_K + rank + 1)
        if semantic:
            # la sémantique juge la pertinence ; un mot courant (« moyen », « lire ») ne suffit pas à lui seul
            in_semantic = set(semantic)
            top_lexical = set(lexical[:LEXICAL_ONLY_KEPT])
            scores = {n: v for n, v in scores.items() if n in in_semantic or n in top_lexical}
        hits: list[Hit] = []
        seen_items: set[str] = set()
        with self._conn() as con:
            for nid, score in sorted(scores.items(), key=lambda kv: -kv[1]):
                # un seul résultat par item : l'item lui-même ou son objectif le mieux classé
                key = re.sub(r"/o\d+$", "", nid)
                if key in seen_items:
                    continue
                if key != nid and (key in scores or allowed is None or key in allowed):
                    nid = key  # un objectif classé avant son item : on propose l'item, qui porte l'objectif
                row = con.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
                if row is None:
                    continue
                node = self._row(row)
                seen_items.add(key)
                context = node["data"].get("contexte") or " › ".join(node["data"].get("chemin", []))
                hits.append(Hit(nid, node["kind"], node["title"], node["discipline"], node["levels"], context,
                                node["source_id"], node["page"], score))
                if len(hits) >= limit:
                    break
        return SearchResult(mode, hits, warning)

    def _eligible(self, kinds: tuple[str, ...], level: str | None, discipline: str | None, year: int | None) -> set[str] | None:
        """Nœuds qui répondent au niveau, à la discipline et à l'année demandés. Le filtre passe avant le
        classement : sinon les 80 meilleurs candidats viennent d'autres niveaux et ne laissent que du bruit."""
        if not (level or discipline or year):
            return None
        key = (kinds, level, discipline, year)
        if key not in self._eligible_cache:
            with self._conn() as con:
                rows = con.execute(f"SELECT * FROM nodes WHERE kind IN ({','.join('?' * len(kinds))})", kinds).fetchall()
            self._eligible_cache[key] = {
                r["id"] for r in map(self._row, rows)
                if (not discipline or r["discipline"] == discipline) and self.node_applicable(r, level, year)
            }
        return self._eligible_cache[key]

    def _lexical(self, query: str, kinds: tuple[str, ...], allowed: set[str] | None = None) -> list[str]:
        q = fts_query(query)
        if not q:
            return []
        # les mots-clés des thèmes (« caravelle ») sont des nœuds notion : on remonte à leur thème
        searched = kinds + ("notion",) if "theme" in kinds else kinds
        sql = (f"SELECT n.id, n.kind FROM nodes_fts f JOIN nodes n ON n.rowid = f.rowid WHERE nodes_fts MATCH ? "
               f"AND f.kind IN ({','.join('?' * len(searched))}) ORDER BY bm25(nodes_fts, 4.0, 1.0, 0.5) LIMIT ?")

        def run(match: str) -> list[str]:
            with self._conn() as con:
                rows = con.execute(sql, (match, *searched, CANDIDATES * 40)).fetchall()
            ids: list[str] = []
            for r in rows:
                found = [t["id"] for t in self.neighbours(r["id"], "mot_cle", reverse=True)] if r["kind"] == "notion" else [r["id"]]
                ids += [n for n in found if n not in ids and (allowed is None or n in allowed)]
            return ids

        # l'expression entière d'abord (« Moyen Âge ») : si elle existe dans le programme, c'est elle qu'on cherche
        phrase = fts_phrase(query)
        ids = run(phrase) if phrase else []
        ids = ids or run(q)
        return ids[: CANDIDATES * 4]

    def _load_vectors(self) -> tuple[list[str], np.ndarray] | None:
        if self.embedder is None:
            return None
        with self._lock:
            if self._vectors is None:
                model = self.embedder.model
                with self._conn() as con:
                    rows = con.execute(
                        f"SELECT id, kind, title, text, discipline, levels FROM nodes WHERE kind IN ({','.join('?' * len(EMBEDDED_KINDS))})",
                        EMBEDDED_KINDS,
                    ).fetchall()
                    vecs = {r["hash"]: r["vector"] for r in con.execute("SELECT hash, vector FROM embeddings WHERE model = ?", (model,))}
                ids, mats = [], []
                for r in rows:
                    blob = vecs.get(_text_hash(model, self._embed_text(r)))
                    if blob is not None:
                        ids.append((r["id"], r["kind"]))
                        mats.append(np.frombuffer(blob, dtype=np.float32))
                self._vectors = (ids, np.vstack(mats) if mats else np.zeros((0, 1), dtype=np.float32))
            return self._vectors

    def _semantic(self, query: str, kinds: tuple[str, ...], allowed: set[str] | None = None,
                  margin: float = SEMANTIC_MARGIN) -> tuple[list[str], str | None, float]:
        loaded = self._load_vectors()
        if loaded is None:
            return [], None, 0.0
        ids, matrix = loaded
        if not ids:
            return [], "aucun embedding calculé : lance `edu-kb embed` (recherche plein texte seulement)", 0.0
        try:
            q = self.embedder.embed([query])[0]
        except EmbeddingUnavailable as exc:
            return [], f"recherche sémantique indisponible ({exc}) : plein texte seulement", 0.0
        sims = matrix @ q
        order = np.argsort(-sims)
        out = []
        best = None
        for i in order:
            nid, kind = ids[i]
            if kind in kinds and (allowed is None or nid in allowed):
                best = float(sims[i]) if best is None else best
                # sous ce seuil, les résultats ne sont plus que le reste du niveau classé par défaut
                if float(sims[i]) < best - margin:
                    break
                out.append(nid)
            if len(out) >= CANDIDATES:
                break
        return out, None, best or 0.0

    # ------------------------------------------------------------------ requêtes du graphe
    def item_card(self, node_id: str, year: int | None = None) -> dict | None:
        """Tout ce qu'il faut pour préparer une séance à partir d'un item (ou d'un objectif, d'un thème)."""
        node = self.node(node_id)
        if node is None:
            return None
        if node["kind"] == "objectif":
            parent = self.neighbours(node_id, "contient", reverse=True)
            if parent:
                card = self.item_card(parent[0]["id"], year)
                if card:
                    card["objectif_cible"] = node["title"]
                return card
        if node["kind"] in ("theme", "rubrique", "sous_rubrique"):
            return self.theme_card(node_id, year)
        if node["kind"] != "item":
            return {"noeud": node}
        champs = node["data"].get("champs", {})
        source = self.node(f"source:{node['source_id']}")
        themes = [self._theme_summary(t) for t in self.neighbours(node_id, "theme")]
        heading = self.neighbours(node_id, "contient", reverse=True)
        progression = self._progression(heading[0]["id"]) if heading else {}
        notions = self.neighbours(node_id, "mentionne")
        transversal = self._transversal(node, notions, year)
        return {
            "id": node_id,
            "titre": node["title"],
            "discipline": node["discipline"],
            "niveaux": node["levels"],
            "contexte": node["data"].get("contexte"),
            "objectifs": champs.get("objectifs") or champs.get(next(iter(champs), ""), []),
            "champs": {FIELD_LABELS.get(k, k): v for k, v in champs.items()},
            "competences": self.competences(node),
            "themes": themes,
            "periodes_programme": node["data"].get("periodes", []),
            "progression": progression,
            "notions": [n["title"] for n in notions],
            "liens_autres_disciplines": transversal,
            "source": self._source_summary(source, node),
        }

    def competences(self, node: dict) -> dict:
        """Compétences d'un item : ses attendus propres, les compétences travaillées de la discipline
        sur le cycle (quand le programme les définit) et les domaines du socle commun."""
        champs = node["data"].get("champs", {})
        own = {FIELD_LABELS.get(k, k): [re.sub(r"(?:\s+(?:ou|et))+\s*$", "", b["texte"].strip()) for b in champs[k]] for k in COMPETENCE_FIELDS if k in champs}
        disc_id = f"discipline:{slug(node['discipline'])}"
        cycles = {2 if lv in ("CP", "CE1", "CE2") else 3 for lv in node["levels"]}
        travaillees = []
        for c in self.neighbours(disc_id, "competence"):
            if c["data"].get("cycle") in cycles:
                socle = [s["title"].split(" — ")[0] for s in self.neighbours(c["id"], "socle")]
                travaillees.append({"competence": c["title"], "details": c["data"].get("details", []), "socle": socle,
                                    "source": c["source_id"]})
        socle = [{"code": s["data"]["code"], "intitule": s["text"], "origine": (s.get("edge_data") or {}).get("origine", "programme")}
                 for s in self.neighbours(disc_id, "socle")]
        return {"attendus_de_l_item": own, "competences_travaillees_du_cycle": travaillees, "socle_commun": socle}

    def _theme_summary(self, t: dict) -> dict:
        d = t["data"]
        out = {"id": t["id"], "theme": t["title"], "discipline": t["discipline"], "niveaux": t["levels"]}
        for key in ("question", "mots_cles", "periodes_programme", "horaire"):
            if key in d:
                out[key] = d[key]
        return out

    def theme_card(self, node_id: str, year: int | None = None) -> dict | None:
        t = self.node(node_id)
        if t is None:
            return None
        items = [i for i in self.neighbours(node_id, "contient") if i["kind"] == "item"]
        sub = [s for s in self.neighbours(node_id, "contient") if s["kind"] in ("rubrique", "sous_rubrique", "theme")]
        for s in sub:
            items += [i for i in self.neighbours(s["id"], "contient") if i["kind"] == "item"]
        source = self.node(f"source:{t['source_id']}")
        return {
            **self._theme_summary(t),
            "type": t["kind"],
            "texte_du_programme": t["text"],
            "items": [{"id": i["id"], "titre": i["title"], "champs": {FIELD_LABELS.get(k, k): v for k, v in i["data"].get("champs", {}).items()}} for i in items],
            "competences": self.competences(items[0]) if items else None,
            "progression": self._progression(node_id),
            "source": self._source_summary(source, t),
        }

    def _progression(self, heading_id: str) -> dict:
        def chain(start: str, reverse: bool) -> list[dict]:
            out, seen, cur = [], {start}, start
            while True:
                nxt = self.neighbours(cur, "suite", reverse=reverse)
                if not nxt or nxt[0]["id"] in seen:
                    return out
                cur = nxt[0]["id"]
                seen.add(cur)
                items = [i["title"] for i in self.neighbours(cur, "contient") if i["kind"] == "item"]
                out.append({"id": cur, "niveaux": nxt[0]["levels"], "titre": nxt[0]["title"], "items": items[:8]})
        return {"avant": list(reversed(chain(heading_id, True))), "apres": chain(heading_id, False)}

    def _transversal(self, node: dict, notions: list[dict], year: int | None) -> list[dict]:
        out = []
        seen = {node["id"]}
        for notion in notions:
            for other in self.neighbours(notion["id"], "mentionne", reverse=True) + self.neighbours(notion["id"], "mot_cle", reverse=True):
                if other["id"] in seen or other["discipline"] == node["discipline"]:
                    continue
                if not set(other["levels"]) & set(node["levels"]):
                    continue
                if year is not None and not any(self.applicable(other["source_id"], lv, year) for lv in set(other["levels"]) & set(node["levels"])):
                    continue
                seen.add(other["id"])
                out.append({"id": other["id"], "discipline": other["discipline"], "titre": other["title"], "notion": notion["title"]})
        return out[:12]

    def _source_summary(self, source: dict | None, node: dict) -> dict:
        if source is None:
            return {}
        return {"titre": source["title"], "bo": source["data"].get("bo"), "fichier": source["data"].get("fichier"),
                "page": node.get("page"), "application": source["data"].get("application")}

    def themes(self, level: str, discipline: str | None = None, year: int | None = None) -> list[dict]:
        """Thèmes d'un niveau (histoire-géographie, sciences, EMC, arts plastiques, culture littéraire…)."""
        level = normalize_level(level)
        discipline = self.resolve_discipline(discipline)
        out = []
        with self._conn() as con:
            rows = con.execute("SELECT * FROM nodes WHERE kind IN ('theme', 'niveau') AND levels LIKE ? ORDER BY position", (f"%,{level},%",)).fetchall()
        for r in rows:
            n = self._row(r)
            if not n["source_id"]:
                continue
            if discipline and n["discipline"] != discipline:
                continue
            if year is not None and not self.applicable(n["source_id"], level, year):
                continue
            if n["kind"] == "niveau":
                if "theme_annuel" not in n["data"]:
                    continue
                out.append({"id": n["id"], "theme": n["data"]["theme_annuel"], "discipline": n["discipline"], "type": "thème de l'année",
                             "domaine": "", **({"periodes_programme": n["data"]["periodes_programme"]} if "periodes_programme" in n["data"] else {}),
                             "source": n["source_id"]})
                continue
            if not self._has_items(n["id"]):
                continue
            chemin = n["data"].get("chemin", [])
            domaine = chemin[0] if chemin and chemin[0] != chemin[-1] else ""
            out.append({**self._theme_summary(n), "type": "thème", "domaine": domaine, "source": n["source_id"]})
        return out

    def _has_items(self, node_id: str) -> bool:
        with self._conn() as con:
            return con.execute(
                "SELECT 1 FROM edges e JOIN nodes n ON n.id = e.dst WHERE e.src = ? AND e.rel = 'contient' AND n.kind = 'item' "
                "UNION SELECT 1 FROM edges e JOIN edges f ON f.src = e.dst JOIN nodes n ON n.id = f.dst "
                "WHERE e.src = ? AND e.rel = 'contient' AND f.rel = 'contient' AND n.kind = 'item' LIMIT 1",
                (node_id, node_id),
            ).fetchone() is not None

    def outline(self, level: str, discipline: str, year: int | None = None) -> list[dict]:
        """Le programme d'une discipline pour un niveau : domaines, rubriques ou thèmes, items."""
        level = normalize_level(level)
        discipline = self.resolve_discipline(discipline)
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM nodes WHERE discipline = ? AND kind = 'item' AND levels LIKE ? ORDER BY position",
                (discipline, f"%,{level},%"),
            ).fetchall()
        out = []
        for r in rows:
            n = self._row(r)
            if year is not None and not self.applicable(n["source_id"], level, year):
                continue
            out.append({"id": n["id"], "contexte": n["data"].get("contexte"), "titre": n["title"],
                        "periodes": n["data"].get("periodes", []), "source": n["source_id"], "page": n["page"]})
        return out

    def items_for(self, level: str, discipline: str, year: int) -> list[dict]:
        level = normalize_level(level)
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM nodes WHERE discipline = ? AND kind = 'item' AND levels LIKE ? ORDER BY position",
                (discipline, f"%,{level},%"),
            ).fetchall()
        return [n for n in map(self._row, rows) if self.applicable(n["source_id"], level, year)]

    def applicable_sources(self, level: str, year: int) -> list[dict]:
        level = normalize_level(level)
        return [s for s in self.sources() if self.applicable(s["source_id"], level, year)]
