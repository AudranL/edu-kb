from collections import Counter
from datetime import date

from edu_kb.planning import WHOLE_YEAR, Objective, Unit, _allocate_periods, _spread_objectives, _split_weeks, school_weeks


def test_school_weeks_follow_the_calendar(calendar_file):
    weeks = school_weeks(calendar_file, 2026, "B")
    assert Counter(w.period for w in weeks) == {1: 7, 2: 7, 3: 7, 4: 6, 5: 9}
    first = weeks[0]
    assert first.label == "P1-S1" and first.days[0] == date(2026, 9, 1)
    assert all(d.isoweekday() in (1, 2, 4, 5) for w in weeks for d in w.days)
    days = {d for w in weeks for d in w.days}
    assert date(2027, 5, 6) not in days and date(2027, 5, 17) not in days  # Ascension, Pentecôte
    assert date(2026, 10, 19) not in days  # vacances de la Toussaint


def test_split_weeks_is_proportional_and_contiguous(calendar_file):
    weeks = [w for w in school_weeks(calendar_file, 2026, "B") if w.period == 1]
    chunks = _split_weeks(weeks, [3, 1, 1])
    assert [len(c) for c in chunks] == [3, 2, 2]
    assert [w.number for c in chunks for w in c] == [w.number for w in weeks]
    # plus d'unités que de semaines : elles se partagent les semaines
    assert len(_split_weeks(weeks[:2], [1, 1, 1])) == 3


def test_period_counts_from_the_programme_are_chained():
    units = [Unit("HG", "Géographie", "Thème 1", "t1", "theme", nb_periods=(1, 2)),
             Unit("HG", "Géographie", "Thème 2", "t2", "theme", nb_periods=(3, 4))]
    _allocate_periods(units)
    assert [u.periods for u in units] == [[1, 2], [3, 4, 5]]


def test_units_without_hint_are_spread_over_the_year():
    units = [Unit("Maths", "", f"U{i}", f"u{i}", "rubrique") for i in range(3)]
    _allocate_periods(units)
    assert [u.periods for u in units] == [[1], [2, 3], [4, 5]]


def test_unit_is_continuous_when_all_its_objectives_are():
    unit = Unit("Français", "Lecture", "Lire à voix haute", "u", "rubrique")
    assert not unit.continuous  # sans objectif ni drapeau : une unité ordinaire
    unit.objectives = [Objective("a", "i", continuous=True), Objective("b", "i", continuous=True)]
    assert unit.continuous
    unit.objectives.append(Objective("c", "i", span=(1, 1)))  # une échéance précise : l'unité reste programmée
    assert not unit.continuous


def test_objectives_without_deadline_in_a_continuous_discipline_are_listed_apart():
    unit = Unit("Français", "Lecture", "Lire", "u", "rubrique", objectives=[Objective("a", "i"), Objective("b", "i", span=(1, 1))])
    unit.periods = [1]
    _spread_objectives(unit, [])
    assert unit.objectives[0].weeks == []  # un objectif en continu n'a pas de semaine


def test_whole_year_markers_are_recognised():
    for moment in ("Tout au long de l’année", "Au cours des périodes 1 à 5", "En cours d’année"):
        assert WHOLE_YEAR.search(moment)
    assert not WHOLE_YEAR.search("En fin d’année")
