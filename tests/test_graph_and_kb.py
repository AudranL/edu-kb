import pytest

from edu_kb.extract import read_lines
from edu_kb.graph import GraphBuilder, clean_title, period_hint, working_spans
from edu_kb.kb import KnowledgeBase, fts_query, school_year
from edu_kb.outline import parse_document

from .conftest import programme_spec


def test_period_hints_in_theme_titles():
    assert period_hint("Thème 2 : La monarchie (deuxième et troisième périodes)")["periodes"] == [2, 3]
    assert period_hint("Thème 1 : Se nourrir (1 ou 2 périodes au choix)")["nb_periodes"] == [1, 2]
    assert period_hint("Thème 1 : Autour de l’école (trois périodes)")["nb_periodes"] == [3, 3]
    assert period_hint("Les fractions") is None
    assert clean_title("Thème 3 : Se déplacer (1 période)") == "Thème 3 : Se déplacer"


def test_deadlines_become_working_periods():
    bullets = [
        {"moment": "En fin de période 1", "periodes": [1, 1]},
        {"moment": "En fin de période 1", "periodes": [1, 1]},
        {"moment": "En milieu d’année", "periodes": [3, 3]},
        {"moment": "En fin d'année", "periodes": [5, 5]},
        {"texte": "sans moment"},
    ]
    assert working_spans(bullets) == [(1, 1), (1, 1), (2, 3), (4, 5), None]
    assert working_spans([{"moment": "Dès le début de l’année", "periodes": [1, 5]}]) == [(1, 5)]


def test_school_year_parsing():
    assert school_year("2026-2027") == 2026
    assert school_year(2027) == 2027
    with pytest.raises(ValueError):
        school_year("l'an prochain")


def test_fts_query_truncates_plurals():
    assert fts_query("les fractions") == '"fraction"*'
    assert fts_query("calcul mental") == '"calcul mental" OR "calcul"* OR "mental"*'


@pytest.fixture
def kb(tmp_path, programme_pdf):
    spec = programme_spec(programme_pdf)
    builder = GraphBuilder()
    builder.add_source(spec, parse_document(spec, read_lines(programme_pdf), programme_pdf), "hash")
    kb = KnowledgeBase(tmp_path / "kb.sqlite")
    kb.replace_graph(builder.finish())
    return kb


def test_search_filters_on_level_and_school_year(kb):
    hits = kb.search("décoder correspondances", level="CP", year=2026).hits
    assert hits and hits[0].discipline == "Français" and "CP" in hits[0].levels
    # le texte cesse de s'appliquer au CE1 à la rentrée 2027
    assert kb.search("traces du passé", level="CE1", year=2026).hits
    assert not kb.search("traces du passé", level="CE1", year=2027).hits


def test_item_card_gives_objectives_competences_and_theme(kb):
    hit = kb.search("traces du passé", level="CE1", year=2026, kinds=("item",)).hits[0]
    card = kb.item_card(hit.id, 2026)
    assert card["objectifs"][0]["texte"] == "Identifier des traces du passé."
    assert card["competences"]["attendus_de_l_item"]["Exemples de réussite"] == ["L'élève classe des objets anciens."]
    assert {s["code"] for s in card["competences"]["socle_commun"]} >= {"D1.1"}
    theme = card["themes"][0]
    assert theme["theme"] == "Thème 1 : Les traces du passé"
    assert theme["periodes_programme"]["periodes"] == [2, 3]
    assert card["source"]["bo"] == "BO de test"


def test_themes_of_a_level(kb):
    assert [t["theme"] for t in kb.themes("CE1", year=2026)] == ["Thème 1 : Les traces du passé"]
    assert kb.themes("CP", year=2026) == []


def test_search_filters_by_level_before_ranking(kb):
    """Le niveau demandé est appliqué avant le classement : pas de résultats d'un autre niveau, pas de bruit."""
    hits = kb.search("traces du passé", level="CE1", year=2026).hits
    assert hits and all("CE1" in h.levels for h in hits)
    assert kb.search("traces du passé", level="CP", year=2026, discipline="Français").hits is not None


def test_fts_phrase_keeps_the_whole_expression():
    from edu_kb.kb import fts_phrase

    assert fts_phrase("le Moyen Âge") == '"moyen age"'
    assert fts_phrase("fractions") is None
