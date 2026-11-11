"""Préparation d'une séquence et de ses séances à partir d'une notion.

Tout ce qui vient du programme est cité tel quel (objectifs, attendus, exemples de réussite,
démarches proposées, repères) avec sa source. Le déroulé des séances n'est qu'un squelette
(phases types) : le détailler est le travail de l'enseignant, ou de Claude via le prompt MCP
« preparer_sequence ».
"""

from __future__ import annotations

import math
import re

from .graph import CYCLE_OF, FIELD_LABELS
from .kb import KnowledgeBase, normalize_level

SKOLA_SOCLE = {"D1.1", "D1.2", "D1.3", "D1.4", "D2", "D3", "D4", "D5"}
ACTIVITY_FIELDS = ("demarches", "exemples_situations", "contenus")
SUCCESS_FIELDS = ("exemples_reussite", "attendus", "notions_competences", "connaissances", "connaissances_cm")

PHASES = [
    ("Découverte / situation de départ", "Collectif", "Présente la situation, fait émerger les représentations.", "Observent, formulent des hypothèses."),
    ("Recherche", "Petits groupes", "Observe, relance, régule.", "Cherchent, manipulent, confrontent leurs procédures."),
    ("Mise en commun et institutionnalisation", "Collectif", "Fait expliciter les procédures, formalise la trace écrite.", "Expliquent, comparent, retiennent."),
    ("Entraînement / réinvestissement", "Individuel", "Différencie, accompagne les élèves fragiles.", "S'exercent, s'auto-évaluent."),
]


def _clean(text: str) -> str:
    """Retire les « ou » orphelins que laisse la mise en tableau du PDF en fin de ligne."""
    return re.sub(r"(?:\s+(?:ou|et))+\s*$", "", text.strip())


def _short(text: str, limit: int = 90) -> str:
    """Titre de séance : la première phrase ou le premier segment avant « : » ou « ( », coupé proprement."""
    head = re.split(r"\s*[:(]\s|\.\s", text, maxsplit=1)[0].strip().rstrip(".")
    if len(head) <= limit:
        return head
    return head[:limit].rsplit(" ", 1)[0] + "…"


def _item_of(kb: KnowledgeBase, node: dict) -> list[dict]:
    if node["kind"] == "item":
        return [node]
    if node["kind"] == "objectif":
        return [p for p in kb.neighbours(node["id"], "contient", reverse=True) if p["kind"] == "item"]
    if node["kind"] in ("theme", "rubrique", "sous_rubrique"):
        items = [i for i in kb.neighbours(node["id"], "contient") if i["kind"] == "item"]
        for sub in kb.neighbours(node["id"], "contient"):
            items += [i for i in kb.neighbours(sub["id"], "contient") if i["kind"] == "item"]
        return items
    return []


def _scope(kb: KnowledgeBase, node: dict) -> dict | None:
    """Thème ou rubrique qui englobe un résultat de recherche."""
    if node["kind"] in ("theme", "rubrique", "sous_rubrique"):
        return node
    items = _item_of(kb, node)
    if not items:
        return None
    themes = kb.neighbours(items[0]["id"], "theme")
    if themes:
        return themes[0]
    parents = [p for p in kb.neighbours(items[0]["id"], "contient", reverse=True) if p["kind"] in ("rubrique", "sous_rubrique", "theme")]
    return parents[0] if parents else None


def prepare(kb: KnowledgeBase, notion: str, level: str, year: int, discipline: str | None = None,
            nb_seances: int | None = None) -> dict:
    level = normalize_level(level)
    result = kb.search(notion, level=level, discipline=discipline, year=year, kinds=("item", "theme", "objectif"), limit=25)
    if not result.hits:
        return {"notion": notion, "niveau": level, "annee": year, "trouve": False,
                "message": f"Aucun item du programme de {level} ne traite « {notion} » pour {year}-{year + 1}. "
                           "Essaie un synonyme, un autre niveau, ou retire le filtre de discipline."}
    anchor = discipline and kb.resolve_discipline(discipline) or result.hits[0].discipline
    hit_ids = [h.id for h in result.hits if h.discipline == anchor]

    # périmètre : le thème ou la rubrique du meilleur résultat, avec tous ses items
    best = kb.node(hit_ids[0])
    scope = _scope(kb, best)
    items = [i for i in _item_of(kb, scope) if level in i["levels"]] if scope else []
    if not items:
        items = [i for i in _item_of(kb, best) if level in i["levels"]]
    in_scope = {i["id"] for i in items}
    targeted: set[str] = set()
    for hid in hit_ids:
        node = kb.node(hid)
        if node["kind"] == "objectif" and any(p["id"] in in_scope for p in _item_of(kb, node)):
            targeted.add(node["title"])
    cards = [kb.item_card(i["id"], year) for i in items]

    objectives: list[dict] = []
    for card, item in zip(cards, items):
        for b in card["objectifs"]:
            objectives.append({"texte": b["texte"], "moment": b.get("moment"), "item": item["id"],
                               "cible": b["texte"] in targeted or not targeted})
    # les objectifs repérés par la recherche d'abord, dans l'ordre du programme
    objectives.sort(key=lambda o: not o["cible"])
    chosen = [o for o in objectives if o["cible"]] or objectives

    def collect(fields: tuple[str, ...]) -> list[dict]:
        out = []
        for item in items:
            champs = item["data"].get("champs", {})
            for f in fields:
                out += [{"texte": _clean(b["texte"]), "champ": FIELD_LABELS.get(f, f), "item": item["id"]} for b in champs.get(f, [])]
        return out

    success = collect(SUCCESS_FIELDS)
    activities = collect(ACTIVITY_FIELDS)
    themes = {t["id"]: t for card in cards for t in card["themes"]}
    competences = cards[0]["competences"] if cards else {}
    socle = [s["code"] for s in competences.get("socle_commun", []) if s["code"] in SKOLA_SOCLE]
    periods = sorted({p for card in cards for p in card["periodes_programme"]})
    for t in themes.values():
        hint = t.get("periodes_programme") or {}
        periods = sorted(set(periods) | set(hint.get("periodes", [])))

    n = len(chosen)
    seances = []
    per = max(1, math.ceil(n / nb_seances)) if nb_seances and nb_seances < n else 1
    for k in range(0, n, per):
        group = chosen[k : k + per]
        num = len(seances) + 1
        seances.append({
            "numero": num,
            "titre": _short(group[0]["texte"]) if len(group) == 1 else " / ".join(_short(o["texte"], 40) for o in group),
            "objectifs": [o["texte"] for o in group],
            "moment_du_programme": [o["moment"] for o in group if o["moment"]],
            "phases": [{"titre": t, "duree": "", "modalite": m, "deroulement": "", "role_enseignant": r1, "role_eleve": r2}
                       for t, m, r1, r2 in PHASES],
            "criteres_de_reussite": [s["texte"] for s in success if s["item"] in {o["item"] for o in group}][:6],
        })
    seances.append({
        "numero": len(seances) + 1, "titre": "Évaluation", "objectifs": [o["texte"] for o in chosen],
        "moment_du_programme": [], "phases": [], "criteres_de_reussite": [s["texte"] for s in success][:10],
    })

    progression = cards[0]["progression"] if cards else {}
    return {
        "notion": notion,
        "trouve": True,
        "niveau": level,
        "cycle": CYCLE_OF[level],
        "annee_scolaire": f"{year}-{year + 1}",
        "discipline": anchor,
        "mode_recherche": result.mode,
        "items": [{"id": c["id"], "contexte": c["contexte"], "titre": c["titre"]} for c in cards],
        "themes": list(themes.values()),
        "periodes_indiquees_par_le_programme": periods,
        "objectifs": chosen,
        "competences": competences,
        "socle": socle,
        "criteres_de_reussite": success,
        "pistes_d_activites": activities,
        "prerequis": progression.get("avant", []),
        "prolongements": progression.get("apres", []),
        # liens du graphe seulement (filtrés par le sens) : les résultats de recherche des autres
        # disciplines ne partagent souvent qu'un mot (« lire l'heure » → « lire un texte »)
        "liens_autres_disciplines": list({link["id"]: link for c in cards for link in c["liens_autres_disciplines"]}.values())[:8],
        "seances": seances,
        "sources": list({c["source"]["titre"]: c["source"] for c in cards}.values()),
    }


def to_markdown(seq: dict) -> str:
    if not seq.get("trouve"):
        return seq["message"]
    out = [f"# Séquence — {seq['notion']} ({seq['discipline']}, {seq['niveau']})", ""]
    out.append(f"Année {seq['annee_scolaire']} · cycle {seq['cycle']} · recherche {seq['mode_recherche']}")
    if seq["periodes_indiquees_par_le_programme"]:
        out.append(f"Périodes indiquées par le programme : {', '.join(f'P{p}' for p in seq['periodes_indiquees_par_le_programme'])}")
    out += ["", "## Ancrage dans le programme", ""]
    out += [f"- {i['contexte']}" for i in seq["items"]]
    if seq["themes"]:
        out += ["", "## Thèmes", ""]
        for t in seq["themes"]:
            line = f"- **{t['theme']}** ({t['discipline']})"
            if t.get("question"):
                line += f" — {t['question']}"
            out.append(line)
            if t.get("mots_cles"):
                out.append(f"  - Mots-clés : {t['mots_cles']}")
    out += ["", "## Objectifs d'apprentissage", ""]
    out += [f"- {o['texte']}" + (f" _(programme : {o['moment']})_" if o["moment"] else "") for o in seq["objectifs"]]
    comp = seq["competences"]
    out += ["", "## Compétences", ""]
    for label, lines in comp.get("attendus_de_l_item", {}).items():
        out += [f"**{label}**", ""] + [f"- {x}" for x in lines] + [""]
    if comp.get("competences_travaillees_du_cycle"):
        out += ["**Compétences travaillées du cycle**", ""]
        out += [f"- {c['competence']}" + (f" (socle : {', '.join(c['socle'])})" if c["socle"] else "") for c in comp["competences_travaillees_du_cycle"]]
        out.append("")
    if comp.get("socle_commun"):
        out += ["**Socle commun** : " + ", ".join(f"{s['code']} {s['intitule']}" for s in comp["socle_commun"]), ""]
    if seq["pistes_d_activites"]:
        out += ["## Pistes d'activités proposées par le programme", ""] + [f"- {a['texte']}" for a in seq["pistes_d_activites"][:12]] + [""]
    if seq["prerequis"] or seq["prolongements"]:
        out += ["## Progression", ""]
        out += [f"- Avant ({', '.join(p['niveaux'])}) — {p['titre']} : " + "; ".join(p["items"][:3]) for p in seq["prerequis"]]
        out += [f"- Après ({', '.join(p['niveaux'])}) — {p['titre']} : " + "; ".join(p["items"][:3]) for p in seq["prolongements"]]
        out.append("")
    if seq["liens_autres_disciplines"]:
        out += ["## Liens avec d'autres disciplines", ""] + [f"- {l['discipline']} — {l['titre']}" for l in seq["liens_autres_disciplines"]] + [""]
    teaching = [s for s in seq["seances"] if s["phases"]]
    shared = len(teaching) > 1 and all(s["criteres_de_reussite"] == teaching[0]["criteres_de_reussite"] for s in teaching)
    if shared and teaching[0]["criteres_de_reussite"]:
        out += ["## Critères de réussite (communs à toutes les séances)", ""] + [f"- {c}" for c in teaching[0]["criteres_de_reussite"]] + [""]
    out += ["## Séances", ""]
    for s in seq["seances"]:
        out += [f"### Séance {s['numero']} — {s['titre']}", ""]
        out += [f"- Objectif : {o}" for o in s["objectifs"]]
        if s["criteres_de_reussite"] and not (shared and s["phases"]):
            out += ["- Critères de réussite :"] + [f"  - {c}" for c in s["criteres_de_reussite"]]
        if s["phases"]:
            out += ["", "| Phase | Modalité | Enseignant | Élèves |", "|---|---|---|---|"]
            out += [f"| {p['titre']} | {p['modalite']} | {p['role_enseignant']} | {p['role_eleve']} |" for p in s["phases"]]
        out.append("")
    out += ["## Sources", ""] + [f"- {s['titre']} — {s.get('bo') or ''}" for s in seq["sources"]]
    return "\n".join(out) + "\n"


def to_skola(seq: dict) -> dict:
    """Séquence et fiches de préparation, avec les colonnes des tables Skola `sequences` et `preps`."""
    if not seq.get("trouve"):
        return {}
    comp = seq["competences"]
    comp_lines = [x for lines in comp.get("attendus_de_l_item", {}).values() for x in lines]
    sequence = {
        "ref": "seq-1",
        "subject": seq["discipline"],
        "title": seq["notion"][:1].upper() + seq["notion"][1:],
        "level": seq["niveau"],
        "period": seq["periodes_indiquees_par_le_programme"][0] if seq["periodes_indiquees_par_le_programme"] else None,
        "objectives": "\n".join(f"- {o['texte']}" for o in seq["objectifs"]),
        "competences": "\n".join(f"- {c}" for c in comp_lines[:20]),
        "description": "\n".join(f"- {i['contexte']}" for i in seq["items"]),
        "evaluation": "\n".join(f"- {c['texte']}" for c in seq["criteres_de_reussite"][:15]),
        "position": 0,
    }
    preps = []
    for s in seq["seances"]:
        preps.append({
            "sequence_ref": "seq-1",
            "subject": seq["discipline"],
            "title": s["titre"][:120],
            "level": seq["niveau"],
            "cycle": seq["cycle"],
            "duration": "",
            "seance_number": s["numero"],
            "socle": seq["socle"],
            "attendus": "\n".join(f"- {c}" for c in s["criteres_de_reussite"]),
            "objectifs": "\n".join(f"- {o}" for o in s["objectifs"]),
            "materiel": "",
            "phases": [{"title": p["titre"], "duration": p["duree"], "modalite": p["modalite"], "deroulement": p["deroulement"],
                        "role_enseignant": p["role_enseignant"], "role_eleve": p["role_eleve"]} for p in s["phases"]],
            "differenciation": "",
            "evaluation": "\n".join(f"- {c}" for c in s["criteres_de_reussite"]),
            "bilan": "",
        })
    return {"format": "skola-sequence", "version": 1, "sequences": [sequence], "preps": preps}
