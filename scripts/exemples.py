"""Régénère les sorties exactes de docs/exemples/ pour les outils dont le résultat dépend de la recherche
ou de la planification (chercher, progression_notion, preparer_sequence, programmation, referentiel).

    uv run python scripts/exemples.py
"""

from __future__ import annotations

import json
from pathlib import Path

from edu_kb import cli, referentiel, sequence
from edu_kb.config import Settings
from edu_kb.kb import school_year
from edu_kb.planning import build_plan
from edu_kb.server import PROGRESSION_MARGIN, format_search
from edu_kb import skola

OUT = Path(__file__).resolve().parent.parent / "docs" / "exemples"


def write(name: str, tool: str, arguments: dict, body: str, lang: str) -> None:
    call = json.dumps({"outil": tool, "arguments": arguments}, ensure_ascii=False, indent=1)
    text = f"# `{tool}` : sortie exacte\n\nAppel MCP :\n\n```json\n{call}\n```\n\nRéponse, telle que l'outil la renvoie :\n\n```{lang}\n{body.rstrip()}\n```\n"
    (OUT / name).write_text(text, encoding="utf-8")
    print("écrit", name)


def main() -> None:
    settings = Settings.from_env()
    kb = cli._kb(settings)
    year = school_year()

    write("01-chercher.md", "chercher", {"notion": "fractions", "niveau": "CM1", "limite": 5},
          format_search("fractions", kb.search("fractions", "CM1", None, year, limit=5)), "text")

    hits = kb.search("numération des nombres entiers", discipline="Mathématiques", kinds=("item", "theme"), limit=40, margin=PROGRESSION_MARGIN).hits
    by_level: dict[str, list] = {}
    for h in hits:
        for lv in h.levels:
            by_level.setdefault(lv, []).append({"id": h.id, "discipline": h.discipline, "source": h.source_id,
                                                "contexte": h.context, "titre": h.title})
    ordered = {lv: by_level[lv] for lv in ["CP", "CE1", "CE2", "CM1", "CM2", "6e"] if lv in by_level}
    write("05-progression_notion.md", "progression_notion",
          {"notion": "numération des nombres entiers", "discipline": "Mathématiques"},
          json.dumps(ordered, ensure_ascii=False, indent=1), "json")

    seq = sequence.prepare(kb, "le Moyen Âge", "CM1", year, None, 4)
    write("06-preparer_sequence.md", "preparer_sequence", {"notion": "le Moyen Âge", "niveau": "CM1", "nb_seances": 4},
          sequence.to_markdown(seq), "markdown")

    plan = build_plan(kb, settings.calendar_file, "CP", year, "B", ["Sciences et technologie"])
    write("07-programmation.md", "programmation", {"niveau": "CP", "disciplines": ["Sciences et technologie"], "zone": "B"},
          skola.to_markdown(skola.export(kb, plan)), "markdown")

    ref = referentiel.build(kb, "CP", year, ["Mathématiques"])
    write("09-referentiel.md", "referentiel", {"niveau": "CP", "discipline": "Mathématiques"}, referentiel.to_markdown(ref), "markdown")


if __name__ == "__main__":
    main()
