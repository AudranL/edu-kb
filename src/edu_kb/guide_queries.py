"""Requêtes sur les guides pédagogiques : liste, fiches, recherche, et place dans le calendrier.

Le calendrier suit le rythme de chaque guide, période par période :
- « semaine » : une séquence par semaine. La k-ième séquence d'une période va sur la k-ième semaine
  de classe de cette période ; la séance n (et le calcul mental n, le flash maths n) sur le n-ième
  jour de classe de la semaine. Les autres rubriques (atelier problèmes) sont données pour la semaine.
- « jour » : un jour du guide par jour de classe. Le k-ième jour d'une période va sur le k-ième
  jour de classe de la période.
C'est une proposition : les jours ou semaines de classe sans contenu prévu (évaluations,
rattrapage) et les contenus qui dépassent la période sont signalés.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .kb import GUIDE_KINDS, KnowledgeBase, school_year
from .planning import PERIOD_NAMES, Week, school_weeks

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DAY_KINDS = ("séance", "calcul mental", "flash maths")  # maths : un par jour de la semaine


def has_guides(kb: KnowledgeBase) -> bool:
    with kb._conn() as con:
        return con.execute("SELECT 1 FROM nodes WHERE kind = 'guide' LIMIT 1").fetchone() is not None


def _nodes(kb: KnowledgeBase, sql: str, args: tuple = ()) -> list[dict]:
    with kb._conn() as con:
        return [kb._row(r) for r in con.execute(sql, args)]


def _children(kb: KnowledgeBase, node_id: str) -> list[dict]:
    return kb.neighbours(node_id, "contient")


def guides(kb: KnowledgeBase) -> list[dict]:
    out = []
    for g in _nodes(kb, "SELECT * FROM nodes WHERE kind = 'guide' ORDER BY position"):
        units = _children(kb, g["id"])
        with kb._conn() as con:
            n = {r["kind"]: r["n"] for r in con.execute(
                "SELECT kind, COUNT(*) AS n FROM nodes WHERE source_id = ? GROUP BY kind", (g["source_id"],))}
        out.append({"id": g["id"], "titre": g["title"], "discipline": g["discipline"], "niveau": g["levels"],
                    "rythme": g["data"].get("rythme"), "description": g["data"].get("description"),
                    "programme": g["data"].get("programme"),
                    "periodes": {p: [u["title"] for u in units if u["data"]["periode"] == p] for p in g["data"].get("periodes", [])},
                    "sequences_ou_lecons": len(units), "jours": n.get("jour", 0), "seances": n.get("seance", 0),
                    "fichiers": g["data"].get("fichiers")})
    return out


# --------------------------------------------------------------------------- fiches
def _programme_links(kb: KnowledgeBase, node_id: str) -> list[dict]:
    out = []
    for o in kb.neighbours(node_id, "travaille"):
        items = [p for p in kb.neighbours(o["id"], "contient", reverse=True) if p["kind"] == "item"]
        source = kb.node(f"source:{o['source_id']}")
        out.append({"id": o["id"], "objectif": o["title"], "item": items[0]["id"] if items else None,
                    "contexte": o["data"].get("contexte"), "origine": (o.get("edge_data") or {}).get("origine"),
                    "similarite": (o.get("edge_data") or {}).get("similarite"),
                    "source": {"titre": source["title"], "bo": source["data"].get("bo"), "page": o["page"]} if source else None})
    return sorted(out, key=lambda x: (x["origine"] != "objectif cité par le guide", -(x["similarite"] or 0)))


def _path(kb: KnowledgeBase, node: dict) -> list[dict]:
    """Ancêtres d'un nœud de guide : guide, séquence ou leçon, jour."""
    out = []
    cur = node
    while True:
        parents = [p for p in kb.neighbours(cur["id"], "contient", reverse=True) if p["kind"] in ("guide",) + GUIDE_KINDS + ("jour",)]
        if not parents:
            return list(reversed(out))
        cur = parents[0]
        out.append(cur)


def _seance_summary(s: dict) -> dict:
    d = s["data"]
    return {"id": s["id"], "titre": s["title"], "type": d.get("type"), "numero": d.get("numero"),
            "duree_minutes": d.get("duree_minutes"), "pages": d.get("pages")}


def guide_card(kb: KnowledgeBase, node_id: str) -> dict | None:
    """Fiche d'un nœud de guide : séance (déroulé complet), jour, séquence ou leçon, guide."""
    node = kb.node(node_id)
    if node is None:
        return None
    guide = kb.node(f"guide:{node['source_id']}")
    base = {"id": node_id, "type": node["kind"], "titre": node["title"], "discipline": node["discipline"],
            "niveaux": node["levels"], "guide": guide["title"] if guide else node["source_id"],
            "contexte": node["data"].get("contexte"), "pages_du_guide": node["data"].get("pages")}
    if node["kind"] == "guide":
        return next((g for g in guides(kb) if g["id"] == node_id), base)
    if node["kind"] == "seance":
        d = node["data"]
        parents = _path(kb, node)
        unit = next((p for p in parents if p["kind"] == "sequence_guide"), None)
        return {**base, "seance": {"type": d.get("type"), "numero": d.get("numero"), "duree_minutes": d.get("duree_minutes"),
                                   "phases": d.get("phases"), "references_manuel": d.get("references")},
                "deroule": d.get("deroule", []),
                "programme": _programme_links(kb, node_id),
                "programme_de_la_sequence": _programme_links(kb, unit["id"]) if unit else [],
                "periode": d.get("periode"), "jour_de_la_periode": d.get("jour_periode"), "sequence": d.get("sequence")}
    if node["kind"] == "jour":
        seances = [s for s in _children(kb, node_id) if s["kind"] == "seance"]
        return {**base, "periode": node["data"].get("periode"), "jour_de_la_periode": node["data"].get("jour_periode"),
                "jour_de_la_lecon": node["data"].get("jour_lecon"), "seances": [_seance_summary(s) for s in seances],
                "programme": _merge([_programme_links(kb, s["id"]) for s in seances])}
    if node["kind"] == "sequence_guide":
        d = node["data"]
        kids = _children(kb, node_id)
        days = [k for k in kids if k["kind"] == "jour"]
        seances = [k for k in kids if k["kind"] == "seance"] + [s for j in days for s in _children(kb, j["id"]) if s["kind"] == "seance"]
        return {**base, "periode": d.get("periode"), "numero": d.get("numero"), "type_unite": d.get("type"),
                "objectifs_cites": d.get("objectifs_programme", []), "atelier_problemes": d.get("atelier_problemes"),
                "calcul_mental": d.get("calcul_mental"), "objectifs_calcul_mental": d.get("objectifs_calcul_mental", []),
                "jours": [{"id": j["id"], "titre": j["title"], "jour_de_la_periode": j["data"].get("jour_periode"),
                           "seances": [_seance_summary(s) for s in _children(kb, j["id"]) if s["kind"] == "seance"]} for j in days],
                "seances": [_seance_summary(s) for s in kids if s["kind"] == "seance"],
                "programme": _merge([_programme_links(kb, node_id)] + [_programme_links(kb, s["id"]) for s in seances])}
    return base


def _merge(groups: list[list[dict]]) -> list[dict]:
    """Objectifs du programme d'un ensemble de séances, sans doublon, les plus cités d'abord."""
    seen: dict[str, dict] = {}
    for links in groups:
        for link in links:
            entry = seen.setdefault(link["id"], {**link, "seances": 0})
            entry["seances"] += 1
            if link["origine"] == "objectif cité par le guide":
                entry["origine"] = link["origine"]
    return sorted(seen.values(), key=lambda x: (x["origine"] != "objectif cité par le guide", -x["seances"]))[:12]


def in_guides(kb: KnowledgeBase, node: dict) -> list[dict]:
    """Séquences et séances des guides qui travaillent un item (ou un objectif) du programme."""
    targets = [node["id"]]
    if node["kind"] == "item":
        targets += [o["id"] for o in _children(kb, node["id"]) if o["kind"] == "objectif"]
    out, seen = [], set()
    for t in targets:
        for g in kb.neighbours(t, "travaille", reverse=True):
            if g["id"] in seen:
                continue
            seen.add(g["id"])
            out.append({"id": g["id"], "type": g["kind"], "titre": g["title"], "contexte": g["data"].get("contexte"),
                        "origine": (g.get("edge_data") or {}).get("origine"), "similarite": (g.get("edge_data") or {}).get("similarite")})
    return sorted(out, key=lambda x: (x["origine"] != "objectif cité par le guide", -(x["similarite"] or 0)))[:15]


# --------------------------------------------------------------------------- recherche
def search(kb: KnowledgeBase, query: str, discipline: str | None = None, period: int | None = None, limit: int = 10) -> list[dict]:
    res = kb.search(query, discipline=discipline, kinds=GUIDE_KINDS, limit=limit * 3 if period else limit)
    out = []
    for h in res.hits:
        node = kb.node(h.id)
        if period and node["data"].get("periode") != period:
            continue
        out.append({"id": h.id, "type": h.kind, "titre": h.title, "contexte": h.context, "discipline": h.discipline,
                    "pages_du_guide": node["data"].get("pages")})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- calendrier
@dataclass
class Slot:
    """Ce qu'un guide prévoit pour un jour de classe."""
    guide: str
    unit: dict
    seances: list[dict]
    day: dict | None = None  # jour du guide (français)
    week_items: list[dict] = field(default_factory=list)  # maths : à placer dans la semaine (atelier problèmes)


@dataclass
class GuideCalendar:
    weeks: list[Week]
    by_day: dict[date, list[Slot]]
    by_week: dict[int, list[tuple[str, dict]]]  # numéro de semaine → (guide, séquence) de maths
    free_days: dict[str, list[date]]  # guide → jours de classe sans contenu prévu
    overflow: dict[str, list[str]]  # guide → contenus au-delà des jours ou semaines de la période


def build_calendar(kb: KnowledgeBase, calendar_file: Path, year: int, zone: str) -> GuideCalendar:
    weeks = school_weeks(calendar_file, year, zone)
    cal = GuideCalendar(weeks, {}, {}, {}, {})
    for g in _nodes(kb, "SELECT * FROM nodes WHERE kind = 'guide' ORDER BY position"):
        units = _children(kb, g["id"])
        free, over = [], []
        for period in sorted({u["data"]["periode"] for u in units}):
            p_units = sorted((u for u in units if u["data"]["periode"] == period), key=lambda u: u["data"]["numero"])
            p_weeks = [w for w in weeks if w.period == period]
            if g["data"].get("rythme") == "semaine":
                for i, unit in enumerate(p_units):
                    if i >= len(p_weeks):
                        over.append(f"P{period} : séquence {unit['data']['numero']} « {unit['title']} » (pas de semaine de classe restante)")
                        continue
                    week = p_weeks[i]
                    cal.by_week.setdefault(week.number, []).append((g["title"], unit))
                    seances = [s for s in _children(kb, unit["id"]) if s["kind"] == "seance"]
                    in_week = [_seance_summary(s) for s in seances if s["data"].get("type") not in DAY_KINDS]
                    for k, day in enumerate(week.days, 1):
                        todays = [_seance_summary(s) for s in seances if s["data"].get("type") in DAY_KINDS and s["data"].get("numero") == k]
                        cal.by_day.setdefault(day, []).append(Slot(g["title"], unit, todays, week_items=in_week))
                    if len(week.days) < 4:
                        over.append(f"semaine {week.number} ({len(week.days)} jours de classe) : séance(s) "
                                    f"{', '.join(str(n) for n in range(len(week.days) + 1, 5))} de la séquence "
                                    f"{unit['data']['numero']} à placer")
                free += [d for w in p_weeks[len(p_units):] for d in w.days]
            else:
                days = sorted((d for u in p_units for d in _children(kb, u["id"]) if d["kind"] == "jour"),
                              key=lambda d: d["data"]["jour_periode"])
                unit_of = {d["id"]: u for u in p_units for d in _children(kb, u["id"]) if d["kind"] == "jour"}
                class_days = [d for w in p_weeks for d in w.days]
                for day_node, when in zip(days, class_days):
                    seances = [_seance_summary(s) for s in _children(kb, day_node["id"]) if s["kind"] == "seance"]
                    cal.by_day.setdefault(when, []).append(Slot(g["title"], unit_of[day_node["id"]], seances, day=day_node))
                free += class_days[len(days):]
                over += [f"P{period} : {d['title']} (pas de jour de classe restant)" for d in days[len(class_days):]]
        cal.free_days[g["title"]] = free
        cal.overflow[g["title"]] = over
    return cal


def parse_date(value: str | None) -> date:
    if not value or value.strip().lower() in ("aujourd'hui", "aujourdhui", "today"):
        return date.today()
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Date illisible : {value!r} (attendu : 2026-11-16 ou 16/11/2026)")


def _week_of(weeks: list[Week], when: date) -> Week | None:
    return next((w for w in weeks if w.monday <= when < w.monday + timedelta(days=7)), None)


def day_plan(kb: KnowledgeBase, calendar_file: Path, when: date, zone: str = "B") -> dict:
    """Ce que les guides prévoient pour un jour de classe."""
    year = school_year(None, when)
    cal = build_calendar(kb, calendar_file, year, zone)
    week = _week_of(cal.weeks, when)
    out = {"date": when.isoformat(), "jour": WEEKDAYS[when.weekday()], "zone": zone.upper(), "annee": f"{year}-{year + 1}"}
    if week is None:
        return {**out, "classe": False, "message": "Pas de classe cette semaine-là (vacances)."}
    out.update(periode=week.period, semaine=week.number, semaine_de_la_periode=week.rank)
    if when not in week.days:
        return {**out, "classe": False, "message": f"Pas de classe ce jour-là ({out['jour']}, jour férié ou hors des jours de classe)."}
    out["jour_de_la_semaine"] = week.days.index(when) + 1
    out["classe"] = True
    out["guides"] = [_slot_dict(s) for s in cal.by_day.get(when, [])]
    out["sans_contenu_prevu"] = [g for g, days in cal.free_days.items() if when in days]
    return out


def _slot_dict(s: Slot) -> dict:
    u = s.unit
    d = {"guide": s.guide, "unite": {"id": u["id"], "titre": u["title"], "numero": u["data"].get("numero"),
                                     "type": u["data"].get("type"), "objectifs_cites": u["data"].get("objectifs_programme", [])},
         "seances": s.seances}
    if s.day:
        d["jour_du_guide"] = {"id": s.day["id"], "jour_de_la_lecon": s.day["data"].get("jour_lecon"),
                              "jour_de_la_periode": s.day["data"].get("jour_periode"), "pages": s.day["data"].get("pages")}
    if s.week_items:
        d["dans_la_semaine"] = s.week_items
    return d


def period_plan(kb: KnowledgeBase, calendar_file: Path, year: int, zone: str = "B", period: int | None = None) -> dict:
    """Semaine par semaine : la séquence de maths et les leçons de français de chaque jour."""
    cal = build_calendar(kb, calendar_file, year, zone)
    rows = []
    for w in cal.weeks:
        if period and w.period != period:
            continue
        days = []
        for d in w.days:
            slots = cal.by_day.get(d, [])
            days.append({"date": d.isoformat(), "jour": WEEKDAYS[d.weekday()],
                         "guides": {s.guide: (f"{s.unit['title']} — jour {s.day['data'].get('jour_lecon')}" if s.day
                                              else ", ".join(x["titre"] for x in s.seances if x["type"] == "séance"))
                                    for s in slots}})
        rows.append({"semaine": w.number, "periode": w.period, "semaine_de_la_periode": w.rank,
                     "lundi": w.monday.isoformat(), "sequences": [{"guide": g, "numero": u["data"]["numero"], "titre": u["title"]}
                                                                 for g, u in cal.by_week.get(w.number, [])], "jours": days})
    return {"annee": f"{year}-{year + 1}", "zone": zone.upper(), "periode": period, "guides": list(cal.free_days), "semaines": rows,
            "jours_sans_contenu": {g: [d.isoformat() for d in days if not period or _period_of(cal.weeks, d) == period]
                                   for g, days in cal.free_days.items()},
            "a_placer": cal.overflow}


def _period_of(weeks: list[Week], when: date) -> int | None:
    w = next((w for w in weeks if when in w.days), None)
    return w.period if w else None


# --------------------------------------------------------------------------- rendu
def day_markdown(plan: dict) -> str:
    head = f"# {plan['jour'].capitalize()} {plan['date']}"
    if not plan.get("classe"):
        return f"{head}\n\n{plan['message']}"
    lines = [(f"{head} — période {plan['periode']}, semaine {plan['semaine']} (semaine {plan['semaine_de_la_periode']} "
              f"de la période), jour {plan['jour_de_la_semaine']} de la semaine"), ""]
    for g in plan["guides"]:
        u = g["unite"]
        if "jour_du_guide" in g:
            j = g["jour_du_guide"]
            lines.append(f"## {g['guide']} — {u['titre']}, jour {j['jour_de_la_lecon']} "
                         f"(jour {j['jour_de_la_periode']} de la période, pages {'-'.join(map(str, j['pages'] or []))})")
        else:
            lines.append(f"## {g['guide']} — séquence {u['numero']} : {u['titre']}")
            for o in u["objectifs_cites"]:
                lines.append(f"- Objectif du programme 2025 : {o}")
        for s in g["seances"]:
            duree = f" ({s['duree_minutes']} min)" if s.get("duree_minutes") else ""
            lines.append(f"- {s['titre']}{duree} · pages {', '.join(map(str, s['pages'] or []))} · id={s['id']}")
        for s in g.get("dans_la_semaine", []):
            lines.append(f"- Dans la semaine : {s['titre']} · id={s['id']}")
        lines.append("")
    for g in plan.get("sans_contenu_prevu", []):
        lines.append(f"_{g} : aucun jour du guide n'est prévu ce jour-là (évaluations, rattrapage)._")
    lines.append("\n_Correspondance proposée : le k-ième jour (ou la k-ième séquence) d'une période du guide sur le "
                 "k-ième jour (ou la k-ième semaine) de classe de la période. Le détail d'une séance : `fiche_guide` avec son id._")
    return "\n".join(lines).rstrip() + "\n"


def period_markdown(plan: dict) -> str:
    title = f"Progression des guides {plan['annee']}, zone {plan['zone']}" + (f", période {plan['periode']}" if plan["periode"] else "")
    lines = [f"# {title}", ""]
    current = None
    for w in plan["semaines"]:
        if w["periode"] != current:
            current = w["periode"]
            lines += [f"## Période {current} — {PERIOD_NAMES.get(current, '')}", ""]
        seqs = "; ".join(f"{s['guide'].split(' —')[0]} : séquence {s['numero']} « {s['titre']} »" for s in w["sequences"])
        lines.append(f"### Semaine {w['semaine']} (S{w['semaine_de_la_periode']}, lundi {w['lundi']})" + (f" — {seqs}" if seqs else ""))
        for d in w["jours"]:
            parts = [f"{g.split(' —')[0]} : {d['guides'].get(g) or 'rien de prévu (évaluations, rattrapage)'}" for g in plan["guides"]]
            lines.append(f"- {d['jour']} {d['date']} : " + " · ".join(parts))
        lines.append("")
    for g, items in plan["a_placer"].items():
        for item in items:
            lines.append(f"- ⚠ {g.split(' —')[0]} : {item}")
    return "\n".join(lines).rstrip() + "\n"


def search_markdown(query: str, hits: list[dict]) -> str:
    if not hits:
        return f"Aucune séance des guides ne correspond à « {query} »."
    lines = [f"Séances des guides pour « {query} » : {len(hits)} résultat(s)."]
    for i, h in enumerate(hits, 1):
        pages = f" · pages {', '.join(map(str, h['pages_du_guide']))}" if h.get("pages_du_guide") else ""
        lines.append(f"\n[{i}] {h['type']} · {h['discipline']}{pages}\nid={h['id']}\n{h['contexte']}\n→ {h['titre']}")
    return "\n".join(lines)



def guide_fiche(kb: KnowledgeBase, node_id: str) -> dict | None:
    """Fiche du serveur des guides : un nœud de guide, ou un item (objectif) du programme réduit aux
    séances des guides qui le travaillent (le détail du programme est sur le serveur des programmes)."""
    node = kb.node(node_id)
    if node is None:
        return None
    if node["kind"] in ("guide", "jour") + GUIDE_KINDS:
        return guide_card(kb, node_id)
    if node["kind"] in ("item", "objectif"):
        return {"id": node_id, "type": node["kind"], "titre": node["title"], "contexte": node["data"].get("contexte"),
                "dans_les_guides": in_guides(kb, node)}
    return None


def card(kb: KnowledgeBase, node_id: str, year: int | None = None) -> dict | None:
    """Fiche d'un nœud : celle d'un nœud de guide, ou celle du programme complétée des séances des guides."""
    node = kb.node(node_id)
    if node is None:
        return None
    if node["kind"] in ("guide", "jour") + GUIDE_KINDS:
        return guide_card(kb, node_id)
    out = kb.item_card(node_id, year)
    if out is not None and node["kind"] in ("item", "objectif"):
        linked = in_guides(kb, node)
        if linked:
            out["dans_les_guides"] = linked
    return out
