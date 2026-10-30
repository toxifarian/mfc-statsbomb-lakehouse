import pytest

from pitchlake.integration.identity import name_score, normalise


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Álvaro Borja Morata Martín", "alvaro borja morata martin"),
        ("KANE, Harry", "harry kane"),
        ("Trent Alexander-Arnold", "trent alexander arnold"),
    ],
)
def test_normalise(raw, expected):
    assert normalise(raw) == expected


def test_initial_surname_matches():
    score, method = name_score("H. Kane", "Harry Edward Kane", "Harry Kane")
    assert score >= 90 and method.startswith("initial_surname")


def test_nickname_beats_long_legal_name():
    score, _ = name_score("Joselu", "José Luis Sanmartín Mato", "Joselu")
    assert score == 100


def test_surname_only_is_not_auto_matched():
    score, _ = name_score("Stones", "John Stones", None)
    assert score < 90


def test_different_players_score_low():
    score, _ = name_score("Phil Foden", "Harry Kane", None)
    assert score < 60
