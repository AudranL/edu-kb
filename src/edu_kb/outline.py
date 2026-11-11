"""Reconstruction de la structure d'un programme : titres hiérarchisés, tableaux, puces.

Chaque document est décrit dans sources.toml : quels styles de ligne sont des titres, et de quel
rang (domaine > niveau > rubrique…). Le parseur parcourt les lignes dans l'ordre et maintient la
pile des titres ouverts. Les tableaux sont reconnus à leur ligne d'en-tête (« Objectifs
d'apprentissage », « Exemples de réussite », « Repères »…) : chaque colonne devient un champ de
l'item, et chaque ligne de tableau tracée devient un item. Dans une cellule, les puces sont
séparées, les marqueurs temporels (« En fin de période 1 ») et les intertitres en gras
(« Expérimenter, produire, créer ») sont rattachés aux puces qui les suivent.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path

import pymupdf

from .extract import BULLET_CHARS, Line

# Intitulés de colonnes reconnus → nom du champ. L'ordre compte : le premier motif qui
# correspond l'emporte.
COLUMN_LABELS: list[tuple[str, str]] = [
    (r"^objectifs?d'apprentissage$", "objectifs"),
    (r"^objectifs$", "objectifs"),
    (r"^exemplesderéussite$", "exemples_reussite"),
    (r"^attendus\(connaissanceset(compétences\))?$", "attendus"),
    (r"^attendus$", "attendus"),
    (r"^repères$", "reperes"),
    (r"^propositionsdedémarches", "demarches"),
    (r"^notionsabordées$", "notions"),
    (r"^contenusd'enseignement$", "contenus"),
    (r"^démarchesetsituationsd'apprentissage", "demarches"),
    (r"^notionsetcompétences$", "notions_competences"),
    (r"^compétencestravaillées", "competences"),
    (r"^compétences$", "competences"),
    (r"^domaines(dusocle)?$", "socle"),
    (r"^connaissancesetcompétencesattenduesenfindecoursmoyen$", "connaissances_cm"),
    (r"^connaissancesetcompétencesattenduesenfindesixième$", "connaissances_6e"),
    (r"^connaissancesetcompétencesattenduesen$", "connaissances"),
    (r"^connaissancesetcompétencesassociées$", "connaissances"),
    (r"^connaissancesetcompétences$", "connaissances"),
    (r"^connaissanceset$", "connaissances"),
    (r"^exemplesdesituations", "exemples_situations"),
    (r"^exemplesde$", "exemples_situations"),
    (r"^attendusdefindecycle$", "attendus_fin_cycle"),
    (r"^repèresannuelsde(programmation)?$", "reperes_programmation"),
    (r"^questionnements$", "questionnements"),
    (r"^lienàd'autres(enseignements)?$", "liens"),
    (r"^démarchesetcontenusd'enseignement$", "demarches"),
]

# Suites d'intitulés qui ne commencent pas une colonne (2e ligne d'un intitulé coupé).
LABEL_CONTINUATIONS = re.compile(
    r"^(compétences\)|compétencesassociées|associées|pourl'élève|d'activitésetde|d'activitésetderessources|"
    r"ressourcespourl'élève|etderessourcespourl'élève|deressourcespourl'élève|programmation|enseignements|findecoursmoyen|"
    r"findesixième|dusocle|l'élève|d'activitésetderessourcespour|"
    r"lesséancesoutempsd'enseignementspécifiques.*|possibles|d'enseignementspécifiques.*)$"
)

LEVEL_PATTERNS: list[tuple[str, list[str]]] = [
    (r"cours moyen premi[eè]re et deuxi[eè]me ann[ée]es?", ["CM1", "CM2"]),
    (r"cours pr[ée]paratoire", ["CP"]),
    (r"cours [ée]l[ée]mentaire premi[eè]re ann[ée]e", ["CE1"]),
    (r"cours [ée]l[ée]mentaire deuxi[eè]me ann[ée]e", ["CE2"]),
    (r"cours moyen premi[eè]re ann[ée]e", ["CM1"]),
    (r"cours moyen deuxi[eè]me ann[ée]e", ["CM2"]),
    (r"^cours moyen$", ["CM1", "CM2"]),
    (r"^sixi[eè]me|classe de sixi[eè]me|^6e$", ["6e"]),
    (r"^classe de (CP|CE1|CE2|CM1|CM2)$", []),  # niveau donné par le texte
    (r"^(CP|CE1|CE2|CM1|CM2)\s*:", []),
    (r"^CM1-CM2$", ["CM1", "CM2"]),
]

SECTION_TITLES = re.compile(
    r"^(principes|préambule|propos introductif|sommaire|points? de vigilance.*|organisation du programme|"
    r"approches pédagogiques|modalités de mise en œuvre|structuration du programme|fréquence des temps.*|"
    r"objectifs majeurs|croisements entre enseignements|spécificités du cycle.*|volume horaire|"
    r"compétences travaillées.*|attendus de fin de cycle|repères de progressivité|exemples)$",
    re.IGNORECASE,
)

# Marqueurs temporels → périodes (début, fin) où l'objectif est travaillé. « n » = numéro lu dans le texte.
MOMENTS: list[tuple[str, tuple[int | str, int | str]]] = [
    (r"^dès la fin de la p[ée]riode (?P<n>\d)", ("n", 5)),
    (r"^(?:en |à la )?fin de (?:la )?p[ée]riode (?P<n>\d)", ("n", "n")),
    (r"^(?:dès|à partir de) (?:la )?(?P<n>\d)e p[ée]riode", ("n", 5)),
    (r"^(?:dès|à partir de) (?:la )?p[ée]riode (?P<n>\d)", ("n", 5)),
    (r"^(?:au cours de|en|pendant) (?:la )?(?P<n>\d)e p[ée]riode", ("n", "n")),
    (r"^(?:au cours de|en|pendant) (?:la )?p[ée]riode (?P<n>\d)", ("n", "n")),
    (r"^au cours des p[ée]riodes (?P<n>\d) à (?P<m>\d)", ("n", "m")),
    (r"^dès (?:le début de l'ann[ée]e|les premières semaines|la rentrée)", (1, 5)),
    (r"^en d[ée]but d'ann[ée]e", (1, 1)),
    (r"^(?:en|au) milieu d'ann[ée]e|^à mi-ann[ée]e", (3, 3)),
    (r"^(?:en|à la) fin (?:d'|de l')ann[ée]e|^en fin de (?:cp|ce1|ce2|cm1|cm2)\b", (5, 5)),
    (r"^(?:en|au) cours d'ann[ée]e|^tout au long de l'ann[ée]e|^au fil de l'ann[ée]e", (1, 5)),
]


# Écart vertical (en fraction de la taille de police) au-delà duquel une ligne ouvre un paragraphe.
PARAGRAPH_GAP = 0.33


LABEL_STARTS = re.compile(
    r"\b(Objectifs?|Exemples|Attendus|Repères|Connaissances|Compétences|Domaines|Propositions|Notions|"
    r"Contenus|Démarches|Questionnements|Lien)\b"
)


def squash(text: str) -> str:
    """Forme de comparaison : minuscules, apostrophes droites, sans espaces."""
    text = unicodedata.normalize("NFC", text).lower().replace("’", "'").replace("ʼ", "'")
    return re.sub(r"\s+", "", text)


def clean(text: str) -> str:
    text = text.strip()
    while text and (text[0] in BULLET_CHARS or text[0] in " ."):
        text = text[1:].lstrip()
    return text.replace("’", "’").strip()


def column_field(text: str) -> str | None:
    s = squash(text)
    for pattern, name in COLUMN_LABELS:
        if re.search(pattern, s):
            return name
    return None


def parse_moment(text: str) -> tuple[str, tuple[int, int]] | None:
    t = text.strip().rstrip(":").strip().lower().replace("’", "'")
    if len(t) > 60:
        return None
    for pattern, (start, end) in MOMENTS:
        m = re.search(pattern, t)
        if m:
            groups = m.groupdict()
            span = tuple(int(groups[v]) if isinstance(v, str) else v for v in (start, end))
            return text.strip().rstrip(":").strip(), (span[0], span[1])
    return None


def levels_of(title: str) -> list[str] | None:
    t = title.strip()
    for pattern, levels in LEVEL_PATTERNS:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            if levels:
                return levels
            return [m.group(1).upper()]
    return None


# --------------------------------------------------------------------------- configuration
@dataclass
class HeadingRule:
    rank: int
    kind: str  # domaine | niveau | theme | rubrique | sous_rubrique | section
    style: str = ".*"  # regex sur la signature « taille/B|R/couleur »
    text: str | None = None  # regex sur le texte
    x_min: float = 0
    x_max: float = 10_000
    size_min: float = 0
    size_max: float = 1_000
    in_table: bool = False  # intertitre placé à l'intérieur d'un tableau (anciens programmes)
    strip: str | None = None  # regex à retirer du titre (préfixe « Objectif d'apprentissage : »)

    def matches(self, line: Line, text: str) -> bool:
        if not (self.x_min <= line.x0 <= self.x_max and self.size_min <= line.size <= self.size_max):
            return False
        if not re.fullmatch(self.style, line.style):
            return False
        return self.text is None or re.search(self.text, text, re.IGNORECASE) is not None


@dataclass
class DocSpec:
    id: str
    path: Path
    title: str
    discipline: str
    cycle: int
    levels: list[str]
    pages: tuple[int, int] | None
    headings: list[HeadingRule]
    domaines: list[str] = field(default_factory=list)
    theme_under: list[str] = field(default_factory=list)  # rubriques de ces domaines = thèmes
    rubrique_kind: str = ""  # type donné à toutes les rubriques (« theme »)
    skip: list[str] = field(default_factory=list)
    skip_top: float = 0
    skip_bottom: float = 10_000
    sommaire_until: float = 0
    ocr: bool = False
    bo: str = ""
    applies: dict[str, tuple[int, int | None]] = field(default_factory=dict)


# --------------------------------------------------------------------------- arbre
@dataclass
class Bullet:
    text: str
    page: int
    moment: str | None = None
    periods: tuple[int, int] | None = None
    group: str | None = None


@dataclass
class Item:
    page: int
    lead: str = ""  # champ de la première colonne du tableau (« objectifs »…)
    fields: dict[str, list[Bullet]] = field(default_factory=dict)

    def add(self, name: str, bullet: Bullet) -> None:
        self.fields.setdefault(name, []).append(bullet)

    @property
    def empty(self) -> bool:
        return not any(self.fields.values())


@dataclass
class Heading:
    kind: str
    title: str
    rank: int
    page: int
    levels: list[str] | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    texts: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    children: list["Heading"] = field(default_factory=list)

    def walk(self, path: tuple["Heading", ...] = ()):
        path = path + (self,)
        yield path
        for child in self.children:
            yield from child.walk(path)


# --------------------------------------------------------------------------- tableaux tracés
@dataclass
class _Grid:
    bbox: tuple[float, float, float, float]
    cols: list[float]  # abscisses de début de colonne
    rows: list[tuple[float, float]]


def _cluster(values: list[float], tol: float) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def page_grids(page: pymupdf.Page) -> list[_Grid]:
    """Tableaux reconstitués à partir des traits dessinés (rectangles fins ou lignes).

    Les programmes tracent les bordures avec de fins rectangles pleins, que find_tables ne
    reconnaît pas toujours : on rassemble les traits horizontaux et verticaux, on forme les
    bandes de lignes (deux traits horizontaux reliés par des traits verticaux), puis on regroupe
    les bandes contiguës en tableaux.
    """
    hs: list[tuple[float, float, float]] = []  # (y, x0, x1)
    vs: list[tuple[float, float, float]] = []  # (x, y0, y1)
    for d in page.get_drawings():
        for item in d["items"]:
            if item[0] == "re":
                r = item[1]
            elif item[0] == "l":
                p1, p2 = item[1], item[2]
                r = pymupdf.Rect(min(p1.x, p2.x), min(p1.y, p2.y), max(p1.x, p2.x), max(p1.y, p2.y))
            else:
                continue
            if r.height <= 2 and r.width > 15:
                hs.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
            elif r.width <= 2 and r.height > 4:
                vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
            elif r.width > 15 and r.height > 4 and d.get("fill") is not None and d.get("type") == "fs":
                # cellule pleine avec bordure : ses quatre côtés
                hs += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
                vs += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
    if not hs or not vs:
        return []
    # Un trait horizontal est souvent fait d'un segment par cellule : on fusionne les segments
    # alignés et contigus.
    merged: list[tuple[float, float, float]] = []
    for y, x0, x1 in sorted(hs, key=lambda h: (round(h[0]), h[1])):
        if merged and abs(merged[-1][0] - y) < 1.5 and x0 <= merged[-1][2] + 3:
            py, px0, px1 = merged[-1]
            merged[-1] = (py, px0, max(px1, x1))
        else:
            merged.append((y, x0, x1))
    hs = merged
    merged_v: list[tuple[float, float, float]] = []
    for x, y0, y1 in sorted(vs, key=lambda v: (round(v[0]), v[1])):
        if merged_v and abs(merged_v[-1][0] - x) < 1.5 and y0 <= merged_v[-1][2] + 3:
            px, py0, py1 = merged_v[-1]
            merged_v[-1] = (px, py0, max(py1, y1))
        else:
            merged_v.append((x, y0, y1))
    vs = merged_v
    # Les cellules contiennent parfois de petits tableaux (exemples de calcul) : seuls les traits
    # aussi larges que le tableau principal séparent ses lignes.
    widest = max(x1 - x0 for _, x0, x1 in hs)
    hs = [h for h in hs if h[2] - h[1] >= 0.6 * widest]
    ys = _cluster([h[0] for h in hs], 1.5)
    bands: list[tuple[float, float, list[float]]] = []
    for ya, yb in zip(ys, ys[1:]):
        if yb - ya < 4:
            continue
        span = [h for h in hs if abs(h[0] - ya) < 2]
        left, right = min(h[1] for h in span), max(h[2] for h in span)
        xs = [x for x, y0, y1 in vs if y0 <= ya + 2 and y1 >= yb - 2 and left - 3 <= x <= right + 3]
        xs = _cluster(xs, 3)
        if xs and (xs[0] > left + 5 or xs[-1] < right - 5):
            continue  # traits verticaux d'un tableau intérieur seulement
        if len(xs) >= 2:
            bands.append((ya, yb, xs))
    grids: list[_Grid] = []
    for ya, yb, xs in bands:
        g = grids[-1] if grids else None
        if g and abs(g.rows[-1][1] - ya) < 2 and abs(g.bbox[0] - xs[0]) < 4 and abs(g.bbox[2] - xs[-1]) < 4:
            g.rows.append((ya, yb))
            g.bbox = (g.bbox[0], g.bbox[1], g.bbox[2], yb)
            if len(xs) - 1 > len(g.cols):
                g.cols = xs[:-1]
        else:
            grids.append(_Grid((xs[0], ya, xs[-1], yb), xs[:-1], [(ya, yb)]))
    return grids


def _grids(path: Path, pages: tuple[int, int] | None) -> dict[int, list[_Grid]]:
    doc = pymupdf.open(path)
    first, last = pages or (1, doc.page_count)
    return {pno + 1: page_grids(doc[pno]) for pno in range(first - 1, min(last, doc.page_count))}


# --------------------------------------------------------------------------- parseur
class _Table:
    def __init__(self, page: int, labels: list[tuple[float, float, str]], grid: _Grid | None):
        self.labels = sorted(labels)  # (x0, x1, champ)
        self.fields = [f for _, _, f in self.labels]
        self.gridded = grid is not None  # tableau tracé : il se termine à la sortie de sa grille
        self.bounds = self._bounds(grid)
        self.page = page
        self.row_key: tuple[int, int] | None = None
        self.item: Item | None = None
        self.open: dict[int, Bullet | None] = {}
        self.last_line: dict[int, Line] = {}
        self.moment: dict[int, tuple[str, tuple[int, int]] | None] = {}
        self.group: dict[int, str | None] = {}

    def _bounds(self, grid: _Grid | None) -> list[float]:
        n = len(self.labels)
        if grid and len(grid.cols) == n:
            return [c - 4 for c in grid.cols[1:]]
        # À défaut de grille : milieu entre la fin d'un intitulé et le début du suivant.
        return [(self.labels[i][1] + self.labels[i + 1][0]) / 2 for i in range(n - 1)]

    def column(self, x0: float) -> int:
        for i, b in enumerate(self.bounds):
            if x0 < b:
                return i
        return len(self.bounds)


class OutlineParser:
    def __init__(self, spec: DocSpec, lines: list[Line], grids: dict[int, list[_Grid]]):
        self.spec = spec
        self.lines = lines
        self.grids = grids
        sizes: dict[float, int] = {}
        for line in lines:
            sizes[line.size] = sizes.get(line.size, 0) + len(line.text)
        self.body_size = max(sizes, key=sizes.get) if sizes else 10.0
        self.root = Heading("document", spec.title, 0, 1)
        self.stack: list[Heading] = [self.root]
        self.table: _Table | None = None
        self.last_labels: list[tuple[float, float, str]] = []
        self.closed: _Table | None = None  # dernier tableau terminé (pour une reprise après saut de page)
        self.closed_page = 0
        self.keywords_open: Heading | None = None
        self.skips = [re.compile(s, re.IGNORECASE) for s in spec.skip]

    # ------------------------------------------------------------------ helpers
    @property
    def current(self) -> Heading:
        return self.stack[-1]

    def _skip(self, line: Line) -> bool:
        if line.y0 < self.spec.skip_top or line.y0 > self.spec.skip_bottom:
            return True
        first_page = self.spec.pages[0] if self.spec.pages else 1
        if line.page == first_page and line.y0 < self.spec.sommaire_until:
            return True
        if line.y0 > 750 and re.fullmatch(r"\d{1,3}", line.text.strip()):
            return True  # numéro de page
        return any(r.search(line.text) for r in self.skips)

    def _heading_rule(self, line: Line, text: str) -> HeadingRule | None:
        if len(text) < 2 or (line.text and line.text[0] in BULLET_CHARS and line.text[0] != "➜" and not line.text.startswith("➜")):
            # une puce n'est jamais un titre (sauf la flèche des titres de l'EVAR)
            if not line.text.startswith("➜"):
                return None
        for rule in self.spec.headings:
            if rule.in_table != (self.table is not None) and rule.in_table:
                continue
            if rule.matches(line, text):
                return rule
        return None

    def _open_heading(self, rule: HeadingRule, title: str, page: int) -> None:
        kind, rank = rule.kind, rule.rank
        levels = levels_of(title)
        if SECTION_TITLES.match(title):
            kind = "section"
        elif rule.kind == "niveau" and levels is None:
            kind = "section"
        elif levels is not None and kind in ("rubrique", "sous_rubrique", "theme"):
            kind, rank = "niveau", 2  # PDF scannés : le style ne distingue pas les niveaux
        if any(squash(title) == squash(d) for d in self.spec.domaines):
            kind, rank = "domaine", 1
        if kind == "rubrique" and self.spec.rubrique_kind and (
            not self.spec.domaines or any(h.kind == "domaine" for h in self.stack)
        ):
            # (pas avant le premier domaine : les rubriques des principes ne sont pas des thèmes)
            kind = self.spec.rubrique_kind
        if kind == "rubrique" and any(
            h.kind == "domaine" and squash(h.title) in {squash(t) for t in self.spec.theme_under} for h in self.stack
        ):
            kind = "theme"
        while len(self.stack) > 1 and self.stack[-1].rank >= rank:
            self.stack.pop()
        node = Heading(kind, title, rank, page, levels=levels if kind != "section" else None)
        self.current.children.append(node)
        self.stack.append(node)
        self.table = None if not rule.in_table else self.table
        if rule.in_table and self.table is not None:
            self.table.item = None
            self.table.row_key = None
        self.keywords_open = None

    def _merge_heading(self, line: Line, text: str, rule: HeadingRule) -> bool:
        """Titre sur deux lignes : même style, ligne juste en dessous."""
        h = self.current
        if h.rank != rule.rank or h.items or h.children or h.texts:
            return False
        last = getattr(self, "_last_heading_line", None)
        if last is None or last.page != line.page or last.style != line.style:
            return False
        if not (-3 <= line.y0 - last.y1 < line.size * 0.9):  # les cadres de lignes se chevauchent parfois
            return False
        h.title = f"{h.title} {text}".strip()
        lv = levels_of(h.title)
        if h.kind in ("niveau", "section") and lv:
            h.levels, h.kind = lv, "niveau"
        return True

    def _heading_continuation(self, line: Line, text: str) -> bool:
        """Suite d'un titre coupé dont la 2e ligne ne correspond à aucune règle (« …sociales et » /
        « juridiques) d'une relation humaine. ») : même style, juste en dessous, en minuscule."""
        h, last = self.current, getattr(self, "_last_heading_line", None)
        if last is None or h.kind == "document" or h.items or h.children or h.texts or self.table is not None:
            return False
        if last.page != line.page or last.style != line.style or not text[:1].islower() or h.title.rstrip().endswith((".", "?", "!")):
            return False
        if not -3 <= line.y0 - last.y1 < line.size * 0.9:
            return False
        h.title = f"{h.title} {text}".strip()
        self._last_heading_line = line
        return True

    # ------------------------------------------------------------------ tableaux
    def _label_style(self, line: Line) -> bool:
        return line.bold or self.spec.ocr or line.color == 0xFFFFFF

    @staticmethod
    def _label_pieces(line: Line) -> list[Line]:
        """Deux intitulés voisins fondus en une ligne (« … associées Exemples de situations… ») :
        on coupe avant chaque mot qui ouvre un intitulé connu, abscisses estimées au prorata."""
        cuts = [m.start() for m in LABEL_STARTS.finditer(line.text) if m.start() > 0]
        if not cuts:
            return [line]
        pieces, bounds = [], [0] + cuts + [len(line.text)]
        width = (line.x1 - line.x0) / max(1, len(line.text))
        for a, b in zip(bounds, bounds[1:]):
            pieces.append(replace(line, text=line.text[a:b].strip(), x0=line.x0 + a * width, x1=line.x0 + b * width))
        return pieces

    def _header_labels(self, idx: int) -> tuple[list[tuple[float, float, str]], set[int]] | None:
        """Ligne d'en-tête de tableau : intitulés de colonnes, éventuellement sur plusieurs lignes.

        Les lignes d'intitulé proches sont regroupées par colonne (recouvrement horizontal) ; le
        champ est déduit du texte complet de chaque colonne.
        """
        line = self.lines[idx]
        if not self._label_style(line) or not any(column_field(p.text) for p in self._label_pieces(line)):
            return None
        block: list[int] = []
        pieces: list[Line] = []
        for j in range(max(0, idx - 8), min(len(self.lines), idx + 16)):
            other = self.lines[j]
            if other.page != line.page or not -14 <= other.y0 - line.y0 <= 30 or not self._label_style(other):
                continue
            parts = self._label_pieces(other)
            if all(column_field(p.text) or LABEL_CONTINUATIONS.match(squash(p.text)) for p in parts):
                block.append(j)
                pieces += parts
        columns: list[list] = []  # [x0, x1, [(y, texte)]]
        for o in sorted(pieces, key=lambda p: (p.y0, p.x0)):
            for col in columns:
                if o.x0 < col[1] - 2 and o.x1 > col[0] + 2:
                    col[0], col[1] = min(col[0], o.x0), max(col[1], o.x1)
                    col[2].append(o.text)
                    break
            else:
                columns.append([o.x0, o.x1, [o.text]])
        labels = []
        for x0, x1, texts in columns:
            name = column_field(" ".join(texts)) or column_field(texts[0])
            if name:
                labels.append((x0, x1, name))
        if not labels:
            return None
        return labels, set(block)

    def _grid_for(self, page: int, y: float) -> _Grid | None:
        for g in self.grids.get(page, []):
            if g.bbox[1] - 3 <= y <= g.bbox[3] + 3:
                return g
        return None

    def _row_key(self, line: Line) -> tuple[int, int, bool] | None:
        """(page, haut de la ligne de tableau, est-ce la 1re ligne d'un tableau en haut de page ?)"""
        mid = (line.y0 + line.y1) / 2
        grid = self._grid_for(line.page, mid)
        if grid is None:
            return None
        for i, (y0, y1) in enumerate(grid.rows):
            if y0 - 1 <= mid <= y1 + 1:
                return (line.page, round(y0), i == 0 and grid.bbox[1] < 70)
        return None

    def _table_line(self, line: Line, text: str) -> None:
        t = self.table
        assert t is not None
        if not self.spec.ocr and not 0.8 * self.body_size <= line.size <= 1.25 * self.body_size and not re.search(r"\d/\d", text):
            return  # texte d'une figure (schéma, opération posée) dessinée dans la cellule ; on garde les fractions
        col = t.column(line.x0)
        name = t.fields[col]
        key = self._row_key(line)
        new_row = key is not None and t.row_key is not None and key[:2] != t.row_key[:2]
        # une ligne de tableau coupée par le saut de page continue sur la page suivante ; une
        # ligne qui commence par une minuscule prolonge la cellule précédente
        continued = new_row and (
            (key[0] != t.row_key[0] and key[2])
            or (not line.is_bullet and text[:1].islower() and t.open.get(col) is not None)
        )
        if t.item is None or (new_row and not continued):
            t.item = Item(line.page, lead=t.fields[0])
            self.current.items.append(t.item)
            t.open = {}
            t.moment = {}
            t.group = {}
        if key is not None:
            t.row_key = key
        moment = parse_moment(text) if line.bold or len(text) < 45 else None
        if moment and (line.bold or text.rstrip().endswith(":") or len(text) < 45) and not line.is_bullet:
            t.moment[col] = moment
            t.open[col] = None
            t.last_line[col] = line
            return
        prev = t.last_line.get(col)
        bullet = t.open.get(col)
        if line.bold and not line.is_bullet and name in ("competences", "connaissances", "objectifs", "attendus_fin_cycle") and len(text) < 120:
            # intertitre de cellule : compétence majeure, sous-partie…
            if bullet is not None and prev is not None and prev.bold and line.y0 - prev.y1 < line.size:
                t.group[col] = f"{t.group[col]} {text}"
            else:
                t.group[col] = text
            t.open[col] = None
            t.last_line[col] = line
            return
        if text.rstrip().endswith(":") and len(text) < 60:
            # « Connaitre et comprendre : », « - L'inégal accès : » introduisent les puces suivantes ;
            # si la ligne finit une phrase commencée (« Développer… les compétences qui / lui permettront
            # en fin d'année : »), toute la phrase est l'introduction, pas un objectif
            intro = clean(text)
            if bullet is not None and not line.is_bullet and not bullet.text.rstrip().endswith((".", "!", "?", ";", ":")):
                intro = _join(bullet.text, text)
                t.item.fields[name].remove(bullet)
            t.group[col] = intro.rstrip(" :")
            t.open[col] = None
            t.last_line[col] = line
            return
        # L'interligne des PDF scannés est irrégulier : seules les puces y ouvrent un paragraphe.
        gap = 1.2 if self.spec.ocr else PARAGRAPH_GAP
        new = (
            bullet is None
            or line.is_bullet
            or (not continued and prev is not None and prev.page == line.page and line.y0 - prev.y1 > line.size * gap)
        )
        if new and not line.is_bullet and bullet is not None and (
            # une phrase inachevée continue, même après un interligne plus grand ou une figure
            (text[:1].islower() and not bullet.text.rstrip().endswith((".", "!", "?")))
            # une ligne sans lettre (opération posée, schéma) n'ouvre pas de paragraphe
            or not re.search(r"[^\W\d_]", text)
        ):
            new = False
        if new and not re.search(r"[^\W\d_]", text):
            return
        if new:
            m = t.moment.get(col)
            bullet = Bullet(clean(text), line.page, m[0] if m else None, m[1] if m else None, t.group.get(col))
            if bullet.text:
                t.item.add(name, bullet)
                t.open[col] = bullet
        else:
            bullet.text = _join(bullet.text, clean(text) if line.is_bullet else text)
        t.last_line[col] = line

    # ------------------------------------------------------------------ boucle
    def parse(self) -> Heading:
        consumed: set[int] = set()
        for idx, line in enumerate(self.lines):
            if idx in consumed or self._skip(line):
                continue
            text = clean(line.text) if line.text.startswith("➜") else line.text.strip()
            header = self._header_labels(idx)
            if header:
                labels, used = header
                consumed |= used
                grid = self._grid_for(line.page, line.y0 + 2)
                self.table = _Table(line.page, labels, grid)
                self.last_labels = labels
                self.keywords_open = None
                continue
            rule = self._heading_rule(line, text)
            if rule is not None:
                if rule.strip:
                    text = re.sub(rule.strip, "", text, flags=re.IGNORECASE).strip()
                if not self._merge_heading(line, text, rule):
                    self._open_heading(rule, text, line.page)
                self._last_heading_line = line
                continue
            if self._heading_continuation(line, text):
                continue
            low = text.lower()
            if low.startswith("question") and ":" in text[:12]:
                self.current.attrs["question"] = _join(self.current.attrs.get("question", ""), text.split(":", 1)[1].strip())
                continue
            if low.startswith(("mots-clés", "mots clés")):
                self.table = None
                self.keywords_open = self.current
                self.current.attrs["mots_cles"] = text.split(":", 1)[1].strip() if ":" in text else ""
                continue
            if self.keywords_open is self.current and "mots_cles" in self.current.attrs:
                last = getattr(self, "_last_line", None)
                if last is not None and last.page == line.page and line.y0 - last.y1 < line.size * 0.6:
                    self.current.attrs["mots_cles"] = _join(self.current.attrs["mots_cles"], text)
                    self._last_line = line
                    continue
                self.keywords_open = None
            if self.table is not None and self._ends_table(line):
                self.closed, self.closed_page = self.table, line.page
                self.table = None
            if self.table is None and self.last_labels:
                grid = self._grid_for(line.page, (line.y0 + line.y1) / 2)
                if grid is not None and len(grid.cols) == len(self.last_labels):
                    closed = self.closed
                    if closed is not None and line.page - self.closed_page <= 1 and grid.bbox[1] < 80 and closed.item in self.current.items:
                        # tableau coupé par le saut de page : il reprend en haut de la page suivante
                        self.table = closed
                        self.table.page = line.page
                    elif self.current.kind in ("rubrique", "sous_rubrique", "theme"):
                        # tableau sans ligne d'en-tête sous une rubrique : mêmes colonnes que le précédent
                        self.table = _Table(line.page, self.last_labels, grid)
            if self.table is not None:
                self._table_line(line, text)
            else:
                self._prose(line, text)
            self._last_line = line
        _prune(self.root)
        return self.root

    def _ends_table(self, line: Line) -> bool:
        """Dans un PDF aux tableaux tracés, une ligne hors de toute grille termine le tableau.

        Sans tracés (PDF scannés), seuls un titre, un nouvel en-tête ou « Mots-clés » le terminent.
        """
        if not self.table.gridded:
            return False
        return self._grid_for(line.page, (line.y0 + line.y1) / 2) is None

    def _prose(self, line: Line, text: str) -> None:
        h = self.current
        last = getattr(self, "_last_line", None)
        if h.texts and last is not None and last.page == line.page and 0 <= line.y0 - last.y1 < line.size * PARAGRAPH_GAP and not line.is_bullet:
            h.texts[-1] = _join(h.texts[-1], text)
        elif h.texts and last is not None and last.page != line.page and not line.is_bullet and text[:1].islower():
            h.texts[-1] = _join(h.texts[-1], text)
        else:
            h.texts.append(clean(text) if line.is_bullet else text)


def _join(a: str, b: str) -> str:
    if not a:
        return b
    if a.endswith("-") and b[:1].islower():
        return a + b
    return f"{a} {b}"


def _prune(node: Heading) -> None:
    items: list[Item] = []
    for item in node.items:
        if item.empty:
            continue
        prev = items[-1] if items else None
        if prev is not None and item.lead == prev.lead and item.lead not in item.fields and prev.lead in prev.fields:
            # cellule fusionnée : la première colonne couvre plusieurs lignes du tableau
            for name, bullets in item.fields.items():
                prev.fields.setdefault(name, []).extend(bullets)
            continue
        items.append(item)
    node.items = items
    for c in node.children:
        _prune(c)


def parse_document(spec: DocSpec, lines: list[Line], source: Path) -> Heading:
    grids = _grids(source, spec.pages)
    return OutlineParser(spec, lines, grids).parse()
