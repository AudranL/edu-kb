import csv
import io

import pytest

from edu_kb import referentiel
from edu_kb.extract import read_lines
from edu_kb.graph import GraphBuilder
from edu_kb.kb import KnowledgeBase
from edu_kb.outline import parse_document

from .conftest import programme_spec


@pytest.fixture
def kb(tmp_path, programme_pdf):
    spec = programme_spec(programme_pdf)
    builder = GraphBuilder()
    builder.add_source(spec, parse_document(spec, read_lines(programme_pdf), programme_pdf), "hash")
    kb = KnowledgeBase(tmp_path / "kb.sqlite")
    kb.replace_graph(builder.finish())
    return kb


def test_referentiel_lists_the_competences_of_a_level(kb):
    ref = referentiel.build(kb, "CE1", 2026)
    assert ref["niveau"] == "CE1" and ref["annee_scolaire"] == "2026-2027" and ref["cycle"] == 2
    assert [d["discipline"] for d in ref["disciplines"]] == ["Français"]
    texts = [c["texte"] for d in ref["disciplines"][0]["domaines"] for c in d["competences"]]
    assert "Identifier des traces du passé." in texts
    assert ref["disciplines"][0]["source"]["bo"] == "BO de test"


def test_referentiel_follows_the_school_year(kb):
    # le programme de test s'applique au CE1 jusqu'en 2027 exclu
    assert referentiel.build(kb, "CE1", 2027)["disciplines"] == []


def test_referentiel_renders_a_checklist_and_a_csv(kb):
    ref = referentiel.build(kb, "CE1", 2026)
    assert "- [ ] Identifier des traces du passé." in referentiel.to_markdown(ref)
    rows = list(csv.DictReader(io.StringIO(referentiel.to_csv(ref)), delimiter=";"))
    assert rows and {"discipline", "domaine", "competence", "echeance", "en_continu", "criteres_de_reussite"} <= set(rows[0])
    assert {r["niveau"] for r in rows} == {"CE1"}


def test_trailing_connectors_and_semicolons_are_removed():
    assert referentiel._text({"texte": "Comprendre ses émotions ;"}) == "Comprendre ses émotions"
    assert referentiel._text({"texte": "Décrire un château ou"}) == "Décrire un château"
