"""Construction du graphe de connaissance à partir des programmes analysés.

Nœuds : source, discipline, cycle, niveau, domaine, theme, rubrique, sous_rubrique, section,
item (une ligne de tableau du programme), objectif, competence, socle, notion.

Arêtes (src → dst) :
  contient     hiérarchie du programme (source → domaine → niveau → rubrique → item → objectif)
  niveau       item, thème ou rubrique → niveau
  discipline   item, thème → discipline ; source → discipline
  theme        item → thème qui l'englobe
  s_applique   source → niveau (années scolaires d'application dans data)
  suite        rubrique ou thème → même rubrique au niveau suivant (progression)
  competence   discipline → compétence travaillée (cycle dans data)
  socle        compétence ou discipline → domaine du socle commun
  mot_cle      thème → notion (mots-clés du programme d'histoire-géographie)
  mentionne    item → notion citée dans son texte (liens entre disciplines)
  cycle        niveau → cycle
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .outline import Bullet, DocSpec, Heading, Item, levels_of

LEVELS = ["CP", "CE1", "CE2", "CM1", "CM2", "6e"]
CYCLE_OF = {"CP": 2, "CE1": 2, "CE2": 2, "CM1": 3, "CM2": 3, "6e": 3}

SOCLE = {
    "D1": "Les langages pour penser et communiquer",
    "D1.1": "Comprendre, s’exprimer en utilisant la langue française à l’oral et à l’écrit",
    "D1.2": "Comprendre, s’exprimer en utilisant une langue étrangère ou régionale",
    "D1.3": "Comprendre, s’exprimer en utilisant les langages mathématiques, scientifiques et informatiques",
    "D1.4": "Comprendre, s’exprimer en utilisant les langages des arts et du corps",
    "D2": "Les méthodes et outils pour apprendre",
    "D3": "La formation de la personne et du citoyen",
    "D4": "Les systèmes naturels et les systèmes techniques",
    "D5": "Les représentations du monde et l’activité humaine",
}

# Contribution principale de chaque discipline au socle commun, d'après le volet 2 des
# programmes de cycle (2020). Correspondance indicative, utilisée quand le programme ne donne pas
# de tableau « Compétences travaillées / Domaines du socle ».
DISCIPLINE_SOCLE = {
    "Français": ["D1.1", "D2", "D3", "D5"],
    "Mathématiques": ["D1.3", "D2", "D4"],
    "Langues vivantes": ["D1.2", "D2", "D3", "D5"],
    "EPS": ["D1.4", "D2", "D3", "D4"],
    "Arts plastiques": ["D1.4", "D2", "D3", "D5"],
    "Éducation musicale": ["D1.4", "D2", "D3", "D5"],
    "Histoire des arts": ["D1.4", "D3", "D5"],
    "EMC": ["D1.1", "D2", "D3"],
    "EVAR": ["D3", "D4"],
    "Histoire-géographie": ["D1.1", "D2", "D3", "D5"],
    "Questionner le monde": ["D1.3", "D2", "D4", "D5"],
    "Sciences et technologie": ["D1.3", "D2", "D4", "D5"],
}

# Champs d'item qui décrivent ce que l'élève doit savoir faire (les « compétences » de l'item).
COMPETENCE_FIELDS = [
    "attendus", "exemples_reussite", "notions_competences", "connaissances", "connaissances_cm",
    "connaissances_6e", "attendus_fin_cycle", "contenus",
]
FIELD_LABELS = {
    "objectifs": "Objectifs d’apprentissage",
    "exemples_reussite": "Exemples de réussite",
    "attendus": "Attendus (connaissances et compétences)",
    "reperes": "Repères",
    "demarches": "Propositions de démarches et d’activités",
    "notions": "Notions abordées",
    "contenus": "Contenus d’enseignement",
    "notions_competences": "Notions et compétences",
    "competences": "Compétences travaillées",
    "socle": "Domaines du socle",
    "connaissances": "Connaissances et compétences associées",
    "connaissances_cm": "Connaissances et compétences attendues en fin de cours moyen",
    "connaissances_6e": "Connaissances et compétences attendues en fin de sixième",
    "exemples_situations": "Exemples de situations, d’activités et de ressources",
    "attendus_fin_cycle": "Attendus de fin de cycle",
    "reperes_programmation": "Repères annuels de programmation",
    "questionnements": "Questionnements",
    "liens": "Liens avec d’autres enseignements",
}

ORDINALS = {"première": 1, "deuxième": 2, "troisième": 3, "quatrième": 4, "cinquième": 5}
COUNTS = {"une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}


def slug(text: str, limit: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:limit].strip("-") or "x"


def squash_title(text: str) -> str:
    return slug(text, 200)


def period_hint(title: str) -> dict | None:
    """Indication de périodes dans un titre de thème : « (deuxième et troisième périodes) » → [2, 3] ;
    « (trois périodes) » → 3 périodes ; « (1 ou 2 périodes au choix) » → 1 à 2."""
    m = re.search(r"\(([^()]*p[ée]riodes?[^()]*)\)\s*$", title, re.IGNORECASE)
    if not m:
        return None
    inner = m.group(1).lower()
    named = [ORDINALS[w] for w in re.findall(r"première|deuxième|troisième|quatrième|cinquième", inner)]
    if named:
        return {"periodes": sorted(set(named)), "texte": m.group(1)}
    counts = [COUNTS[w] for w in re.findall(r"\b(une|deux|trois|quatre|cinq|[1-5])\b", inner)]
    if counts:
        return {"nb_periodes": [min(counts), max(counts)], "texte": m.group(1)}
    return None


def working_spans(bullets: list[dict]) -> list[tuple[int, int] | None]:
    """Convertit les échéances du programme en périodes de travail.

    « En fin de période 1 » → P1 ; « En milieu d'année » qui suit → P2-P3 ; « En fin d'année » → P4-P5.
    Les marqueurs de début (« Dès le début de l'année », « À partir de la période 2 ») gardent leur étendue.
    """
    spans: list[tuple[int, int] | None] = []
    prev_deadline, current_moment, current_span = 0, None, None
    for b in bullets:
        moment, periods = b.get("moment"), b.get("periodes")
        if not periods:
            spans.append(None)
            continue
        if moment != current_moment:
            a, z = periods
            is_deadline = bool(re.search(r"\bfin\b|milieu|mi-ann", moment, re.IGNORECASE)) and not re.match(r"\s*dès", moment, re.IGNORECASE)
            if is_deadline:
                current_span = (min(prev_deadline + 1, z), z)
                prev_deadline = z
            else:
                current_span = (a, z)
            current_moment = moment
        spans.append(current_span)
    return spans


def hours_hint(title: str) -> str | None:
    m = re.search(r"\((\d+\s*(?:à\s*\d+\s*)?heures)\)", title)
    return m.group(1) if m else None


def clean_title(title: str) -> str:
    """Titre sans l'indication de périodes ou d'heures finale."""
    return re.sub(r"\s*\((?:[^()]*p[ée]riodes?[^()]*|\d+\s*(?:à\s*\d+\s*)?heures)\)\s*$", "", title).strip()


@dataclass
class Node:
    id: str
    kind: str
    title: str
    text: str = ""
    discipline: str = ""
    levels: list[str] = field(default_factory=list)
    source_id: str = ""
    page: int | None = None
    position: int = 0
    data: dict = field(default_factory=dict)


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: set[tuple[str, str, str]] = field(default_factory=set)
    edge_data: dict[tuple[str, str, str], dict] = field(default_factory=dict)

    def add(self, node: Node) -> Node:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        return existing

    def link(self, src: str, rel: str, dst: str, data: dict | None = None) -> None:
        self.edges.add((src, rel, dst))
        if data:
            self.edge_data[(src, rel, dst)] = data


def _bullet_dict(b: Bullet) -> dict:
    d = {"texte": b.text, "page": b.page}
    if b.moment:
        d["moment"] = b.moment
    if b.periods:
        d["periodes"] = list(b.periods)
    if b.group:
        d["groupe"] = b.group
    return d


def _item_text(item: Item) -> str:
    parts = []
    for name, bullets in item.fields.items():
        label = FIELD_LABELS.get(name, name)
        parts.append(f"{label} : " + " ; ".join(b.text for b in bullets))
    return "\n".join(parts)


def _socle_codes(text: str) -> list[str]:
    codes = []
    for m in re.findall(r"\b([1-5])(?:\s*[.,]\s*([1-4]))?\b", text):
        main, sub = m
        codes.append(f"D{main}.{sub}" if sub and main == "1" else f"D{main}")
    return sorted(set(codes))


class GraphBuilder:
    def __init__(self) -> None:
        self.g = Graph()
        self._position = 0
        self._node_of: dict[int, str] = {}  # titre analysé → identifiant de nœud
        for code, label in SOCLE.items():
            self.g.add(Node(f"socle:{code}", "socle", f"{code} — {label}", label, data={"code": code}))
        for level in LEVELS:
            cycle = CYCLE_OF[level]
            self.g.add(Node(f"niveau:{level}", "niveau", level, levels=[level], data={"cycle": cycle}))
            self.g.add(Node(f"cycle:{cycle}", "cycle", f"Cycle {cycle}", data={"cycle": cycle}))
            self.g.link(f"niveau:{level}", "cycle", f"cycle:{cycle}")

    def _discipline(self, name: str) -> str:
        nid = f"discipline:{slug(name)}"
        if nid not in self.g.nodes:
            self.g.add(Node(nid, "discipline", name, discipline=name))
            for code in DISCIPLINE_SOCLE.get(name, []):
                self.g.link(nid, "socle", f"socle:{code}", {"origine": "correspondance indicative (volet 2, 2020)"})
        return nid

    def _next_position(self) -> int:
        self._position += 1
        return self._position

    # ------------------------------------------------------------------ sources
    def add_source(self, spec: DocSpec, root: Heading, file_hash: str) -> None:
        g = self.g
        disc = self._discipline(spec.discipline)
        sid = f"source:{spec.id}"
        applies = {lvl: {"depuis": a, "jusqu_a": b} for lvl, (a, b) in spec.applies.items()}
        g.add(Node(sid, "source", spec.title, text=spec.bo, discipline=spec.discipline,
                   levels=list(spec.applies), source_id=spec.id,
                   data={"bo": spec.bo, "fichier": spec.path.name, "pages": list(spec.pages or []),
                         "cycle": spec.cycle, "application": applies, "hash": file_hash}))
        g.link(sid, "discipline", disc)
        for lvl, years in applies.items():
            g.link(sid, "s_applique", f"niveau:{lvl}", years)
        used_ids: set[str] = set()
        for child in root.children:
            self._heading(spec, child, sid, [], used_ids, disc)
        if root.texts:
            g.nodes[sid].data["introduction"] = root.texts

    def _heading(self, spec: DocSpec, h: Heading, parent: str, path: list[Heading], used: set[str], disc: str) -> None:
        g = self.g
        path = path + [h]
        base = f"{spec.id}/" + "/".join(slug(p.title, 40) for p in path)
        nid, n = base, 2
        while nid in used:
            nid, n = f"{base}-{n}", n + 1
        used.add(nid)
        levels = self._levels(spec, path)
        title = h.title
        data: dict = {"chemin": [p.title for p in path], "rang": h.rank}
        if h.attrs:
            data.update(h.attrs)
        hint = period_hint(title)
        if hint:
            data["periodes_programme"] = hint
        hours = hours_hint(title)
        if hours:
            data["horaire"] = hours
        if h.kind in ("theme", "rubrique", "sous_rubrique", "niveau", "domaine"):
            title = clean_title(title) if h.kind == "theme" else title
        node = g.add(Node(nid, h.kind, title, text="\n".join(h.texts), discipline=spec.discipline,
                          levels=levels, source_id=spec.id, page=h.page, position=self._next_position(), data=data))
        g.link(parent, "contient", nid)
        if h.kind in ("theme", "rubrique", "sous_rubrique"):
            for lvl in levels:
                g.link(nid, "niveau", f"niveau:{lvl}")
            g.link(nid, "discipline", disc)
        # Thème annuel porté par un titre de niveau : « CP : Se reconnaitre comme individu et élève »
        if h.kind == "niveau" and ":" in h.title:
            annual = h.title.split(":", 1)[1].strip()
            if annual and not re.match(r"^\s*$", annual):
                node.data["theme_annuel"] = clean_title(annual[:1].upper() + annual[1:])
                hint = period_hint(annual)
                if hint:
                    node.data["periodes_programme"] = hint
        if "mots_cles" in h.attrs:
            for word in re.split(r"[,;]", h.attrs["mots_cles"].rstrip(". ")):
                word = word.strip()
                if 2 < len(word) < 60:
                    notion = f"notion:{slug(word)}"
                    g.add(Node(notion, "notion", word.lower()))
                    g.link(nid, "mot_cle", notion)
        self._node_of[id(h)] = nid
        theme = next((p for p in reversed(path) if p.kind == "theme"), None)
        theme_id = self._node_of.get(id(theme)) if theme is not None else None
        for i, item in enumerate(h.items, 1):
            self._item(spec, item, nid, f"{nid}#i{i}", path, levels, theme_id, disc)
        for child in h.children:
            self._heading(spec, child, nid, path, used, disc)

    def _levels(self, spec: DocSpec, path: list[Heading]) -> list[str]:
        for h in reversed(path):
            if h.levels:
                return [lv for lv in h.levels if lv in LEVELS]
        return [lv for lv in spec.applies if lv in LEVELS]

    def _item(self, spec: DocSpec, item: Item, parent: str, iid: str, path: list[Heading],
              levels: list[str], theme_id: str | None, disc: str) -> None:
        g = self.g
        head = path[-1]
        lead = item.fields.get(item.lead) or next(iter(item.fields.values()))
        first = (f"{lead[0].group} : {lead[0].text}" if lead[0].group and lead[0].text[:1].islower() else lead[0].text) if lead else head.title
        title = first if len(first) <= 140 else first[:137].rsplit(" ", 1)[0] + "…"
        context = " › ".join(clean_title(p.title) for p in path if p.kind not in ("section",))
        fields = {name: [_bullet_dict(b) for b in bullets] for name, bullets in item.fields.items()}
        spans = [s for bullets in fields.values() for s in working_spans(bullets) if s]
        periods = sorted({p for a, b in spans for p in range(a, b + 1)})
        g.add(Node(iid, "item", title, text=f"{context}\n{_item_text(item)}", discipline=spec.discipline,
                          levels=levels, source_id=spec.id, page=item.page, position=self._next_position(),
                          data={"contexte": context, "champs": fields, "periodes": periods,
                                "rubrique": clean_title(head.title), "chemin": [p.title for p in path]}))
        g.link(parent, "contient", iid)
        g.link(iid, "discipline", disc)
        for lvl in levels:
            g.link(iid, "niveau", f"niveau:{lvl}")
        if theme_id:
            g.link(iid, "theme", theme_id)
        # objectifs : un nœud par puce de la première colonne
        # (les tableaux « Compétences travaillées » deviennent des nœuds compétence, pas des objectifs)
        if item.lead in ("objectifs", "notions_competences", "connaissances", "connaissances_cm", "attendus_fin_cycle", "questionnements", "reperes_programmation", "notions"):
            for k, b in enumerate(item.fields.get(item.lead, []), 1):
                oid = f"{iid}/o{k}"
                # « à l'eau ; ou » n'a de sens qu'avec son intertitre « L'inégal accès »
                label = f"{b.group} : {b.text}" if b.group and b.text[:1].islower() else b.text
                g.add(Node(oid, "objectif", label, text=f"{context}\n{label}", discipline=spec.discipline, levels=levels,
                           source_id=spec.id, page=b.page, position=self._next_position(),
                           data={**_bullet_dict(b), "contexte": context}))
                g.link(iid, "contient", oid)
        # compétences travaillées (anciens programmes) : un nœud par compétence majeure
        if "competences" in item.fields:
            self._competences(spec, item, disc)

    def _competences(self, spec: DocSpec, item: Item, disc: str) -> None:
        g = self.g
        socle_text = " ".join(b.text for b in item.fields.get("socle", []))
        codes = _socle_codes(socle_text)
        groups: dict[str, list[str]] = {}
        for b in item.fields["competences"]:
            groups.setdefault(b.group or b.text, []).append(b.text)
        for group, details in groups.items():
            cid = f"competence:{slug(spec.discipline)}-c{spec.cycle}-{slug(group, 50)}"
            node = g.add(Node(cid, "competence", group, text="\n".join(details), discipline=spec.discipline,
                              levels=[lv for lv in spec.applies], source_id=spec.id,
                              data={"cycle": spec.cycle, "details": [d for d in details if d != group]}))
            g.link(disc, "competence", cid, {"cycle": spec.cycle})
            for code in codes:
                g.link(cid, "socle", f"socle:{code}")
            if not node.data.get("socle") and codes:
                node.data["socle"] = codes

    # ------------------------------------------------------------------ liens transverses
    def finish(self) -> Graph:
        self._progressions()
        self._mentions()
        return self.g

    def _progressions(self) -> None:
        """Même rubrique ou thème d'un niveau au suivant, dans une même discipline et un même domaine."""
        g = self.g
        groups: dict[tuple[str, str, str], list[Node]] = {}
        for n in g.nodes.values():
            if n.kind not in ("rubrique", "theme", "sous_rubrique") or len(n.levels) != 1:
                continue
            chemin = n.data.get("chemin", [])
            domaine = next((t for t in chemin if not levels_of(t)), "")
            key = (n.discipline, squash_title(domaine) if domaine != n.title else "", squash_title(n.title))
            groups.setdefault(key, []).append(n)
        for nodes in groups.values():
            nodes.sort(key=lambda n: (LEVELS.index(n.levels[0]), -int(n.source_id[-4:]) if n.source_id[-4:].isdigit() else 0))
            by_level: dict[str, Node] = {}
            for n in nodes:
                by_level.setdefault(n.levels[0], n)
            ordered = [by_level[lv] for lv in LEVELS if lv in by_level]
            for a, b in zip(ordered, ordered[1:]):
                g.link(a.id, "suite", b.id)

    def _mentions(self) -> None:
        """Notions (mots-clés d'histoire-géographie) citées dans les items des autres disciplines."""
        g = self.g
        notions = [n for n in g.nodes.values() if n.kind == "notion" and len(n.title) >= 4]
        patterns = [(n, re.compile(rf"\b{re.escape(n.title)}s?\b", re.IGNORECASE)) for n in notions]
        for item in [n for n in g.nodes.values() if n.kind == "item"]:
            # le contenu seul : le contexte (« Cours élémentaire première année », « Écriture ») ne compte pas
            content = " ".join(b["texte"] for bullets in item.data["champs"].values() for b in bullets)
            for notion, pat in patterns:
                if pat.search(content):
                    g.link(item.id, "mentionne", notion.id)
