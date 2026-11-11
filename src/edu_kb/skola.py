"""Export de la programmation pour Skola : JSON calqué sur ses tables, Markdown et CSV lisibles.

Le JSON reprend les colonnes des tables Skola (`subjects`, `sequences`, `programmation_items`),
en désignant les matières par leur nom et les séquences par une référence (`sequence_ref`), puisque
les identifiants n'existent qu'une fois les lignes créées dans la base de l'application. Il ajoute
ce que Skola ne stocke pas encore : les semaines de chaque unité et la progression hebdomadaire.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from .kb import KnowledgeBase
from .planning import MODES, PERIOD_NAMES, Plan, Unit

FORMAT = "skola-programmation"
VERSION = 1

# Couleurs des matières déjà créées par Skola (src/main/db/seed.ts), complétées pour les autres.
SUBJECT_COLORS = {
    "Français": "#2563eb",
    "Mathématiques": "#dc2626",
    "Questionner le monde": "#16a34a",
    "EMC": "#9333ea",
    "EPS": "#ea580c",
    "Arts plastiques": "#db2777",
    "Éducation musicale": "#0891b2",
    "Langues vivantes": "#4f46e5",
    "Sciences et technologie": "#15803d",
    "Histoire-géographie": "#b45309",
    "Histoire des arts": "#be185d",
    "EVAR": "#0d9488",
}


def _school_year(year: int) -> str:
    return f"{year}-{year + 1}"


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def _sequence(kb: KnowledgeBase, plan: Plan, unit: Unit, ref: str, position: int) -> dict:
    weeks = {w.number: w for w in plan.weeks}
    first, last = weeks[unit.weeks[0]], weeks[unit.weeks[-1]]
    item = kb.node(unit.item_ids[0]) if unit.item_ids else None
    comp = kb.competences(item) if item else {}
    socle = ", ".join(s["code"] for s in comp.get("socle_commun", []))
    source = kb.node(f"source:{unit.source}")
    exemples = []
    for iid in unit.item_ids:
        champs = (kb.node(iid) or {}).get("data", {}).get("champs", {})
        exemples += [b["texte"] for b in champs.get("exemples_reussite", []) + champs.get("attendus", [])]
    description = [
        f"Discipline : {unit.discipline}" + (f" › {unit.strand}" if unit.strand else ""),
        f"Périodes : {', '.join(f'P{p}' for p in unit.periods)} — {unit.origin}",
        f"Semaines : du {first.days[0]:%d/%m/%Y} au {last.days[-1]:%d/%m/%Y} ({len(unit.weeks)} semaine(s))",
    ]
    if unit.question:
        description.append(f"Question : {unit.question}")
    if source:
        description.append(f"Source : {source['title']} — {source['data'].get('bo', '')}")
    return {
        "ref": ref,
        "subject": unit.discipline,
        "title": unit.title,
        "level": plan.level,
        "period": unit.periods[0] if unit.periods else None,
        "objectives": _bullets([o.text for o in unit.objectives]),
        "competences": _bullets(unit.competences[:30]) + (f"\n\nDomaines du socle commun : {socle}" if socle else ""),
        "description": "\n".join(description),
        "evaluation": _bullets(exemples[:20]),
        "position": position,
        "edu_kb": {"noeud": unit.node_id, "items": unit.item_ids, "semaines": unit.weeks, "periodes": unit.periods,
                   "origine": unit.origin},
    }


def export(kb: KnowledgeBase, plan: Plan) -> dict:
    units = [u for u in plan.units if u.weeks]
    subjects = sorted({u.discipline for u in units}, key=lambda s: list(SUBJECT_COLORS).index(s) if s in SUBJECT_COLORS else 99)
    sequences, items, progression, continuous = [], [], {}, []
    weeks = {w.number: w for w in plan.weeks}
    for i, unit in enumerate(units):
        ref = f"seq-{i + 1}"
        sequences.append(_sequence(kb, plan, unit, ref, i))
        for p in unit.periods:
            pweeks = [n for n in unit.weeks if weeks[n].period == p]
            if not pweeks:
                continue
            items.append({
                "subject": unit.discipline, "period": p, "title": unit.title, "domain": unit.strand,
                "status": "a_faire", "sequence_ref": ref, "position": len(items),
                "semaines": pweeks, "origine": unit.origin, "en_continu": unit.continuous,
            })
        always = [o.text for o in unit.objectives if o.continuous]
        if always or unit.always:
            continuous.append({"subject": unit.discipline, "domain": unit.strand, "sequence_ref": ref, "titre": unit.title,
                               "objectifs": always, "toute_l_unite": unit.continuous})
        for o in unit.objectives:
            if o.continuous:
                continue
            # un objectif travaillé sur plus d'une période n'est rappelé qu'en début de chaque période
            spread = len({weeks[n].period for n in o.weeks}) > 1
            shown = [n for n in o.weeks if not spread or n == min(m for m in o.weeks if weeks[m].period == weeks[n].period)]
            for n in shown:
                entry = progression.setdefault(n, {}).setdefault(ref, {
                    "subject": unit.discipline, "domain": unit.strand, "sequence_ref": ref, "titre": unit.title, "objectifs": []})
                entry["objectifs"].append(f"En continu : {o.text}" if spread else o.text)
        for n in () if unit.always or MODES.get(unit.discipline) == "continu" or any(o.continuous for o in unit.objectives) else unit.weeks:  # unité sans objectif placé cette semaine-là : on la mentionne quand même (sauf si elle a du travail en continu, listé à part)
            progression.setdefault(n, {}).setdefault(ref, {
                "subject": unit.discipline, "domain": unit.strand, "sequence_ref": ref, "titre": unit.title, "objectifs": []})
    periods = plan.periods()
    return {
        "format": FORMAT,
        "version": VERSION,
        "genere_par": "edu-kb",
        "genere_le": datetime.now().isoformat(timespec="seconds"),
        "classe": {"niveau": plan.level, "annee_scolaire": _school_year(plan.year), "zone": plan.zone},
        "avertissement": (
            "Proposition générée à partir des programmes officiels : les périodes imposées par les textes sont "
            "respectées (champ `origine`), le reste est réparti dans l'ordre du programme. À ajuster."
        ),
        "sources": [{"id": s["source_id"], "titre": s["title"], "bo": s["data"].get("bo"), "fichier": s["data"].get("fichier")}
                    for s in plan.sources],
        "calendrier": {
            "periodes": [{"numero": p, "nom": PERIOD_NAMES[p], "debut": ws[0].days[0].isoformat(),
                          "fin": ws[-1].days[-1].isoformat(), "semaines": len(ws)} for p, ws in periods.items()],
            "semaines": [{"numero": w.number, "periode": w.period, "rang": w.rank, "lundi": w.monday.isoformat(),
                          "jours": [d.isoformat() for d in w.days]} for w in plan.weeks],
        },
        "subjects": [{"name": s, "color": SUBJECT_COLORS.get(s, "#64748b")} for s in subjects],
        "sequences": sequences,
        "programmation_items": items,
        "en_continu": sorted(continuous, key=lambda e: subjects.index(e["subject"])),
        "progression": [
            {"semaine": n, "periode": weeks[n].period, "rang": weeks[n].rank, "du": weeks[n].days[0].isoformat(),
             "au": weeks[n].days[-1].isoformat(),
             "entrees": sorted(progression.get(n, {}).values(), key=lambda e: subjects.index(e["subject"]))}
            for n in sorted(weeks)
        ],
    }


def to_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def to_markdown(data: dict) -> str:
    c = data["classe"]
    out = [f"# Programmation {c['niveau']} — {c['annee_scolaire']} (zone {c['zone']})", "", f"> {data['avertissement']}", ""]
    out += ["## Calendrier", "", "| Période | Du | Au | Semaines |", "|---|---|---|---|"]
    for p in data["calendrier"]["periodes"]:
        out.append(f"| P{p['numero']} — {p['nom']} | {p['debut']} | {p['fin']} | {p['semaines']} |")
    out += ["", "## Programmation annuelle", "", "| Discipline | " + " | ".join(f"P{p['numero']}" for p in data["calendrier"]["periodes"]) + " |",
            "|---|" + "---|" * len(data["calendrier"]["periodes"])]
    for s in data["subjects"]:
        cells = []
        for p in data["calendrier"]["periodes"]:
            rows = [i for i in data["programmation_items"]
                    if i["subject"] == s["name"] and i["period"] == p["numero"] and not i.get("en_continu")]
            by_domain: dict[str, list[str]] = {}
            for i in rows:
                by_domain.setdefault(i["domain"], [])
                if i["title"] not in by_domain[i["domain"]]:
                    by_domain[i["domain"]].append(i["title"])
            parts = [(f"*{d}* : " if d and len(by_domain) > 1 else "") + " ; ".join(t) for d, t in by_domain.items()]
            cells.append("<br>".join(parts) or ("↻ en continu" if any(c["subject"] == s["name"] for c in data["en_continu"]) else "—"))
        out.append(f"| **{s['name']}** | " + " | ".join(cells) + " |")
    if data["en_continu"]:
        out += ["", "## Travaillé en continu (toute l'année)", "",
                "> Objectifs sans échéance dans le programme, ou que le programme dit travaillés toute l'année : "
                "ils ne sont pas répétés dans la progression hebdomadaire.", ""]
        current_subject = None
        for e in data["en_continu"]:
            if e["subject"] != current_subject:
                current_subject = e["subject"]
                out += [f"### {current_subject}", ""]
            dom = f"{e['domain']} › " if e["domain"] and e["domain"] != e["titre"] else ""
            out.append(f"- **{dom}{e['titre']}**")
            out += [f"  - {o}" for o in e["objectifs"]]
        out.append("")
    out += ["", "## Progression hebdomadaire", ""]
    current = None
    for w in data["progression"]:
        if w["periode"] != current:
            current = w["periode"]
            out += [f"### Période {current}", ""]
        out += [f"#### Semaine {w['rang']} (S{w['semaine']}) — du {w['du']} au {w['au']}", ""]
        for e in w["entrees"]:
            dom = f" › {e['domain']}" if e["domain"] else ""
            objs = "; ".join(e["objectifs"]) if e["objectifs"] else "(suite)"
            out.append(f"- **{e['subject']}{dom}** — {e['titre']} : {objs}")
        out.append("")
    out += ["## Sources", ""] + [f"- {s['titre']} — {s['bo']}" for s in data["sources"]]
    return "\n".join(out) + "\n"


def to_csv(data: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["semaine", "periode", "semaine_de_periode", "du", "au", "discipline", "domaine", "unite", "objectifs"])
    for w in data["progression"]:
        for e in w["entrees"]:
            writer.writerow([w["semaine"], w["periode"], w["rang"], w["du"], w["au"], e["subject"], e["domain"], e["titre"],
                             " | ".join(e["objectifs"])])
    return buf.getvalue()
