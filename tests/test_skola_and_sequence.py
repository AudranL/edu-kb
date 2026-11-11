import csv
import io

import pytest

from edu_kb import sequence, skola
from edu_kb.extract import read_lines
from edu_kb.graph import GraphBuilder
from edu_kb.kb import KnowledgeBase
from edu_kb.outline import parse_document
from edu_kb.planning import build_plan

from .conftest import programme_spec


@pytest.fixture
def kb(tmp_path, programme_pdf):
    spec = programme_spec(programme_pdf)
    builder = GraphBuilder()
    builder.add_source(spec, parse_document(spec, read_lines(programme_pdf), programme_pdf), "hash")
    kb = KnowledgeBase(tmp_path / "kb.sqlite")
    kb.replace_graph(builder.finish())
    return kb


def test_skola_export_mirrors_skola_tables(kb, calendar_file):
    data = skola.export(kb, build_plan(kb, calendar_file, "CE1", 2026, "B"))
    assert data["classe"] == {"niveau": "CE1", "annee_scolaire": "2026-2027", "zone": "B"}
    assert data["subjects"] == [{"name": "Français", "color": "#2563eb"}]
    seq = data["sequences"][0]
    assert seq["title"] == "Thème 1 : Les traces du passé" and seq["level"] == "CE1"
    assert "- Identifier des traces du passé." in seq["objectives"]
    # le thème est placé sur les périodes 2 et 3 que le programme lui donne
    periods = {i["period"] for i in data["programmation_items"] if i["sequence_ref"] == seq["ref"]}
    assert periods == {2, 3}
    assert {"subject", "period", "title", "domain", "status", "position"} <= set(data["programmation_items"][0])
    week_of_p2 = next(w for w in data["progression"] if w["periode"] == 2)
    assert week_of_p2["entrees"][0]["titre"] == "Thème 1 : Les traces du passé"
    rows = list(csv.DictReader(io.StringIO(skola.to_csv(data)), delimiter=";"))
    assert rows and rows[0]["discipline"] == "Français"
    assert "| **Français** |" in skola.to_markdown(data)


def test_sequence_from_a_notion(kb):
    data = sequence.prepare(kb, "traces du passé", "CE1", 2026)
    assert data["trouve"] and data["discipline"] == "Français"
    assert [o["texte"] for o in data["objectifs"]] == ["Identifier des traces du passé."]
    assert data["periodes_indiquees_par_le_programme"] == [2, 3]
    assert data["seances"][-1]["titre"] == "Évaluation"
    out = sequence.to_skola(data)
    assert out["sequences"][0]["level"] == "CE1"
    assert out["preps"][0]["seance_number"] == 1 and out["preps"][0]["phases"]


def test_unknown_notion_says_so(kb):
    data = sequence.prepare(kb, "volcans sous-marins", "CP", 2026)
    assert not data["trouve"] and "Aucun item" in data["message"]


def test_orphan_connectors_are_removed_from_criteria():
    from edu_kb.sequence import _clean, _short

    assert _clean("Raconter la vie quotidienne (calendrier, etc.). ou") == "Raconter la vie quotidienne (calendrier, etc.)."
    assert _clean("Décrire un château") == "Décrire un château"
    assert _short("Les cadres de la vie : la seigneurie (la domination d’un seigneur)") == "Les cadres de la vie"
    assert _short("mot " * 40).endswith("…") and len(_short("mot " * 40)) <= 91
