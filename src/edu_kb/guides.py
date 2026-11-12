"""Guides pédagogiques des méthodes suivies en classe : lecture des guides scannés et ajout au graphe.

Le choix des méthodes dépend de chaque classe : aucune n'est nommée ici. Chaque enseignant décrit
les siennes dans son guides.toml local (~/.edu-kb/guides.toml), par leur rythme :

- « jour » : le guide détaille chaque jour de classe (souvent une double page par jour, un fichier
  par période). Les jours se regroupent en leçons (« JOUR 1 », « JOUR 2 » d'un graphème, d'une
  révision, d'une lecture) et enchaînent des rituels et plusieurs séances (« SÉANCE 1 »… avec leur
  durée), découpées en phases (« MISE EN SITUATION », « MISE EN ACTIVITÉ »…).
- « semaine » : le guide propose une séquence par semaine, une séance par jour, dans l'ordre de son
  sommaire par période ; chaque séquence peut citer les objectifs du programme qu'elle travaille, et
  être suivie de rubriques de la semaine (atelier problèmes, calcul mental, flash maths).

Seul le vocabulaire courant des guides de l'enseignant est reconnu (séance, jour, période, phases,
carte repère, révision, rubriques) : une méthode dont le guide s'organise autrement demandera
d'ajuster son analyseur.

Graphe : guide → sequence_guide (séquence ou leçon) → [jour →] seance. Les liens `travaille`
(sequence_guide ou seance → objectif du programme) disent sur quelle partie du programme
s'appuie le guide : cités par le guide, ou rapprochés par le sens.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .config import find_file
from .graph import Graph, Node, slug
from .ocr_vision import OcrLine, OcrPage


# --------------------------------------------------------------------------- description
@dataclass(frozen=True)
class GuideFile:
    path: Path
    period: int | None


RHYTHMS = {
    "jour": "Tout est détaillé par jour de classe, avec plusieurs séances par jour.",
    "semaine": "Une séquence par semaine, une séance par jour.",
}


@dataclass(frozen=True)
class GuideSpec:
    id: str
    title: str
    discipline: str
    level: str
    rhythm: str  # « jour » ou « semaine » (RHYTHMS)
    files: list[GuideFile]
    programme_year: int | None = None  # rentrée du programme sur lequel s'appuie le guide
    description: str = ""

    @property
    def rhythm_text(self) -> str:
        return self.description or RHYTHMS[self.rhythm]


def load_guides(guides_file: Path, programmes_dir: Path) -> tuple[list[GuideSpec], list[str]]:
    """Charge le guides.toml de l'enseignant. Les fichiers sont cherchés dans `dossier` (relatif au
    fichier de configuration), sinon dans le dossier des programmes. Renvoie les guides dont tous les
    fichiers sont présents, et les avertissements."""
    with guides_file.open("rb") as f:
        data = tomllib.load(f)
    folder = programmes_dir
    if data.get("dossier"):
        folder = (guides_file.parent / Path(data["dossier"]).expanduser()).resolve()
    specs, warnings = [], []
    for raw in data.get("guide", []):
        if raw.get("rythme") not in RHYTHMS:
            raise ValueError(f"{guides_file} : guide {raw.get('id')!r}, rythme {raw.get('rythme')!r} inconnu "
                             f"(attendu : {', '.join(RHYTHMS)})")
        files, missing = [], []
        for entry in raw["fichiers"]:
            path = find_file(folder, entry["file"])
            if path is None:
                missing.append(entry["file"])
            else:
                files.append(GuideFile(path, entry.get("periode")))
        if missing:
            warnings.append(f"{raw['id']} : aucun fichier « {', '.join(missing)} » dans {folder}")
            continue
        specs.append(GuideSpec(raw["id"], raw["titre"], raw["discipline"], raw["niveau"], raw["rythme"],
                               files, raw.get("programme"), raw.get("description", "")))
    return specs, warnings


# --------------------------------------------------------------------------- structure lue
@dataclass
class Seance:
    kind: str  # séance, rituels, atelier problèmes, calcul mental, flash maths
    number: int | None
    title: str
    minutes: int | None = None
    lines: list[str] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)  # pages imprimées

    @property
    def phases(self) -> list[str]:
        return list(dict.fromkeys(m.group(1).capitalize() for t in self.lines if (m := PHASE.match(t))))

    @property
    def references(self) -> list[str]:
        """Renvois au manuel ou au fichier de l'élève (« P11 N1 », « P6 Ex1 »)."""
        refs = [m.group(0) for t in self.lines for m in REF.finditer(t)]
        return list(dict.fromkeys(re.sub(r"\s+", " ", r) for r in refs))


@dataclass
class Day:
    period: int
    rank: int  # rang du jour dans la période (1 = premier jour de classe de la période)
    day_in_unit: int  # JOUR 1, JOUR 2 de la leçon
    pages: list[int]
    seances: list[Seance] = field(default_factory=list)


@dataclass
class Unit:
    """Une séquence de maths (une semaine) ou une leçon de français (un graphème, une révision, une lecture)."""
    kind: str  # séquence, graphème, révision, lecture
    period: int
    number: int  # numéro dans le guide (séquences) ou rang dans la période (leçons)
    title: str
    domain: str = ""
    objectives: list[str] = field(default_factory=list)  # objectifs du programme cités par le guide
    days: list[Day] = field(default_factory=list)  # français
    seances: list[Seance] = field(default_factory=list)  # maths
    pages: list[int] = field(default_factory=list)
    atelier: str = ""  # maths : type de problèmes de l'atelier de la semaine
    calcul: str = ""  # maths : objectif de la séquence de calcul mental de la semaine
    calcul_objectives: list[str] = field(default_factory=list)

    @property
    def all_seances(self) -> list[Seance]:
        return self.seances + [s for d in self.days for s in d.seances]


# --------------------------------------------------------------------------- lecture des pages
PHASE = re.compile(r"^(MISE EN SITUATION|MISE EN ACTIVIT[ÉE]|MISE EN COMMUN|STRUCTURATION|ENTRA[IÎ]NEMENT|"
                   r"INSTITUTIONNALISATION|DIFF[ÉE]RENCIATION|PROLONGEMENTS?|RAPPEL DES ACQUIS|"
                   r"R[ée]activation|Mise en situation|Explicitation|Pratique guid[ée]e|Pratique autonome|"
                   r"Cl[ôo]ture de la s[ée]ance|Cl[ôo]ture de la s[ée]quence|Obstacles possibles|Consolidation|"
                   r"[ÉE]valuation)\b", re.IGNORECASE)  # « Bilan de la séquence » est le titre de la séance 4
REF = re.compile(r"\bP\s?\d{1,3}(?:-\d{1,3})?(?:\s+(?:N|Ex)\s?\d+(?:\s*(?:,|à)\s*\d+)*)?")
SEANCE = re.compile(r"^S[ÉE]ANCE\s*(\d{1,2})\b")
MINUTES = re.compile(r"(\d{1,3})\s*min(?:utes?)?\b")
BULLET = re.compile(r"^[•·+*●◦▪»\-–—]\s*")
LETTER = re.compile(r"[A-Za-zÀ-ÿ]")
LEFT_ALIGNED = re.compile(r"^([•·●]|MISE EN |ACTIVIT[ÉE] ?(ENSEIGNANT|[ÉE]L[ÈE]VE))")
COLUMN_MERGE = 0.08  # deux débuts de ligne plus proches sont dans la même colonne (retrait d'une sous-puce)
STOP_TITLE = re.compile(r"^(RITUELS|ACTIVIT[ÉE]|MAT[ÉE]RIEL|CALCUL CHRONO|[ÉE]CHAUFFEMENT)", re.IGNORECASE)


def _keep(line: OcrLine) -> bool:
    """Écarte ce que Vision lit dans les photos et les reproductions d'exercices."""
    text = line.text.strip()
    if line.conf < 0.5 or len(text) < 2:
        return False
    letters = len(LETTER.findall(text))
    return letters >= 3 or bool(re.fullmatch(r"[\d\s/+=−\-×:.,]+", text)) and len(text) >= 3


def column_starts(lines: list[OcrLine]) -> list[float]:
    """Abscisses de début des colonnes de texte.

    Les puces et les étiquettes (« MISE EN SITUATION », « ACTIVITÉ ENSEIGNANT ») sont toujours calées
    sur le bord gauche de leur colonne, alors que les intertitres (« Mise en situation ») et les
    encadrés sont centrés ou en retrait : seules les premières dessinent les colonnes."""
    xs = sorted(l.x0 for l in lines if l.conf >= 0.5 and LEFT_ALIGNED.match(l.text.strip()))
    starts: list[float] = []
    for x in xs:
        if sum(1 for y in xs if abs(y - x) <= 0.02) < 2:
            continue  # puce isolée (illustration, encadré en retrait)
        if not starts or x - starts[-1] > COLUMN_MERGE:
            starts.append(x)
    return [0.0] + starts[1:] if starts else [0.0]


def reading_order(page: OcrPage) -> list[OcrLine]:
    """Lignes dans l'ordre de lecture : colonne par colonne, de haut en bas."""
    lines = [l for l in page.lines if _keep(l)]
    starts = column_starts(lines)

    def column(l: OcrLine) -> int:
        return max((i for i, s in enumerate(starts) if l.x0 >= s - 0.02), default=0)

    return sorted(lines, key=lambda l: (column(l), l.y0))


def _join(lines: list[str]) -> list[str]:
    """Recolle les lignes coupées : une puce, un intertitre ou une phase commence une nouvelle ligne."""
    out: list[str] = []
    for text in lines:
        text = text.strip()
        starts_new = (not out or BULLET.match(text) or PHASE.match(text) or text[:1].isupper()
                      and (out[-1].endswith((".", "!", "?", ":")) or out[-1].isupper() or len(out[-1]) < 40))
        if starts_new:
            out.append(BULLET.sub("• ", text) if BULLET.match(text) else text)
        else:
            out[-1] = out[-1][:-1] + text if out[-1].endswith("-") and not out[-1].endswith(" -") else f"{out[-1]} {text}"
    return out


def _minutes(texts: list[str]) -> int | None:
    for t in texts:
        m = MINUTES.search(t)
        if m:
            return int(m.group(1))
    return None


def _heading_title(rest: list[OcrLine], start: int, max_lines: int = 3) -> tuple[str, int, int | None]:
    """Titre d'une séance : les lignes qui suivent « SÉANCE n » (sauf la durée), jusqu'à la première phase.
    Renvoie (titre, nombre de lignes consommées, durée)."""
    title: list[str] = []
    minutes = None
    i = start
    while i < len(rest) and len(title) < max_lines:
        text = rest[i].text.strip()
        if MINUTES.search(text) and len(text) < 20:
            minutes = minutes or _minutes([text])
            i += 1
            continue
        if PHASE.match(text) or SEANCE.match(text) or BULLET.match(text) or STOP_TITLE.match(text):
            break
        if title and rest[i].y0 - rest[i - 1].y1 > 0.04:
            break
        title.append(text)
        i += 1
    return " ".join(title).strip(" .:"), i - start, minutes


# --------------------------------------------------------------------------- guide par jour
PERIOD_MARK = re.compile(r"(?:P[ÉE]R[IÎ]ODE|D[ÉE]BIODE)\s*(\d)\b")  # « DÉBIODE » : « PÉRIODE » mal lu
PAGE_NUMBER = re.compile(r"(?:^|\s)(\d{1,3})$")
FOOTER_ZONE = 0.9  # le pied de page est sous cette ligne (mais tout ce qui y est n'en est pas)
JOUR = re.compile(r"^JOUR\b")
# Repères de leçon : vocabulaire courant des guides de lecture (cartes repères des graphèmes,
# révisions, lectures d'albums, de contes, de documentaires…).
CARTE = re.compile(r"^Cartes? rep[èe]res?\s+(.+)$")
PHONEME = re.compile(r"^Phon[èe]mes?\s+(.+)$")
LESSON = re.compile(r"^(R[ée]vision\s*\d+|Lire (?:un|une|les)\b.*)$")
REVISION_LABEL = re.compile(r"R[ÉE]VISIONS?\s*(\d+)")
ANNEX = re.compile(r"^R[ée]pertoire")


def _grapheme(label: str) -> str:
    """« Ol » → « OI », « W@ ŒU » → « W Œ ŒU » : les graphèmes sont en capitales, un « l » y est un « I »."""
    label = re.sub(r"\s*@\s*", " Œ ", label)  # Vision lit « Œ » comme « @ »
    words = [w for w in re.split(r"\s+", label.strip()) if w]
    return " ".join(w.replace("l", "I").replace("0", "O") if w[:1].isupper() else w for w in words)


def _letters(text: str) -> str:
    return re.sub(r"[\W\d_]+", "", text.upper())


def _covers(running: str, key: str) -> bool:
    """`key` est-il (une partie de) `running`, aux erreurs de lecture près ?"""
    if len(key) < 8:
        return False
    blocks = SequenceMatcher(None, key, running, autojunk=False).get_matching_blocks()
    return max(b.size for b in blocks) >= 6 and sum(b.size for b in blocks) >= 0.8 * len(key)


def running_footer(pages: list[OcrPage]) -> str:
    """Titre courant du pied de page d'un fichier (« PÉRIODE n | GUIDE … » sans ses chiffres) : parmi
    les textes du bas des pages, celui qui recouvre le plus des autres (souvent tronqués ou mal lus).
    Rien n'est supposé de son contenu."""
    keys = [_letters(l.text) for p in pages for l in p.lines if l.y0 > FOOTER_ZONE and len(_letters(l.text)) >= 10]
    best, score = "", 0
    for candidate in sorted(Counter(keys), key=len, reverse=True):
        covered = sum(1 for k in keys if _covers(candidate, k))
        if covered > score:
            best, score = candidate, covered
    return best if score >= max(2, len(pages) // 3) else ""


def is_footer(line: OcrLine, running: str) -> bool:
    """Ligne du pied de page : le titre courant (même tronqué ou mal lu), ou un numéro de page seul dans
    un coin. Le texte d'une page mal cadrée qui descend jusqu'en bas reste du texte."""
    if line.y0 <= FOOTER_ZONE:
        return False
    text = line.text.strip()
    if text.isdigit() and (line.x0 < 0.08 or line.x1 > 0.92):
        return True
    return bool(running) and _covers(running, _letters(text))


def _footer(page: OcrPage, running: str) -> tuple[int | None, int | None]:
    """(période, page imprimée de droite) lues dans le pied de page : le numéro de la page de droite
    termine le pied de page, à droite (sinon : numéro de la page de gauche + 1)."""
    period = right = left = None
    for l in page.lines:
        if not is_footer(l, running):
            continue
        text = l.text.strip()
        if m := PERIOD_MARK.search(text):
            period = period or int(m.group(1))
        if m := PAGE_NUMBER.search(text):
            if l.x0 >= 0.5:
                right = right or int(m.group(1))
            elif text.isdigit():
                left = left or int(text)
    return period, right or (left + 1 if left else None)


def _spread_markers(page: OcrPage) -> dict:
    """Ce qui situe une double page : leçon (graphème, révision, lecture), annexe."""
    lines = [l for l in page.lines if l.conf >= 0.5]
    out: dict = {}
    for l in sorted(lines, key=lambda l: (l.y0, l.x0)):
        text = l.text.strip()
        if "carte" not in out and (m := CARTE.match(text)):
            out["carte"] = _grapheme(m.group(1))
        elif "phoneme" not in out and (m := PHONEME.match(text)):
            out["phoneme"] = _grapheme(m.group(1))
        elif "lecon" not in out and l.y0 < 0.12 and l.x0 < 0.3 and (m := LESSON.match(text)):
            out["lecon"] = re.sub(r"\s+", " ", m.group(1)).strip()
        elif "annexe" not in out and l.y0 < 0.12 and ANNEX.match(text):
            out["annexe"] = text
        elif "revision" not in out and (m := REVISION_LABEL.search(text)):
            out["revision"] = int(m.group(1))
    return out


def _seances_of(lines: list[OcrLine], page_numbers: list[int], kind: str = "séance",
                heading: re.Pattern = SEANCE, footer: str = "") -> tuple[list[str], list[Seance]]:
    """Découpe un texte aux titres « SÉANCE n » (ou `heading`) et « RITUELS », sans le pied de page
    (`footer` : titre courant). Renvoie (lignes avant la première séance, séances)."""
    seances: list[Seance] = []
    intro: list[str] = []
    current: Seance | None = None
    i = 0
    while i < len(lines):
        text = lines[i].text.strip()
        if JOUR.match(text) or is_footer(lines[i], footer):
            i += 1
            continue
        m = heading.match(text)
        if m or re.match(r"^RITUELS\b", text):
            title, used, minutes = _heading_title(lines, i + 1)
            if m:
                label = m.group(1) or ""
                number = int(label) if label.isdigit() else ord(label.upper()) - 64 if label else len(seances) + 1
                current = Seance(kind, number, title, minutes, pages=list(page_numbers))
            else:
                current = Seance("rituels", None, "Rituels", minutes, pages=list(page_numbers))
                used = sum(1 for k in range(i + 1, min(i + 2, len(lines))) if MINUTES.search(lines[k].text) and len(lines[k].text) < 20)
            seances.append(current)
            i += 1 + used
            continue
        (current.lines if current else intro).append(text)
        i += 1
    for s in seances:
        s.lines = _join(s.lines)
    return _join(intro), seances


def _same_spread(a: set[str], b: set[str]) -> bool:
    """Deux lectures de la même double page (rescannée) : la plupart de leurs lignes sont identiques."""
    return bool(a and b) and len(a & b) >= 0.5 * min(len(a), len(b))


def parse_daily_guide(files: list[tuple[GuideFile, list[OcrPage]]], log=None) -> tuple[list[Unit], list[dict]]:
    """Leçons et jours d'un guide qui détaille chaque jour de classe, période par période.
    Renvoie (leçons, annexes).

    Une double page n'est écartée comme doublon que si elle porte le même numéro de page imprimée, le
    même repère de leçon (graphème, révision, titre de la lecture) et le même texte qu'une double page
    déjà lue (la fin d'un fichier rescannée au début du suivant) : deux albums ou deux leçons
    différents ne sont jamais confondus."""
    units: list[Unit] = []
    annexes: list[dict] = []
    read: dict[int, tuple[dict, set[str]]] = {}  # page imprimée de droite → repères et lignes déjà lus
    for gfile, pages in files:
        running = running_footer(pages)
        previous: int | None = None  # page de droite de la double page précédente du fichier
        for page in pages:
            period, right = _footer(page, running)
            period = period if period in (1, 2, 3, 4, 5) else gfile.period
            if right and previous and not previous < right <= previous + 6:
                right = None  # numéro mal lu : les pages d'un fichier se suivent
            if right is None and previous:
                right = previous + 2  # pied de page illisible : la double page suit la précédente
            previous = right
            printed = [right - 1, right] if right else []
            marks = _spread_markers(page)
            texts = {l.text.strip() for l in page.lines if l.conf >= 1.0 and len(l.text.strip()) > 15 and l.y0 < 0.9}
            if right in read and read[right][0] == marks and _same_spread(read[right][1], texts):
                if log:
                    log(f"    pages {right - 1}-{right} lues deux fois ({gfile.path.name}, double page {page.number}) : doublon ignoré")
                continue
            if right:
                read[right] = (marks, texts)
            if "annexe" in marks:
                annexes.append({"titre": marks["annexe"], "periode": period, "pages": printed})
                continue
            intro, seances = _seances_of(reading_order(page), printed, footer=running)
            if not any(s.kind in ("séance", "rituels") for s in seances):
                continue
            if sum(len(t) for t in intro) >= 120:
                # présentation d'une lecture, ou début de journée dont le titre n'a pas été lu (scan rogné)
                seances.insert(0, Seance("introduction", None, "Introduction", lines=intro, pages=printed))
            numbered = [s.number for s in seances if s.kind == "séance" and s.number]
            if log and numbered and min(numbered) > 1:
                where = f"pages {'-'.join(map(str, printed))}" if printed else f"double page {page.number} de {gfile.path.name}"
                log(f"    {where} (période {period}) : titre « SÉANCE 1 » non lu (scan rogné ?), "
                    f"son texte est dans l'introduction du jour")
            last = units[-1] if units else None
            same_period = last is not None and last.period == period
            grapheme = marks.get("carte") or marks.get("phoneme")
            if grapheme:
                kind, title = "graphème", f"Graphème{'s' if ' ' in grapheme else ''} {grapheme}"
            elif "lecon" in marks:
                lecon = marks["lecon"]
                kind, title = ("révision", lecon.capitalize()) if lecon.lower().startswith("r") else ("lecture", lecon)
            elif "revision" in marks:
                kind, title = "révision", f"Révision {marks['revision']}"
            else:
                kind, title = (last.kind, last.title) if same_period else ("leçon", "Leçon")
            if not (same_period and last.title == title):
                units.append(Unit(kind, period, sum(1 for u in units if u.period == period) + 1, title))
            unit = units[-1]
            rank = sum(len(u.days) for u in units if u.period == period) + 1
            unit.days.append(Day(period, rank, len(unit.days) + 1, printed, seances))
            unit.pages += printed
    return units, annexes


# --------------------------------------------------------------------------- guide par semaine
OBJECTIFS = re.compile(r"^OBJECTIFS? D.APPRENTISSAGE", re.IGNORECASE)
PERIODE = re.compile(r"^P[ÉE]RIODE\s*(\d)\b")
# Rubriques de la semaine qui suivent les séances d'une séquence, repérées par les mots en tête de
# leur page ; les rubriques par jour (flash maths A, B, C, D) sont des intertitres dans une colonne.
RUBRICS = [("atelier problèmes", ("ATELIER",)), ("calcul mental", ("CALCUL", "MENTAL"))]
FLASH = re.compile(r"^FLASH MATHS\s*([A-D])?\b")
HEADER_BOTTOM = 0.125  # bas du bandeau d'en-tête d'une séquence (titre et objectifs)
TITLE_BOTTOM = 0.065  # le titre est au-dessus, les objectifs cités en dessous


def _find_sommaire(pages: list[OcrPage]) -> OcrPage | None:
    """Le sommaire par période : une page du début qui commence par « Sommaire » et liste des périodes."""
    for page in pages[:15]:
        texts = [l.text.strip() for l in page.lines if l.conf >= 0.5]
        if any(t.startswith("Sommaire") for t in texts) and sum(1 for t in texts if PERIODE.match(t)) >= 2:
            return page
    return None


def _sommaire_plan(page: OcrPage, last_page: int) -> list[tuple[int, int]]:
    """(période, page de début) de chaque séquence, dans l'ordre du sommaire par période.

    Les numéros de page d'un sommaire sont alignés à droite, en colonnes : on garde les nombres dont
    le bord droit s'aligne sur celui d'au moins deux autres (les numéros de séquence, eux, sont collés
    aux titres ou isolés)."""
    lines = [l for l in page.lines if l.conf >= 0.5]
    periods = sorted((l.y0, int(m.group(1))) for l in lines if (m := PERIODE.match(l.text.strip())))
    numbers = sorted((l for l in lines if re.fullmatch(r"\d{1,3}", l.text.strip())
                      and page.number < int(l.text) <= last_page), key=lambda l: l.x1)
    columns: list[list[OcrLine]] = []
    for l in numbers:
        if columns and l.x1 - columns[-1][-1].x1 <= 0.015:
            columns[-1].append(l)
        else:
            columns.append([l])
    starts = []
    for c, column in enumerate(col for col in columns if len(col) >= 3):
        for l in column:
            period = next((p for y, p in reversed(periods) if y < l.y0), None)
            if period:
                starts.append((period, c, l.y0, int(l.text)))
    return [(period, number) for period, _, _, number in sorted(starts)]


def _period_page(page: OcrPage) -> bool:
    """Page de présentation d'une période : « PÉRIODE » en tête, sans séance."""
    texts = [l.text.strip() for l in page.lines if l.conf >= 0.5]
    return any(PERIODE.match(t) or t == "PÉRIODE" for t in texts[:12]) and not any(SEANCE.match(t) for t in texts)


def _clean_title(text: str) -> str:
    return re.sub(r"\s*[®*%°©]+$", "", re.sub(r"\s+", " ", text)).strip(" .:")


def _header(lines: list[OcrLine], y_max: float, sequence: bool = False) -> tuple[list[OcrLine], str, list[str]]:
    """En-tête d'une page de séquence, d'atelier ou de calcul mental : (lignes de l'en-tête, titre, objectifs cités)."""
    head = [l for l in lines if l.y0 < min(y_max, HEADER_BOTTOM) and 0.1 <= l.x0 < 0.8 and l.y0 > 0.025]
    obj = next((l for l in head if OBJECTIFS.match(l.text.strip())), None)
    if obj is None and sequence:  # bandeau « OBJECTIFS D'APPRENTISSAGE » non lu : il est sous le titre
        obj = OcrLine("OBJECTIFS", 1.0, min((l.x0 for l in head), default=0.14), TITLE_BOTTOM, 0.5, TITLE_BOTTOM)
    titles, objectives, used = [], [], []
    for l in sorted(head, key=lambda l: l.y0):
        text = l.text.strip()
        if re.fullmatch(r"FLASH|MATHS", text):
            continue  # bandeau des flash maths de la même page : lu avec eux
        used.append(l)
        if l is obj or re.fullmatch(r"(CALCUL|MENTAL|ATELIER|PROBL[ÈE]MES|\d+|.{0,3})", text) or re.search(r"PROGRAMME \d{4}", text):
            continue
        if obj is not None and l.y0 > obj.y0 and abs(l.x0 - obj.x0) < 0.03:
            if objectives and (text[:1].islower() or text.startswith("(")):
                objectives[-1] += " " + text
            else:
                objectives.append(text)
        else:
            titles.append(text)
    return used, _clean_title(" ".join(titles)), [o.rstrip(" .") for o in objectives]


def _first_heading_y(lines: list[OcrLine], pattern: re.Pattern = SEANCE) -> float:
    ys = [l.y0 for l in lines if pattern.match(l.text.strip())]
    return min(ys) if ys else 0.125


def parse_weekly_guide(pages: list[OcrPage]) -> list[Unit]:
    """Les séquences d'un guide qui en propose une par semaine (une séance par jour), avec leurs séances.

    Une séquence va de sa première page (lue dans le sommaire par période) à sa page de flash maths,
    ou à la séquence suivante ; les pages de présentation des périodes ne sont pas lues."""
    by_number = {p.number: p for p in pages}
    sommaire = _find_sommaire(pages)
    if sommaire is None:
        raise ValueError("guide par semaine : sommaire par période introuvable dans les premières pages")
    plan = _sommaire_plan(sommaire, max(by_number))
    units: list[Unit] = []
    for k, (period, start) in enumerate(plan, 1):
        end = plan[k][1] if k < len(plan) else max(by_number) + 1
        block = [by_number[n] for n in range(start, end) if n in by_number]
        unit = Unit("séquence", period, k, "")
        mode = "séance"
        flash_title = ""
        for page in block:
            if page.number != start and _period_page(page):
                break  # présentation de la période suivante
            unit.pages.append(page.number)
            lines = [l for l in reading_order(page) if 0.025 < l.y0 < 0.95]
            top = [l.text.strip() for l in page.lines if l.y0 < 0.08]
            new_mode = next((kind for kind, words in RUBRICS if all(w in top for w in words)), None)
            consumed: list[OcrLine] = []
            if page.number == start:
                consumed, unit.title, unit.objectives = _header(lines, _first_heading_y(lines), sequence=True)
            elif new_mode == "calcul mental":
                consumed, unit.calcul, unit.calcul_objectives = _header(lines, _first_heading_y(lines))
            elif new_mode == "atelier problèmes":
                consumed, unit.atelier, _ = _header(lines, _first_heading_y(lines))
            lines = [l for l in lines if l not in consumed]
            flash_at = next((i for i, l in enumerate(lines) if l.text.strip() == "FLASH" or FLASH.match(l.text.strip())), None)
            body, flash = (lines[:flash_at], lines[flash_at:]) if flash_at is not None else (lines, [])
            intro, seances = _seances_of(body, [page.number], new_mode or mode)
            if new_mode:
                mode = new_mode
                if seances:  # matériel de l'atelier, échauffement : début de la première séance de la page
                    seances[0].lines = intro + seances[0].lines
            elif unit.seances:  # le haut de la page continue la séance de la page précédente
                unit.seances[-1].lines += intro
                if intro and page.number not in unit.seances[-1].pages:
                    unit.seances[-1].pages.append(page.number)
            for s in seances:
                if s.kind == "rituels" and unit.seances:
                    unit.seances[-1].lines += s.lines
                elif unit.seances and (unit.seances[-1].kind, unit.seances[-1].number) == (s.kind, s.number):
                    unit.seances[-1].lines += s.lines  # même séance, titre répété ou mal découpé
                    unit.seances[-1].pages = sorted(set(unit.seances[-1].pages + s.pages))
                else:
                    unit.seances.append(s)
            if flash:
                rest = [l for l in flash if l.text.strip() not in ("FLASH", "MATHS")]
                topic, flashes = _seances_of(rest, [page.number], "flash maths", heading=FLASH)
                flash_title = flash_title or (topic[0] if topic else "")
                for s in flashes:
                    s.title = flash_title
                unit.seances += flashes
                break  # la séquence finit avec ses flash maths
        unit.title = unit.title or f"Séquence {k}"
        for s in unit.seances:
            if s.kind == "atelier problèmes" and not s.title:
                s.title = unit.atelier
            elif s.kind == "calcul mental" and unit.calcul:
                s.title = f"{unit.calcul} — {s.title}" if s.title else unit.calcul
        units.append(unit)
    _number_duplicates(units)
    return units


def _number_duplicates(units: list[Unit]) -> None:
    """Deux séquences au même titre (« … ① » et « … ② », exposant mal lu) : on les numérote (1) et (2)."""
    groups: dict[str, list[Unit]] = {}
    for u in units:
        groups.setdefault(_norm(re.sub(r"\s*\d$", "", u.title)), []).append(u)
    for same in groups.values():
        if len(same) > 1:
            base = re.sub(r"(?<=\D)\s*[12]$|(?<=99)[12]$", "", same[0].title).strip()
            for i, u in enumerate(same, 1):
                u.title = f"{base} ({i})"


# --------------------------------------------------------------------------- correspondance au programme
def _norm(text: str) -> str:
    text = re.sub(r"[’'`«»]", " ", text)  # « jusqu’à » : sans cela, l'apostrophe typographique colle les mots
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


NUMBERS = {"10": "dix", "20": "vingt", "100": "cent", "1000": "mille"}
STOP = set("a au aux d de des du en et l la le les ou un une sur dans par pour avec son sa ses leur".split())


def _words(text: str) -> set[str]:
    return {NUMBERS.get(w, w) for w in _norm(text).split()} - STOP


def objective_score(cited: str, objective: str) -> float:
    """Ressemblance entre un objectif cité par le guide et un objectif du programme.

    Le guide reprend le texte du programme mot pour mot, mais en coupe parfois une partie
    (« Connaitre la suite orale des nombres jusqu'à 100 » pour « … la suite écrite et la suite orale
    des nombres jusqu'à cent ») : on prend le meilleur de la ressemblance des textes et de
    l'inclusion des mots de l'un dans l'autre (sur 4 mots pleins au moins)."""
    ratio = SequenceMatcher(None, _norm(cited), _norm(objective)).ratio()
    a, b = _words(cited), _words(objective)
    inclusion = max((len(a & b) / len(x) for x in (a, b) if len(x) >= 4), default=0.0)
    return max(ratio, inclusion)


def match_objectives(cited: list[str], objectives: list[Node], threshold: float = 0.85) -> list[tuple[str, Node, float]]:
    """Objectifs du programme que le guide cite (mot pour mot ou en partie, aux erreurs d'OCR près)."""
    out = []
    for text in cited:
        scored = [(objective_score(text, node.title), node) for node in objectives]
        score, best = max(scored, key=lambda x: x[0], default=(0.0, None))
        if best is not None and score >= threshold:
            out.append((text, best, round(score, 2)))
    return out


# --------------------------------------------------------------------------- graphe
def _seance_text(unit: Unit, s: Seance, day: Day | None) -> str:
    where = f"{unit.title}" + (f" · jour {day.day_in_unit}" if day else "")
    head = f"{s.kind.capitalize()} {s.number}" if s.number else s.kind.capitalize()
    return f"{where} › {head} : {s.title}\n" + "\n".join(s.lines)


def _applies(g: Graph, source_id: str, level: str, year: int | None) -> bool:
    """Le programme `source_id` s'applique-t-il à ce niveau à la rentrée `year` ?"""
    if year is None:
        return True
    rule = g.nodes[f"source:{source_id}"].data.get("application", {}).get(level)
    return rule is not None and rule["depuis"] <= year and (rule["jusqu_a"] is None or year < rule["jusqu_a"])


def add_guide(g: Graph, spec: GuideSpec, units: list[Unit], extra: dict | None = None,
              position: int = 10_000_000) -> int:
    """Ajoute un guide au graphe. Renvoie la dernière position utilisée (ordre de lecture)."""
    gid = f"guide:{spec.id}"
    disc = f"discipline:{slug(spec.discipline)}"
    level = f"niveau:{spec.level}"
    g.add(Node(gid, "guide", spec.title, text=spec.rhythm_text, discipline=spec.discipline, levels=[spec.level],
               source_id=spec.id, position=position,
               data={"rythme": spec.rhythm, "description": spec.rhythm_text, "fichiers": [f.path.name for f in spec.files],
                     "programme": spec.programme_year,
                     "periodes": sorted({u.period for u in units}), **(extra or {})}))
    g.link(gid, "discipline", disc)
    g.link(gid, "niveau", level)
    objectives = [n for n in g.nodes.values() if n.kind == "objectif" and n.discipline == spec.discipline
                  and spec.level in n.levels and _applies(g, n.source_id, spec.level, spec.programme_year)]
    for unit in units:
        position += 1
        uid = f"{gid}/p{unit.period}/{slug(unit.kind, 12)}-{unit.number}"
        context = f"{spec.title} › Période {unit.period} › {unit.title}"
        data = {"type": unit.kind, "periode": unit.period, "numero": unit.number, "pages": sorted(set(unit.pages)),
                "contexte": context, "chemin": [spec.title, f"Période {unit.period}", unit.title]}
        if unit.domain:
            data["domaine"] = unit.domain
        if unit.objectives:
            data["objectifs_programme"] = unit.objectives
        if unit.atelier:
            data["atelier_problemes"] = unit.atelier
        if unit.calcul:
            data["calcul_mental"] = unit.calcul
        if unit.calcul_objectives:
            data["objectifs_calcul_mental"] = unit.calcul_objectives
        if unit.days:
            data["jours"] = [d.rank for d in unit.days]
        summary = ([unit.title] + unit.objectives + ([f"Atelier problèmes : {unit.atelier}"] if unit.atelier else [])
                   + ([f"Calcul mental : {unit.calcul}"] if unit.calcul else [])
                   + [f"{s.kind} {s.number or ''} : {s.title}" for s in unit.all_seances])
        g.add(Node(uid, "sequence_guide", unit.title, text="\n".join(summary), discipline=spec.discipline,
                   levels=[spec.level], source_id=spec.id, page=min(unit.pages) if unit.pages else None,
                   position=position, data=data))
        g.link(gid, "contient", uid)
        g.link(uid, "discipline", disc)
        g.link(uid, "niveau", level)
        for cited, origin in ((unit.objectives, "objectif cité par le guide"),
                              (unit.calcul_objectives, "objectif du calcul mental cité par le guide")):
            for text, node, score in match_objectives(cited, objectives):
                key = (uid, "travaille", node.id)
                if key not in g.edges:
                    g.link(uid, "travaille", node.id, {"origine": origin, "cite": text, "similarite": score})
        containers: list[tuple[str, Day | None, list[Seance]]] = []
        for day in unit.days:
            position += 1
            did = f"{uid}/j{day.day_in_unit}"
            g.add(Node(did, "jour", f"{unit.title} — jour {day.day_in_unit}",
                       text="\n".join(f"{s.title}" for s in day.seances), discipline=spec.discipline,
                       levels=[spec.level], source_id=spec.id, page=min(day.pages) if day.pages else None,
                       position=position,
                       data={"periode": day.period, "jour_periode": day.rank, "jour_lecon": day.day_in_unit,
                             "pages": day.pages, "contexte": context}))
            g.link(uid, "contient", did)
            containers.append((did, day, day.seances))
        if unit.seances:
            containers.append((uid, None, unit.seances))
        for parent, day, seances in containers:
            for k, s in enumerate(seances, 1):
                position += 1
                sid = f"{parent}/s{k}"
                label = f"{s.kind.capitalize()} {s.number}" if s.number else s.kind.capitalize()
                sdata = {"type": s.kind, "numero": s.number, "duree_minutes": s.minutes, "phases": s.phases,
                         "references": s.references, "pages": s.pages, "periode": unit.period,
                         "contexte": f"{context}" + (f" › Jour {day.day_in_unit}" if day else "") + f" › {label}",
                         "deroule": s.lines}
                if day:
                    sdata["jour_periode"] = day.rank
                if unit.kind == "séquence":
                    sdata["sequence"] = unit.number
                g.add(Node(sid, "seance", f"{label} — {s.title}" if s.title and s.title != label else label,
                           text=_seance_text(unit, s, day), discipline=spec.discipline, levels=[spec.level],
                           source_id=spec.id, page=min(s.pages) if s.pages else None, position=position, data=sdata))
                g.link(parent, "contient", sid)
                g.link(sid, "discipline", disc)
                g.link(sid, "niveau", level)
    return position
