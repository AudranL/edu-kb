"""Un mini-programme PDF synthétique, composé comme les programmes officiels de 2024-2026 :
titres de couleur, tableaux tracés avec des rectangles fins, en-tête « Objectifs d'apprentissage |
Exemples de réussite », marqueurs temporels en gras dans les cellules."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from edu_kb.outline import DocSpec, HeadingRule

BLUE = (0, 0, 0x91 / 255)
LEFT, MID, RIGHT = 43, 298, 553


def _text(page: pymupdf.Page, x: float, y: float, text: str, size: float = 8.5, bold: bool = False, color=(0, 0, 0)) -> None:
    page.insert_text((x, y), text, fontsize=size, fontname="hebo" if bold else "helv", color=color)


def _grid(page: pymupdf.Page, rows: list[float]) -> None:
    """Bordures dessinées en rectangles pleins de 0,5 pt, comme dans les PDF du ministère."""
    for y in rows:
        page.draw_rect(pymupdf.Rect(LEFT, y, RIGHT, y + 0.5), color=None, fill=(0, 0, 0))
    for x in (LEFT, MID, RIGHT):
        page.draw_rect(pymupdf.Rect(x, rows[0], x + 0.5, rows[-1]), color=None, fill=(0, 0, 0))


def make_programme(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _text(page, LEFT, 60, "Programme de test du cycle 2", size=12, bold=True)
    _text(page, LEFT, 100, "Lecture", size=11, bold=True, color=BLUE)
    _text(page, LEFT, 120, "Cours préparatoire", size=11, color=BLUE)
    _text(page, LEFT, 140, "Identifier les mots", bold=True, color=BLUE)
    _grid(page, [150, 168, 260, 330])
    _text(page, 46, 162, "Objectifs d'apprentissage", bold=True)
    _text(page, 301, 162, "Exemples de réussite", bold=True)
    _text(page, 46, 180, "En fin de période 1", bold=True)
    _text(page, 46, 192, "- Décoder 12 à 15 correspondances")
    _text(page, 54, 203, "graphème-phonème.")
    _text(page, 46, 220, "En fin d'année", bold=True)
    _text(page, 46, 232, "- Lire 30 mots par minute.")
    _text(page, 301, 180, "- L'élève déchiffre les mots réguliers.")
    _text(page, 46, 275, "- Mémoriser les mots fréquents.")
    _text(page, 301, 275, "- Il lit le, la, ami, lune.")
    _text(page, LEFT, 370, "Histoire", size=11, bold=True, color=BLUE)
    _text(page, LEFT, 390, "Cours élémentaire première année", size=11, color=BLUE)
    _text(page, LEFT, 410, "Thème 1 : Les traces du passé (deuxième et troisième périodes)", size=10, bold=True, color=BLUE)
    _text(page, LEFT, 425, "Question : Comment connaît-on le passé ?")
    _grid(page, [435, 453, 500])
    _text(page, 46, 447, "Objectifs d'apprentissage", bold=True)
    _text(page, 301, 447, "Exemples de réussite", bold=True)
    _text(page, 46, 467, "- Identifier des traces du passé.")
    _text(page, 301, 467, "- L'élève classe des objets anciens.")
    _text(page, LEFT, 520, "Mots-clés : archive, musée, patrimoine.")
    doc.save(path)
    return path


def programme_spec(path: Path) -> DocSpec:
    return DocSpec(
        id="test-c2",
        path=path,
        title="Programme de test du cycle 2",
        discipline="Français",
        cycle=2,
        levels=["CP", "CE1"],
        pages=None,
        headings=[
            HeadingRule(rank=1, kind="domaine", style=r"11\.0/B/000091", x_max=60),
            HeadingRule(rank=2, kind="niveau", style=r"11\.0/R/000091", x_max=60),
            HeadingRule(rank=3, kind="theme", style=r"10\.0/B/000091", x_max=60),
            HeadingRule(rank=3, kind="rubrique", style=r"8\.5/B/000091", x_max=60),
        ],
        applies={"CP": (2025, None), "CE1": (2025, 2027)},
        bo="BO de test",
    )


@pytest.fixture(scope="session")
def programme_pdf(tmp_path_factory) -> Path:
    return make_programme(tmp_path_factory.mktemp("pdf") / "programme-test.pdf")


@pytest.fixture
def calendar_file(tmp_path) -> Path:
    path = tmp_path / "calendrier.toml"
    path.write_text(
        """
[2026]
rentree = "2026-09-01"
ete = "2027-07-03"
jours_de_classe = [1, 2, 4, 5]
feries = ["2026-11-11", "2027-03-29", "2027-05-06", "2027-05-07", "2027-05-17"]
toussaint = { debut = "2026-10-17", reprise = "2026-11-02" }
noel = { debut = "2026-12-19", reprise = "2027-01-04" }
[2026.zones.B]
hiver = { debut = "2027-02-20", reprise = "2027-03-08" }
printemps = { debut = "2027-04-17", reprise = "2027-05-03" }
""",
        encoding="utf-8",
    )
    return path
