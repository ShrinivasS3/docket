import pytest

from docket.stem import stem


@pytest.mark.parametrize(
    "word, expected",
    [
        ("aggregation", "aggreg"),
        ("aggregate", "aggreg"),
        ("aggregates", "aggreg"),
        ("oscillator", "oscil"),
        ("oscillators", "oscil"),
        ("oscillation", "oscil"),
        ("oscillate", "oscil"),
        ("temporal", "tempor"),
        ("temporally", "tempor"),
        ("caresses", "caress"),
        ("ponies", "poni"),
        ("cats", "cat"),
        ("hopping", "hop"),
        ("running", "run"),
        ("relational", "relat"),
        ("conditional", "condit"),
        ("generalization", "gener"),
        ("feed", "feed"),
        ("mediapipe", "mediapip"),
        ("sky", "sky"),
        ("mp", "mp"),
        ("x0002", "x0002"),
    ],
)
def test_porter_pairs(word, expected):
    assert stem(word) == expected


def test_related_forms_share_a_stem():
    assert stem("aggregation") == stem("aggregate") == stem("aggregating")
    assert stem("oscillator") == stem("oscillators") == stem("oscillating")
