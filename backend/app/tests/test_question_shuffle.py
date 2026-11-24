"""Unit tests for option shuffling in question_generator.py.

Verifies the core invariant: after shuffling the 4 options, the correct
answer still points to the SAME TEXT — i.e.
``shuffled[new_correct_index] == options[correct_index]`` — regardless of
the random shuffle outcome. The model tends to return correct_index 0, so
that case is covered explicitly.
"""

import random

import pytest

from app.services.question_generator import _shuffle_options


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _options() -> list[str]:
    """Four distinct answer strings."""
    return ["Alpha", "Beta", "Gamma", "Delta"]


# ---------------------------------------------------------------------------
# Core invariant: correct answer points to the same text after shuffling
# ---------------------------------------------------------------------------

def test_correct_answer_text_preserved_when_model_returns_index_zero():
    """The observed bug: the model always returns correct_index 0."""
    options = _options()
    correct_index = 0
    correct_text = options[correct_index]
    shuffled, new_index = _shuffle_options(options, correct_index)
    assert shuffled[new_index] == correct_text


def test_correct_answer_text_preserved_for_every_starting_index():
    options = _options()
    for correct_index in range(4):
        correct_text = options[correct_index]
        shuffled, new_index = _shuffle_options(options, correct_index)
        assert shuffled[new_index] == correct_text


def test_correct_answer_text_preserved_across_many_shuffles():
    """Run many shuffles to cover different random outcomes for each index."""
    options = _options()
    for correct_index in range(4):
        correct_text = options[correct_index]
        for _ in range(100):
            shuffled, new_index = _shuffle_options(options, correct_index)
            assert shuffled[new_index] == correct_text


# ---------------------------------------------------------------------------
# Shuffle is a proper permutation
# ---------------------------------------------------------------------------

def test_shuffle_preserves_the_same_set_of_options():
    options = _options()
    shuffled, _ = _shuffle_options(options, 0)
    assert sorted(shuffled) == sorted(options)
    assert len(shuffled) == 4


def test_new_correct_index_is_in_range():
    options = _options()
    for correct_index in range(4):
        _, new_index = _shuffle_options(options, correct_index)
        assert 0 <= new_index < 4


# ---------------------------------------------------------------------------
# No mutation of the caller's list
# ---------------------------------------------------------------------------

def test_shuffle_does_not_mutate_original_list():
    options = _options()
    original = list(options)
    _shuffle_options(options, 0)
    assert options == original


# ---------------------------------------------------------------------------
# Correct answer still identifiable even with duplicate option texts
# ---------------------------------------------------------------------------

def test_correct_answer_preserved_with_duplicate_option_texts():
    """If two options share text, tracking by original index keeps the right
    answer pointing at the correct text."""
    options = ["Same", "Same", "Other", "Another"]
    correct_index = 0
    correct_text = options[correct_index]
    shuffled, new_index = _shuffle_options(options, correct_index)
    assert shuffled[new_index] == correct_text
    assert 0 <= new_index < 4


# ---------------------------------------------------------------------------
# The shuffle actually moves things (over many runs, not every option stays)
# ---------------------------------------------------------------------------

def test_shuffle_actually_reorders_options_sometimes():
    """Over many shuffles the correct answer should land in different
    positions, confirming the shuffle is real and not a no-op."""
    options = _options()
    seen_positions = set()
    for _ in range(200):
        _, new_index = _shuffle_options(options, 0)
        seen_positions.add(new_index)
    # The correct answer (originally at index 0) should end up in more than
    # one position across 200 random shuffles.
    assert len(seen_positions) > 1
