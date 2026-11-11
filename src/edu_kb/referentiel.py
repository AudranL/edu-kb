"""Référentiel de compétences d'un niveau : tout ce que le programme en vigueur demande d'acquérir.

Le référentiel est tiré du graphe sans rien inventer : chaque compétence est une puce du programme
(objectif d'apprentissage, compétence travaillée, notion et compétence d'EVAR, contenu d'EMC…),
rangée par discipline puis par domaine, avec son échéance quand le programme en donne une, ses
critères de réussite (exemples de réussite, attendus), sa page et son texte officiel. Il sert de grille
pour évaluer, suivre les acquis d'une classe ou vérifier une programmation.
"""

from __future__ import annotations

import csv
import io
import re

from .graph import CYCLE_OF
from .kb import KnowledgeBase, normalize_level
from .outline import levels_of
from .planning import MODES, WHOLE_YEAR

# Champs qui énoncent ce que l'élève doit acquérir, par ordre de préférence.
COMPETENCE_FIELDS = ("objectifs", "competences", "notions_competences", "contenus", "connaissances")
# Champs qui disent à quoi l'on reconnaît que c'est acquis.
CRITERIA_FIELDS = ("exemples_reussite", "attendus")
END_OF_CYCLE = "attendus_fin_cycle"
ORPHAN = re.compile(r"(?:\s+(?:ou|et))+\s*$")


def _text(bullet: dict) -> str:
    return ORPHAN.sub("", bullet["texte"].strip()).rstrip(" ;")


def _domain(chemin: list[str], discipline: str) -> str:
    parts = [p for p in chemin if not levels_of(p) and p != discipline and not re.match(r"^(principes|préambule)", p, re.IGNORECASE)]
    return " › ".join(parts)


def _first(champs: dict, names: tuple[str, ...]) -> tuple[str, list[dict]]:
    for name in names:
        if champs.get(name):
            return name, champs[name]
    return "", []


def build(kb: KnowledgeBase, level: str, year: int, disciplines: list[str] | None = None) -> dict:
    level = normalize_level(level)
    sources = kb.applicable_sources(level, year)
    names = [kb.resolve_discipline(d) for d in disciplines] if disciplines else sorted({s["discipline"] for s in sources})
    result = []
    for name in names:
        items = kb.items_for(level, name, year)
        if not items:
            continue
        continuous_discipline = MODES.get(name) == "continu"
        domains: dict[str, dict] = {}
        end_of_cycle: list[dict] = []
        for item in items:
            champs = item["data"].get("champs", {})
            field, bullets = _first(champs, COMPETENCE_FIELDS)
            if not field:
                # seuls des attendus de fin de cycle : on les garde à part, ils cadrent la discipline
                end_of_cycle += [{"texte": _text(b), "domaine": _domain(item["data"].get("chemin", []), name), "page": b.get("page"),
                                  "item": item["id"]} for b in champs.get(END_OF_CYCLE, [])]
                continue
            domain = domains.setdefault(_domain(item["data"].get("chemin", []), name), {"competences": [], "criteres_de_reussite": []})
            for b in bullets:
                moment = b.get("moment")
                domain["competences"].append({
                    "texte": _text(b), "echeance": moment, "page": b.get("page"), "item": item["id"],
                    "en_continu": bool(moment and WHOLE_YEAR.search(moment)) or (continuous_discipline and not moment),
                })
            _, criteria = _first(champs, CRITERIA_FIELDS)
            for b in criteria:
                text = _text(b)
                if text not in domain["criteres_de_reussite"]:
                    domain["criteres_de_reussite"].append(text)
        if not domains and not end_of_cycle:
            continue
        card = kb.competences(items[0])
        source = kb.node(f"source:{items[0]['source_id']}")
        result.append({
            "discipline": name,
            "source": {"id": items[0]["source_id"], "titre": source["title"] if source else "", "bo": (source or {}).get("data", {}).get("bo", "")},
            "socle_commun": card["socle_commun"],
            "competences_travaillees_du_cycle": card["competences_travaillees_du_cycle"],
            "attendus_de_fin_de_cycle": end_of_cycle,
            "domaines": [{"domaine": d, **v} for d, v in domains.items()],
        })
    return {"niveau": level, "cycle": CYCLE_OF[level], "annee_scolaire": f"{year}-{year + 1}", "disciplines": result}


def to_markdown(ref: dict) -> str:
    nb = sum(len(d["competences"]) for disc in ref["disciplines"] for d in disc["domaines"])
    out = [f"# Référentiel de compétences — {ref['niveau']} ({ref['annee_scolaire']}, cycle {ref['cycle']})", "",
           f"{nb} compétences dans {len(ref['disciplines'])} disciplines, tirées des programmes en vigueur. "
           "`↻` : travaillée toute l'année ; `⏱` : échéance fixée par le programme.", ""]
    for disc in ref["disciplines"]:
        out += [f"## {disc['discipline']}", "", f"_Source : {disc['source']['titre']} — {disc['source']['bo']}_", ""]
        if disc["socle_commun"]:
            out += ["**Socle commun** : " + " ; ".join(f"{s['code']} {s['intitule']}" for s in disc["socle_commun"]), ""]
        if disc["competences_travaillees_du_cycle"]:
            out += ["**Compétences travaillées du cycle**", ""]
            out += [f"- {c['competence']}" + (f" (socle : {', '.join(c['socle'])})" if c["socle"] else "") for c in disc["competences_travaillees_du_cycle"]]
            out.append("")
        if disc["attendus_de_fin_de_cycle"]:
            out += ["**Attendus de fin de cycle**", ""]
            out += [f"- {a['texte']}" + (f" _({a['domaine']})_" if a["domaine"] else "") for a in disc["attendus_de_fin_de_cycle"]]
            out.append("")
        for d in disc["domaines"]:
            if d["domaine"]:
                out += [f"### {d['domaine']}", ""]
            for c in d["competences"]:
                tag = " ↻" if c["en_continu"] else (f" ⏱ {c['echeance']}" if c["echeance"] else "")
                out.append(f"- [ ] {c['texte']}{tag}")
            if d["criteres_de_reussite"]:
                out += ["", "  Critères de réussite :"] + [f"  - {c}" for c in d["criteres_de_reussite"]]
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def to_csv(ref: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["niveau", "discipline", "domaine", "competence", "echeance", "en_continu", "criteres_de_reussite", "page", "source"])
    for disc in ref["disciplines"]:
        for d in disc["domaines"]:
            criteria = " | ".join(d["criteres_de_reussite"])
            for c in d["competences"]:
                writer.writerow([ref["niveau"], disc["discipline"], d["domaine"], c["texte"], c["echeance"] or "",
                                 "oui" if c["en_continu"] else "", criteria, c["page"] or "", disc["source"]["id"]])
    return buf.getvalue()
