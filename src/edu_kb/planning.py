"""Programmation annuelle (périodes) et progression hebdomadaire d'un niveau.

La programmation suit le programme : les périodes qu'il impose sont respectées (thèmes
d'histoire-géographie « deuxième et troisième périodes », objectifs de français « en fin de
période 1 », « en milieu d'année »…), le reste est réparti dans l'ordre du programme,
proportionnellement au nombre de semaines de chaque période. Chaque discipline est découpée en
fils parallèles (ses domaines : Lecture, Écriture… ; Histoire, Géographie…) ; dans un fil, les
unités (un thème, ou une rubrique quand le programme n'a pas de thèmes) se suivent.
C'est une proposition de départ, à ajuster : l'origine de chaque placement est indiquée.
"""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .graph import working_spans
from .kb import KnowledgeBase, normalize_level
from .outline import levels_of

# Disciplines dont les rubriques se travaillent toute l'année en parallèle (lecture, écriture, oral…) ;
# dans les autres, les unités d'un même fil se succèdent (un thème d'histoire, un champ d'EPS…).
MODES = {"Français": "continu", "Langues vivantes": "continu", "Éducation musicale": "continu"}

PERIOD_NAMES = {1: "Rentrée → Toussaint", 2: "Toussaint → Noël", 3: "Noël → hiver", 4: "Hiver → printemps", 5: "Printemps → été"}
# Échéances du programme qui disent « toute l'année » (en plus des disciplines travaillées en continu).
WHOLE_YEAR = re.compile(r"tout au long de l.ann|au cours des p[ée]riodes 1 [àa] 5|en cours d.ann", re.IGNORECASE)
LEAD_FIELDS = ("objectifs", "notions_competences", "connaissances", "connaissances_cm", "competences", "contenus",
               "attendus_fin_cycle", "reperes_programmation", "questionnements", "notions")


# --------------------------------------------------------------------------- calendrier
@dataclass
class Week:
    number: int  # rang dans l'année (1 = semaine de la rentrée)
    period: int
    rank: int  # rang dans la période
    monday: date
    days: list[date]

    @property
    def label(self) -> str:
        return f"P{self.period}-S{self.rank}"


def _d(value: str) -> date:
    return date.fromisoformat(value)


def school_weeks(calendar_file: Path, year: int, zone: str, weekdays: list[int] | None = None) -> list[Week]:
    """Semaines de classe de l'année, rangées par période (les semaines sans classe sont omises)."""
    with calendar_file.open("rb") as f:
        cal = tomllib.load(f)
    if str(year) not in cal:
        raise ValueError(f"Pas de calendrier pour la rentrée {year} dans {calendar_file} (années : {', '.join(cal)})")
    c = cal[str(year)]
    zone = zone.upper()
    if zone not in c.get("zones", {}):
        raise ValueError(f"Zone inconnue : {zone!r} (zones : {', '.join(c.get('zones', {}))})")
    z = c["zones"][zone]
    holidays = [c["toussaint"], c["noel"], z["hiver"], z["printemps"]]
    bounds = [_d(c["rentree"])] + [_d(h["reprise"]) for h in holidays]
    ends = [_d(h["debut"]) for h in holidays] + [_d(c["ete"])]
    off = {_d(x) for x in c.get("feries", [])}
    days_ok = set(weekdays or c.get("jours_de_classe", [1, 2, 4, 5]))
    weeks: list[Week] = []
    for p, (start, end) in enumerate(zip(bounds, ends), 1):
        monday = start - timedelta(days=start.weekday())
        rank = 0
        while monday < end:
            days = [monday + timedelta(days=i) for i in range(7)]
            days = [d for d in days if start <= d < end and d.isoweekday() in days_ok and d not in off]
            if days:
                rank += 1
                weeks.append(Week(len(weeks) + 1, p, rank, monday, days))
            monday += timedelta(days=7)
    return weeks


# --------------------------------------------------------------------------- unités
@dataclass
class Objective:
    text: str
    item_id: str
    span: tuple[int, int] | None = None  # périodes imposées par le programme
    moment: str | None = None
    weeks: list[int] = field(default_factory=list)
    continuous: bool = False  # travaillé toute l'année, sans échéance : listé à part, pas placé dans une semaine


@dataclass
class Unit:
    discipline: str
    strand: str
    title: str
    node_id: str
    kind: str  # theme | rubrique
    objectives: list[Objective] = field(default_factory=list)
    item_ids: list[str] = field(default_factory=list)
    periods: list[int] = field(default_factory=list)
    nb_periods: tuple[int, int] | None = None
    origin: str = "répartition proposée"
    weeks: list[int] = field(default_factory=list)
    question: str | None = None
    competences: list[str] = field(default_factory=list)
    source: str = ""
    always: bool = False  # unité sans objectif détaillé, travaillée toute l'année (discipline en continu)

    @property
    def continuous(self) -> bool:
        return self.always or (bool(self.objectives) and all(o.continuous for o in self.objectives))


@dataclass
class Plan:
    level: str
    year: int
    zone: str
    weeks: list[Week]
    units: list[Unit]
    sources: list[dict]

    def periods(self) -> dict[int, list[Week]]:
        out: dict[int, list[Week]] = {}
        for w in self.weeks:
            out.setdefault(w.period, []).append(w)
        return out


def _strand(chemin: list[str], unit_title: str) -> str:
    for title in chemin:
        if title == unit_title or levels_of(title) or re.match(r"^(principes|préambule)", title, re.IGNORECASE):
            continue
        return title
    return ""


def _lead_name(champs: dict) -> str:
    for name in LEAD_FIELDS:
        if champs.get(name):
            return name
    return next(iter(champs), "")


def _lead(champs: dict) -> list[dict]:
    return champs.get(_lead_name(champs), [])


def build_units(kb: KnowledgeBase, level: str, discipline: str, year: int) -> list[Unit]:
    units: list[Unit] = []
    by_key: dict[str, Unit] = {}
    items = kb.items_for(level, discipline, year)
    leads = {i["source_id"]: set() for i in items}
    for i in items:
        leads[i["source_id"]].add(_lead_name(i["data"].get("champs", {})))
    for item in items:
        lead = _lead_name(item["data"].get("champs", {}))
        # les tableaux « Compétences travaillées » décrivent le cycle, ce ne sont pas des contenus à programmer ;
        # les « Attendus de fin de cycle » non plus quand le programme détaille les contenus ailleurs
        if lead in ("competences", "socle") or (lead == "attendus_fin_cycle" and len(leads[item["source_id"]] - {"competences", "socle", "attendus_fin_cycle"}) > 0):
            continue
        themes = kb.neighbours(item["id"], "theme")
        parent = kb.neighbours(item["id"], "contient", reverse=True)
        chemin = item["data"].get("chemin", [])
        champs = item["data"].get("champs", {})
        if themes:
            head, kind = themes[0], "theme"
        else:
            head, kind = (parent[0] if parent else item), "rubrique"
        unit = by_key.get(head["id"])
        if unit is None:
            title = head["title"]
            if head["kind"] in ("niveau", "domaine", "section", "source"):
                # item placé directement sous un niveau : l'unité porte le nom du domaine
                title = _strand(chemin, "") or discipline
            if kind == "rubrique" and head["kind"] == "sous_rubrique":
                up = kb.neighbours(head["id"], "contient", reverse=True)
                if up and up[0]["kind"] == "rubrique":
                    title = f"{up[0]['title']} — {head['title']}"
            unit = Unit(discipline, _strand(chemin, head["title"]), title, head["id"], kind, source=item["source_id"],
                        question=head["data"].get("question"))
            hint = head["data"].get("periodes_programme")
            if hint and "periodes" in hint:
                unit.periods, unit.origin = sorted(hint["periodes"]), f"programme ({hint['texte']})"
            elif hint and "nb_periodes" in hint:
                unit.nb_periods, unit.origin = tuple(hint["nb_periodes"]), f"programme ({hint['texte']})"
            by_key[head["id"]] = unit
            units.append(unit)
        unit.item_ids.append(item["id"])
        lead = _lead(champs)
        spans = working_spans(lead)
        for b, span in zip(lead, spans):
            unit.objectives.append(Objective(b["texte"], item["id"], span, b.get("moment"),
                                             continuous=bool(b.get("moment") and WHOLE_YEAR.search(b["moment"]))))
        for name in ("attendus", "exemples_reussite", "notions_competences", "connaissances", "connaissances_cm"):
            unit.competences += [b["texte"] for b in champs.get(name, [])]
    for unit in units:
        fixed = sorted({p for o in unit.objectives if o.span for p in range(o.span[0], o.span[1] + 1)})
        if fixed and not unit.periods:
            unit.periods, unit.origin = fixed, "programme (échéances des objectifs)"
    return units


# --------------------------------------------------------------------------- répartition
def _allocate_periods(units: list[Unit]) -> None:
    """Périodes des unités d'un fil qui n'en ont pas reçu du programme."""
    todo = [u for u in units if not u.periods]
    if not todo:
        return
    if all(u.nb_periods for u in todo):
        # nombres de périodes donnés : on les enchaîne, en allongeant les fourchettes s'il reste de la place
        counts = [u.nb_periods[0] for u in todo]
        spare = 5 - sum(counts)
        for i, u in enumerate(todo):
            extra = min(spare, u.nb_periods[1] - u.nb_periods[0]) if spare > 0 else 0
            counts[i] += extra
            spare -= extra
        p = 1
        for u, n in zip(todo, counts):
            u.periods = [min(5, q) for q in range(p, p + max(1, n))]
            p += n
        return
    n = len(todo)
    for k, u in enumerate(todo):
        first = math.floor(k * 5 / n) + 1
        last = max(first, math.floor((k + 1) * 5 / n)) if n < 5 else first
        u.periods = list(range(first, min(5, last) + 1))
        if u.nb_periods:
            u.origin = "répartition proposée (" + u.origin + ")"


def _allocate_weeks(units: list[Unit], weeks: list[Week], parallel: bool = False) -> None:
    """Semaines des unités d'un fil. En parallèle, chaque unité occupe toutes les semaines de ses
    périodes ; sinon les unités d'une même période se partagent ses semaines, dans l'ordre."""
    by_period: dict[int, list[Week]] = {}
    for w in weeks:
        by_period.setdefault(w.period, []).append(w)
    for p, pweeks in by_period.items():
        active = [u for u in units if p in u.periods]
        if not active:
            continue
        if parallel:
            for u in active:
                u.weeks += [w.number for w in pweeks]
            continue
        for u, chunk in zip(active, _split_weeks(pweeks, [max(1, len(u.objectives)) / len(u.periods) for u in active])):
            u.weeks += [w.number for w in chunk]
    for u in units:
        u.weeks = sorted(set(u.weeks))
        _spread_objectives(u, weeks)


def _split_weeks(weeks: list[Week], weights: list[float]) -> list[list[Week]]:
    """Découpe les semaines d'une période en tranches consécutives, au prorata des poids.

    Plus d'unités que de semaines : plusieurs unités partagent une même semaine.
    """
    n, k = len(weeks), len(weights)
    if k >= n:
        return [[weeks[math.floor(i * n / k)]] for i in range(k)]
    # au moins une semaine chacune, le reste au plus fort reste
    total = sum(weights)
    raw = [(n - k) * w / total for w in weights]
    counts = [1 + math.floor(r) for r in raw]
    for i in sorted(range(k), key=lambda i: raw[i] - math.floor(raw[i]), reverse=True)[: n - sum(counts)]:
        counts[i] += 1
    out, cursor = [], 0
    for c in counts:
        out.append(weeks[cursor : cursor + c])
        cursor += c
    return out


def _spread_objectives(unit: Unit, weeks: list[Week]) -> None:
    if not unit.weeks:
        return
    period_of = {w.number: w.period for w in weeks}
    free = [o for o in unit.objectives if not o.span and not o.continuous]
    for o in unit.objectives:
        if o.continuous:
            continue
        if o.span:
            allowed = [w for w in unit.weeks if o.span[0] <= period_of[w] <= o.span[1]] or unit.weeks
            o.weeks = allowed
    if not free:
        return
    n, m = len(free), len(unit.weeks)
    if n >= m:
        for k, o in enumerate(free):
            o.weeks = [unit.weeks[math.floor(k * m / n)]]
    else:
        for k, o in enumerate(free):
            a, b = math.floor(k * m / n), math.floor((k + 1) * m / n)
            o.weeks = unit.weeks[a:max(a + 1, b)]


def build_plan(kb: KnowledgeBase, calendar_file: Path, level: str, year: int, zone: str,
               disciplines: list[str] | None = None, weekdays: list[int] | None = None) -> Plan:
    level = normalize_level(level)
    weeks = school_weeks(calendar_file, year, zone, weekdays)
    sources = kb.applicable_sources(level, year)
    names = [kb.resolve_discipline(d) for d in disciplines] if disciplines else sorted({s["discipline"] for s in sources})
    units: list[Unit] = []
    for name in names:
        dunits = build_units(kb, level, name, year)
        continuous = MODES.get(name) == "continu"
        strands: dict[str, list[Unit]] = {}
        for u in dunits:
            strands.setdefault(u.strand, []).append(u)
        for strand_units in strands.values():
            if continuous:
                for u in strand_units:
                    # sans échéance dans le programme, un objectif de ces disciplines se travaille toute l'année
                    # (sauf dans un thème dont le programme fixe les périodes)
                    for o in u.objectives:
                        o.continuous = o.continuous or (not o.span and not (u.kind == "theme" and u.periods))
                    if not u.periods:
                        u.periods, u.origin, u.always = [1, 2, 3, 4, 5], "toute l'année (compétence travaillée en continu)", not u.objectives
            else:
                _allocate_periods(strand_units)
            _allocate_weeks(strand_units, weeks, parallel=continuous)
        units += dunits
    return Plan(level, year, zone.upper(), weeks, units, sources)
