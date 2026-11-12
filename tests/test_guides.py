"""Guides pédagogiques : lecture des pages OCR, graphe, liens au programme, calendrier, transfert.

Les pages sont des OcrPage synthétiques (lignes positionnées comme Vision les rend), au contenu
inventé : les tests ne dépendent ni de macOS (Vision, correcteur), ni d'Ollama, ni d'aucune méthode."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from edu_kb import guide_queries as gq
from edu_kb.extract import read_lines
from edu_kb.graph import GraphBuilder
from edu_kb.guides import (
    GuideFile,
    GuideSpec,
    _footer,
    _sommaire_plan,
    add_guide,
    is_footer,
    load_guides,
    parse_daily_guide,
    parse_weekly_guide,
    running_footer,
)
from edu_kb.kb import KnowledgeBase
from edu_kb.ocr_vision import OcrLine, OcrPage, _correctable, candidates, correct
from edu_kb.outline import parse_document
from edu_kb.transfer import TransferError, export_base, import_base

from .conftest import programme_spec


def L(text: str, x: float, y: float, w: float = 0.18, conf: float = 1.0) -> OcrLine:
    return OcrLine(text, conf, x, y, x + w, y + 0.01)


def page(number: int, lines: list[OcrLine]) -> OcrPage:
    return OcrPage(number, 1190, 842, lines)


# --------------------------------------------------------------------------- correction de l'OCR
class FakeSpeller:
    def __init__(self, words: set[str]):
        self.words = words

    def valid(self, words: list[str]) -> dict[str, bool]:
        return {w: w in self.words or any(c.isdigit() for c in w) for w in words}


def test_a_misread_as_o_or_digit_is_repaired_only_into_real_words():
    speller = FakeSpeller({"les", "rangs", "dans", "pratique", "guidée", "il", "y", "a", "des", "appelle", "elle", "s"})
    assert correct(["dons les rongs", "Pr1tique guidée", "il y o des", "elle s'ppelle"], speller) == [
        "dans les rangs", "Pratique guidée", "il y a des", "elle s'appelle"]


def test_graphemes_and_pseudo_words_in_capitals_are_left_alone():
    speller = FakeSpeller({"al", "carte", "repère"})
    assert correct(["Carte repère Ol", "TOVI MALU"], speller) == ["Carte repère Ol", "TOVI MALU"]
    assert not _correctable("Ol") and not _correctable("OU") and _correctable("lo")


def test_candidates_never_keep_a_digit():
    assert "pratique" in candidates("pr1tique")
    assert all(not any(ch.isdigit() for ch in c) for c in candidates("pr1tique"))


# --------------------------------------------------------------------------- pied de page
def test_page_number_is_read_at_the_end_of_any_footer():
    foot = "PÉRIODE 2 | GUIDE DE L'ENSEIGNANT | UNE MÉTHODE {}"
    pages = [page(i, [L(foot.format(n), 0.77, 0.965, 0.2)]) for i, n in enumerate((43, 45, 47), 1)]
    running = running_footer(pages)  # appris dans le fichier : rien n'est supposé de son texte
    assert _footer(pages[1], running) == (2, 45)
    # tronqué ou mal lu, c'est encore le pied de page
    assert _footer(page(9, [L("ANT I UNE MÉTHODE 49", 0.8, 0.96, 0.1)]), running) == (None, 49)
    # seul le numéro de la page de gauche est lu : celui de droite le suit
    assert _footer(page(9, [L("50", 0.03, 0.965, 0.02)]), running) == (None, 51)
    # du texte d'une page mal cadrée qui descend tout en bas reste du texte
    assert not is_footer(L("• Corriger collectivement au tableau. 12", 0.52, 0.95, 0.2), running)


# --------------------------------------------------------------------------- guide par jour
def spread(footer: str, lines: list[OcrLine], number: int = 1) -> OcrPage:
    return page(number, lines + [L(footer, 0.77, 0.965, 0.2)])


def day_lines(marker: list[OcrLine] | None = None, jour: str = "JOUR 1", second: str = "Lire le graphème") -> list[OcrLine]:
    return [
        L(jour, 0.23, 0.05, 0.2),
        *(marker or []),
        L("RITUELS", 0.02, 0.21, 0.05), L("& 15 minutes", 0.16, 0.214, 0.07),
        L("• Relire les graphèmes de la semaine au tableau.", 0.02, 0.232),
        L("SÉANCE 1", 0.02, 0.385, 0.11), L("& 40 minutes", 0.16, 0.402, 0.07),
        L("Identifier et discriminer", 0.02, 0.42, 0.16), L("le graphème", 0.02, 0.445, 0.09),
        L("MISE EN SITUATION Oral collectif", 0.02, 0.53, 0.11),
        L("• Annoncer le graphème du jour.", 0.02, 0.542),
        L("MISE EN ACTIVITÉ Oral collectif", 0.25, 0.26, 0.11),
        L("• Dire des mots qui contiennent le son.", 0.25, 0.27),
        L("• P12 N1 Relire la page du manuel.", 0.25, 0.30),
        L("SÉANCE 2", 0.52, 0.20, 0.11), L("& 10 minutes", 0.65, 0.22, 0.07),
        L(second, 0.52, 0.24, 0.14),
        L("MISE EN SITUATION Oral collectif", 0.52, 0.33, 0.11),
        L("• Lire les syllabes écrites au tableau.", 0.52, 0.34),
        L("• Lire en chœur puis chacun son tour.", 0.75, 0.20),
        L("• Lire la ligne de l'exercice du manuel.", 0.75, 0.22),
    ]


FOOT = "PÉRIODE {} | GUIDE DE L'ENSEIGNANT | UNE MÉTHODE DE LECTURE {}"
ALBUM = [L("Lire un album La cabane", 0.03, 0.05, 0.3)]


def daily_files(tmp_path: Path) -> list[tuple[GuideFile, list[OcrPage]]]:
    p1 = [
        spread(FOOT.format(1, 23), day_lines([L("Carte repère A", 0.02, 0.37, 0.06)]), 1),
        spread(FOOT.format(1, 25), day_lines(jour="JOUR Z"), 2),
        spread(FOOT.format(1, 27), day_lines(ALBUM, jour="", second="Raconter le début"), 3),
    ]
    p2 = [
        # la dernière double page de la période 1, rescannée au début du fichier suivant
        spread(FOOT.format(1, 27), day_lines(ALBUM, jour="", second="Raconter le début"), 1),
        # un autre album : jamais confondu avec le premier
        spread(FOOT.format(2, 29), day_lines([L("Lire un album Le phare", 0.03, 0.05, 0.3)], jour="", second="Raconter la fin"), 2),
        # même numéro de page lu par erreur, mais une autre leçon : gardée
        spread(FOOT.format(2, 29), day_lines([L("Carte repère CH", 0.02, 0.37, 0.06)], second="Écrire des syllabes"), 3),
    ]
    return [(GuideFile(tmp_path / "p1.pdf", 1), p1), (GuideFile(tmp_path / "p2.pdf", 2), p2)]


def test_daily_guide_days_lessons_and_seances(tmp_path):
    notes: list[str] = []
    units, _ = parse_daily_guide(daily_files(tmp_path), log=notes.append)
    assert [(u.period, u.kind, u.title, len(u.days)) for u in units] == [
        (1, "graphème", "Graphème A", 2),
        (1, "lecture", "Lire un album La cabane", 1),
        (2, "lecture", "Lire un album Le phare", 1),
        (2, "graphème", "Graphème CH", 1),
    ]
    a = units[0]
    assert [(d.rank, d.day_in_unit, d.pages) for d in a.days] == [(1, 1, [22, 23]), (2, 2, [24, 25])]
    rituels, s1, s2 = a.days[0].seances
    assert (rituels.kind, rituels.minutes) == ("rituels", 15)
    assert (s1.number, s1.title, s1.minutes) == (1, "Identifier et discriminer le graphème", 40)
    assert s1.phases == ["Mise en situation", "Mise en activité"]
    assert "P12 N1" in s1.references
    assert (s2.number, s2.title, s2.minutes) == (2, "Lire le graphème", 10)
    assert s2.lines[-1] == "• Lire la ligne de l'exercice du manuel."  # la colonne suivante continue la séance
    assert any("26-27" in n and "doublon" in n for n in notes)  # le doublon est signalé


def test_only_the_same_spread_read_twice_is_dropped(tmp_path):
    units, _ = parse_daily_guide(daily_files(tmp_path))
    assert [u.title for u in units if u.kind == "lecture"] == ["Lire un album La cabane", "Lire un album Le phare"]
    assert [d.rank for u in units if u.period == 2 for d in u.days] == [1, 2]


# --------------------------------------------------------------------------- guide par semaine
def sommaire_page() -> OcrPage:
    return page(4, [
        L("Sommaire", 0.11, 0.036, 0.15), L("Sommaire par période", 0.08, 0.10, 0.5),
        L("PÉRIODE 1", 0.42, 0.16, 0.1),
        L("1 Nombres jusqu'à 10", 0.10, 0.19, 0.2), L("38", 0.43, 0.19, 0.02),
        L("Rangs et positions®", 0.11, 0.22, 0.14), L("44", 0.43, 0.22, 0.02),
        L("12", 0.50, 0.22, 0.02),  # numéro de séquence isolé, pas aligné : ce n'est pas une page
        L("PÉRIODE 2", 0.42, 0.25, 0.1),
        L("Solides", 0.11, 0.28, 0.1), L("50", 0.43, 0.28, 0.02),
    ])


def test_sommaire_page_numbers_are_the_right_aligned_column():
    assert _sommaire_plan(sommaire_page(), last_page=60) == [(1, 38), (1, 44), (2, 50)]


def weekly_pages() -> list[OcrPage]:
    start = page(38, [
        L("Nombres jusqu'à 10", 0.14, 0.035, 0.3),
        L("OBJECTIFS D'APPRENTISSAGE DU PROGRAMME 2025", 0.14, 0.068, 0.3),
        L("Décoder 12 à 15 correspondances graphème-phonème", 0.14, 0.078, 0.5),
        L("SÉANCE 1", 0.09, 0.13, 0.14), L("Compter des jetons", 0.09, 0.164, 0.25),
        L("Réactivation", 0.22, 0.206, 0.09),
        L("• Annoncer ce que l'on va apprendre.", 0.09, 0.237, 0.3),
        L("• Faire compter les jetons de la boîte.", 0.09, 0.27, 0.3),
        L("ACTIVITÉ ÉLÈVE", 0.49, 0.13, 0.08), L("• Compter à voix haute.", 0.49, 0.147, 0.3),
        L("• Écrire le nombre sur l'ardoise.", 0.49, 0.167, 0.3),
    ])
    suite = page(39, [
        L("• Faire le point sur ce qui a été appris.", 0.15, 0.08, 0.3),
        L("• Lire les nombres dans l'ordre croissant.", 0.15, 0.10, 0.3),
        L("SÉANCE 2", 0.15, 0.30, 0.14), L("Comparer deux tas", 0.15, 0.33, 0.25),
        L("• Donner deux tas de jetons à chaque binôme.", 0.15, 0.36, 0.3),
        L("• Trouver le tas qui en a le plus.", 0.15, 0.38, 0.3),
    ])
    atelier = page(41, [
        L("ATELIER", 0.52, 0.044, 0.05), L("PROBLÈMES", 0.46, 0.054, 0.15),
        L("Résoudre des problèmes de partage", 0.39, 0.099, 0.28),
        L("MATÉRIEL", 0.15, 0.128, 0.06), L("- des jetons et des boîtes", 0.15, 0.142, 0.26),
        L("SÉANCE 1", 0.15, 0.181, 0.14), L("Mise en situation", 0.27, 0.227, 0.12),
        L("• Lire l'énoncé à voix haute.", 0.15, 0.257, 0.3),
        L("• Faire reformuler la question.", 0.15, 0.29, 0.3),
    ])
    calcul = page(42, [
        L("OBJECTIFS D'APPRENTISSAGE DU PROGRAMME 2025", 0.37, 0.049, 0.25), L("CALCUL", 0.23, 0.051, 0.05),
        L("Lire 30 mots par minute", 0.37, 0.06, 0.3), L("MENTAL", 0.20, 0.063, 0.1),
        L("Ajouter un", 0.17, 0.099, 0.16),
        L("SÉANCE 1", 0.09, 0.139, 0.14), L("30 min", 0.40, 0.154, 0.05),
        L("• Ajouter un jeton dans la boîte.", 0.09, 0.2, 0.3),
        L("• Demander combien il y en a maintenant.", 0.09, 0.22, 0.3),
        L("FLASH", 0.73, 0.083, 0.05), L("MATHS", 0.71, 0.097, 0.09),
        L("Suites de gestes", 0.65, 0.154, 0.2),
        L("FLASH MATHS A", 0.60, 0.183, 0.09), L("• Refaire une suite de gestes.", 0.59, 0.218, 0.28),
        L("• Continuer la suite.", 0.59, 0.24, 0.28),
        L("FLASH MATHS", 0.61, 0.311, 0.09), L("• Coder la suite avec des symboles.", 0.59, 0.346, 0.26),
    ])
    presentation = page(43, [L("PÉRIODE", 0.44, 0.09, 0.1), L("Calcul mental", 0.7, 0.05, 0.1)])
    seq2 = page(44, [L("Rangs et positions ®", 0.14, 0.03, 0.2), L("SÉANCE 1", 0.09, 0.13, 0.14),
                     L("Ranger des objets", 0.09, 0.16, 0.2), L("• Ranger les élèves en file.", 0.09, 0.2, 0.3)])
    seq3 = page(50, [L("Solides", 0.14, 0.03, 0.2), L("SÉANCE 1", 0.09, 0.13, 0.14),
                     L("Trier des objets", 0.09, 0.16, 0.2), L("• Trier selon la forme.", 0.09, 0.2, 0.3)])
    return [sommaire_page(), start, suite, atelier, calcul, presentation, seq2, seq3]


def test_weekly_guide_sequences_and_weekly_parts():
    s1, s2, s3 = parse_weekly_guide(weekly_pages())
    assert (s1.period, s1.number, s1.title) == (1, 1, "Nombres jusqu'à 10")
    assert s1.objectives == ["Décoder 12 à 15 correspondances graphème-phonème"]
    assert s1.atelier == "Résoudre des problèmes de partage"
    assert (s1.calcul, s1.calcul_objectives) == ("Ajouter un", ["Lire 30 mots par minute"])
    assert [(s.kind, s.number) for s in s1.seances] == [
        ("séance", 1), ("séance", 2), ("atelier problèmes", 1), ("calcul mental", 1), ("flash maths", 1), ("flash maths", 2)]
    first = s1.seances[0]
    assert first.title == "Compter des jetons"
    assert first.lines[-1] == "• Lire les nombres dans l'ordre croissant."  # suite en haut de la page suivante
    assert first.pages == [38, 39]
    assert s1.seances[2].lines[0] == "MATÉRIEL"  # le matériel de l'atelier ouvre sa première séance
    assert s1.seances[3].minutes == 30 and s1.seances[3].title == "Ajouter un"
    assert {s.title for s in s1.seances[4:]} == {"Suites de gestes"}
    assert s1.pages == [38, 39, 41, 42]  # la séquence s'arrête à ses flash maths
    assert (s2.number, s2.title) == (2, "Rangs et positions")
    assert (s3.period, s3.title) == (2, "Solides")


# --------------------------------------------------------------------------- configuration de la classe
def test_each_class_describes_its_own_guides(tmp_path):
    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "Lecture periode 1.pdf").write_bytes(b"%PDF")
    config = tmp_path / "guides.toml"
    config.write_text('dossier = "pdf"\n[[guide]]\nid = "lecture"\ntitre = "Ma méthode"\ndiscipline = "Français"\n'
                      'niveau = "CP"\nrythme = "jour"\nfichiers = [{ periode = 1, file = "Lecture*1.pdf" }]\n', encoding="utf-8")
    specs, warnings = load_guides(config, tmp_path / "programmes")
    assert not warnings and specs[0].files[0].path.name == "Lecture periode 1.pdf"
    assert specs[0].rhythm_text.startswith("Tout est détaillé par jour")
    config.write_text(config.read_text(encoding="utf-8").replace('"jour"', '"mois"'), encoding="utf-8")
    with pytest.raises(ValueError, match="rythme 'mois' inconnu"):
        load_guides(config, tmp_path)


# --------------------------------------------------------------------------- graphe, fiches, calendrier
class KeywordEmbedder:
    """Vecteurs de mots-clés : assez pour vérifier que le sens relie une séance à un objectif."""
    model = "mots-cles"
    words = ("décod", "graphème", "phonème", "lire", "mots", "passé", "trace", "mémoris")

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.array([[t.lower().count(w) for w in self.words] + [0.01] for t in texts], dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


DAILY = GuideSpec(id="lecture", title="Méthode de lecture", discipline="Français", level="CP", rhythm="jour",
                  files=[], programme_year=2025)
WEEKLY = GuideSpec(id="semaine", title="Méthode à la semaine", discipline="Français", level="CP", rhythm="semaine",
                   files=[], programme_year=2025)


@pytest.fixture
def guides_kb(tmp_path, programme_pdf) -> KnowledgeBase:
    spec = programme_spec(programme_pdf)
    builder = GraphBuilder()
    builder.add_source(spec, parse_document(spec, read_lines(programme_pdf), programme_pdf), "hash")
    graph = builder.finish()
    units, _ = parse_daily_guide(daily_files(tmp_path))
    position = add_guide(graph, DAILY, units)
    add_guide(graph, WEEKLY, parse_weekly_guide(weekly_pages()), position=position)
    kb = KnowledgeBase(tmp_path / "kb-guides.sqlite", KeywordEmbedder())
    kb.replace_graph(graph)
    return kb


def test_objectives_cited_by_a_guide_link_it_to_the_programme(guides_kb):
    seq = "guide:semaine/p1/sequence-1"
    card = gq.card(guides_kb, seq)
    assert card["objectifs_cites"] == ["Décoder 12 à 15 correspondances graphème-phonème"]
    assert card["programme"][0]["objectif"] == "Décoder 12 à 15 correspondances graphème-phonème."
    assert card["programme"][0]["origine"] == "objectif cité par le guide"
    item = card["programme"][0]["item"]
    assert any(g["id"] == seq for g in gq.card(guides_kb, item)["dans_les_guides"])


def test_seances_are_linked_to_the_programme_by_meaning(guides_kb):
    guides_kb.embed_missing()
    assert guides_kb.link_guides(threshold=0.5) > 0
    card = gq.card(guides_kb, "guide:lecture/p1/grapheme-1/j1/s2")
    assert card["seance"]["numero"] == 1 and card["seance"]["duree_minutes"] == 40
    assert card["deroule"][0] == "MISE EN SITUATION Oral collectif"
    assert any(p["origine"] == "rapprochement par le sens" and "graphème" in p["objectif"] for p in card["programme"])


def test_guide_search_finds_a_seance(guides_kb):
    hits = gq.search(guides_kb, "Identifier et discriminer le graphème")
    assert hits and hits[0]["type"] == "seance" and "Identifier" in hits[0]["titre"]


def test_guides_list_their_rhythm(guides_kb):
    assert [(g["titre"], g["rythme"]) for g in gq.guides(guides_kb)] == [
        ("Méthode de lecture", "jour"), ("Méthode à la semaine", "semaine")]


def test_guide_days_follow_the_class_days_of_the_period(guides_kb, calendar_file):
    # rentrée le mardi 1er septembre 2026 (semaine de 4 jours) : jour 1 du guide, puis jeudi 3 : jour 2
    tuesday = gq.day_plan(guides_kb, calendar_file, date(2026, 9, 1))
    by_guide = {g["guide"]: g for g in tuesday["guides"]}
    assert by_guide["Méthode de lecture"]["unite"]["titre"] == "Graphème A"
    assert by_guide["Méthode de lecture"]["jour_du_guide"]["jour_de_la_lecon"] == 1
    weekly = by_guide["Méthode à la semaine"]
    assert weekly["unite"]["numero"] == 1
    assert [s["type"] for s in weekly["seances"]] == ["séance", "calcul mental", "flash maths"]
    assert [s["type"] for s in weekly["dans_la_semaine"]] == ["atelier problèmes"]
    thursday = gq.day_plan(guides_kb, calendar_file, date(2026, 9, 3))
    daily = next(g for g in thursday["guides"] if g["guide"] == "Méthode de lecture")
    assert daily["jour_du_guide"]["jour_de_la_lecon"] == 2
    assert not gq.day_plan(guides_kb, calendar_file, date(2026, 9, 2))["classe"]  # mercredi
    assert gq.day_plan(guides_kb, calendar_file, date(2026, 10, 20))["message"].startswith("Pas de classe cette semaine")


def test_period_plan_lists_weeks_and_days_without_content(guides_kb, calendar_file):
    plan = gq.period_plan(guides_kb, calendar_file, 2026, "B", 1)
    first = plan["semaines"][0]
    assert first["sequences"][0]["titre"] == "Nombres jusqu'à 10"
    assert first["jours"][0]["date"] == "2026-09-01"
    assert plan["semaines"][1]["sequences"][0]["titre"] == "Rangs et positions"
    assert plan["jours_sans_contenu"]["Méthode de lecture"]  # le guide de test n'a que 3 jours en période 1
    assert "rien de prévu" in gq.period_markdown(plan)


# --------------------------------------------------------------------------- transfert (clé USB)
def test_the_guides_base_goes_to_another_computer_by_usb(guides_kb, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    assert export_base(guides_kb.db_path, usb) == ["Méthode de lecture", "Méthode à la semaine"]
    copy = usb / "kb-guides.sqlite"
    assert copy.exists() and not (usb / "kb-guides.sqlite-wal").exists()
    with pytest.raises(TransferError, match="existe déjà"):
        export_base(guides_kb.db_path, usb)
    other = tmp_path / "autre-poste" / ".edu-kb"
    built_at, guides = import_base(copy, other / "kb-guides.sqlite", other / "kb.sqlite")
    assert built_at and guides == ["Méthode de lecture", "Méthode à la semaine"]
    assert gq.guides(KnowledgeBase(other / "kb-guides.sqlite"))[0]["jours"] == 5  # 3 en période 1, 2 en période 2
    with pytest.raises(TransferError, match="base publiée"):
        import_base(copy, other / "kb.sqlite", other / "kb.sqlite")


def test_a_file_that_is_not_a_guides_base_is_refused(tmp_path):
    bogus = tmp_path / "photo.sqlite"
    bogus.write_bytes(b"pas une base")
    with pytest.raises(TransferError, match="pas une base edu-kb"):
        import_base(bogus, tmp_path / "kb-guides.sqlite", tmp_path / "kb.sqlite")


def test_build_refuses_to_put_guides_in_the_published_base(tmp_path, monkeypatch):
    from edu_kb.cli import main

    monkeypatch.setenv("EDU_KB_HOME", str(tmp_path))
    monkeypatch.setenv("EDU_KB_DB", str(tmp_path / "kb.sqlite"))
    with pytest.raises(SystemExit, match="base publiée"):
        main(["build", "--guides", "--no-embed"])
