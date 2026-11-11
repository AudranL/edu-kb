from edu_kb.extract import read_lines
from edu_kb.outline import Line, OutlineParser, column_field, levels_of, parse_document, parse_moment

from .conftest import programme_spec


def test_moments_give_the_periods_named_by_the_programme():
    assert parse_moment("En fin de période 1") == ("En fin de période 1", (1, 1))
    assert parse_moment("En milieu d’année") == ("En milieu d’année", (3, 3))
    assert parse_moment("En fin d’année") == ("En fin d’année", (5, 5))
    assert parse_moment("À partir de la période 2") == ("À partir de la période 2", (2, 5))
    assert parse_moment("Dès la 2e période") == ("Dès la 2e période", (2, 5))
    assert parse_moment("Tout au long de l’année") == ("Tout au long de l’année", (1, 5))
    assert parse_moment("Lire 30 mots par minute à la fin de la période") is None


def test_level_headings_are_recognised():
    assert levels_of("Cours préparatoire") == ["CP"]
    assert levels_of("Cours élémentaire deuxième année") == ["CE2"]
    assert levels_of("Cours moyen première et deuxième années") == ["CM1", "CM2"]
    assert levels_of("CE1 : Respecter les autres") == ["CE1"]
    assert levels_of("Classe de CM2") == ["CM2"]
    assert levels_of("Sixième : premiers humains") == ["6e"]
    assert levels_of("Identifier les mots") is None


def test_column_labels_survive_missing_spaces_and_line_breaks():
    assert column_field("Objectifsd’apprentissage") == "objectifs"
    assert column_field("Attendus (connaissances et compétences)") == "attendus"
    assert column_field("Connaissances et compétences attendues en fin de cours moyen") == "connaissances_cm"
    assert column_field("Exemples de situations, d’activités et de ressources pour l’élève") == "exemples_situations"
    assert column_field("Lire avec fluidité") is None


def test_two_labels_merged_on_one_line_are_split():
    line = Line(1, 77, 170, 520, 181, 11.0, True, 0, "Arial-Bold",
                "Connaissances et compétences associées Exemples de situations, d’activités et de")
    pieces = OutlineParser._label_pieces(line)
    assert [column_field(p.text) for p in pieces] == ["connaissances", "exemples_situations"]
    assert pieces[0].x1 <= pieces[1].x0


def _line(y: float, text: str, bold: bool = False, x: float = 46) -> Line:
    return Line(1, x, y, x + 5 * len(text), y + 10, 8.5, bold, 0, "Marianne", text)


def test_enumeration_intro_becomes_the_heading_of_its_items(programme_pdf):
    lines = [
        _line(100, "Objectifs d'apprentissage", bold=True),
        _line(115, "- Développer tout au long de l'année les compétences qui"),
        _line(125, "lui permettront en fin d'année :"),
        _line(140, "- d'écrire pour transmettre un message ;"),
        _line(155, "- de relire son texte méthodiquement."),
        _line(170, "3 10 10 × 7 = 70"),
    ]
    root = OutlineParser(programme_spec(programme_pdf), lines, {}).parse()
    bullets = root.items[0].fields["objectifs"]
    assert [b.text for b in bullets] == ["d'écrire pour transmettre un message ;", "de relire son texte méthodiquement. 3 10 10 × 7 = 70"]
    assert bullets[0].group == "Développer tout au long de l'année les compétences qui lui permettront en fin d'année"


def test_synthetic_programme_outline(programme_pdf):
    spec = programme_spec(programme_pdf)
    root = parse_document(spec, read_lines(programme_pdf), programme_pdf)
    lecture, histoire = root.children
    assert (lecture.kind, lecture.title) == ("domaine", "Lecture")
    cp = lecture.children[0]
    assert (cp.kind, cp.levels) == ("niveau", ["CP"])
    rubrique = cp.children[0]
    assert rubrique.title == "Identifier les mots"
    first, second = rubrique.items
    objectifs = first.fields["objectifs"]
    assert objectifs[0].text == "Décoder 12 à 15 correspondances graphème-phonème."
    assert (objectifs[0].moment, objectifs[0].periods) == ("En fin de période 1", (1, 1))
    assert (objectifs[1].moment, objectifs[1].periods) == ("En fin d'année", (5, 5))
    assert [b.text for b in first.fields["exemples_reussite"]] == ["L'élève déchiffre les mots réguliers."]
    assert [b.text for b in second.fields["objectifs"]] == ["Mémoriser les mots fréquents."]

    theme = histoire.children[0].children[0]
    assert theme.kind == "theme"
    assert theme.attrs["question"] == "Comment connaît-on le passé ?"
    assert theme.attrs["mots_cles"] == "archive, musée, patrimoine."
    assert [b.text for b in theme.items[0].fields["objectifs"]] == ["Identifier des traces du passé."]
