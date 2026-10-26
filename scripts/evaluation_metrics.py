"""Pure evaluation helpers; no extractor imports or runtime dependencies.

Text metrics score the complete transcription, so additions and omissions both
count. Structural metrics require stable, human-labeled source identifiers.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass


def canonical_text(text: str) -> str:
    """Ignore layout whitespace and canonical Unicode encoding, preserving content."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def edit_distance[T](expected: Sequence[T], actual: Sequence[T]) -> int:
    """Levenshtein distance using linear auxiliary space."""
    if len(expected) < len(actual):
        return edit_distance(actual, expected)
    previous = list(range(len(actual) + 1))
    for row, left in enumerate(expected, start=1):
        current = [row]
        for column, right in enumerate(actual, start=1):
            current.append(
                min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (left != right))
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class TextMetrics:
    character_errors: int
    expected_characters: int
    word_errors: int
    expected_words: int
    exact: bool

    @property
    def cer(self) -> float:
        """Empty references use denominator one; insertions remain errors."""
        return self.character_errors / max(1, self.expected_characters)

    @property
    def wer(self) -> float:
        return self.word_errors / max(1, self.expected_words)


def text_metrics(expected: str, actual: str) -> TextMetrics:
    """CER/WER after NFC and whitespace normalization; rates may exceed one."""
    reference, candidate = canonical_text(expected), canonical_text(actual)
    reference_words, candidate_words = reference.split(), candidate.split()
    return TextMetrics(
        edit_distance(reference, candidate),
        len(reference),
        edit_distance(reference_words, candidate_words),
        len(reference_words),
        reference == candidate,
    )


@dataclass(frozen=True)
class ExactMetrics:
    matched: int
    expected: int
    actual: int
    exact: bool

    @property
    def precision(self) -> float:
        return self.matched / self.actual if self.actual else float(self.expected == 0)

    @property
    def recall(self) -> float:
        return self.matched / self.expected if self.expected else float(self.actual == 0)


def order_metrics(expected: Sequence[str], actual: Sequence[str]) -> ExactMetrics:
    """Score exact source-ID positions; duplicate IDs are invalid ground truth/output."""
    if len(set(expected)) != len(expected) or len(set(actual)) != len(actual):
        raise ValueError("Reading-order identifiers must be unique")
    matches = sum(left == right for left, right in zip(expected, actual, strict=False))
    return ExactMetrics(matches, len(expected), len(actual), list(expected) == list(actual))


def _partition(groups: Sequence[Sequence[str]]) -> set[frozenset[str]]:
    flattened = [member for group in groups for member in group]
    if any(not group for group in groups) or len(set(flattened)) != len(flattened):
        raise ValueError("Groups must be nonempty and each source identifier must occur once")
    return {frozenset(group) for group in groups}


def grouping_metrics(
    expected: Sequence[Sequence[str]],
    actual: Sequence[Sequence[str]],
) -> ExactMetrics:
    """Score whole memberships, ignoring group and member presentation order."""
    reference, candidate = _partition(expected), _partition(actual)
    return ExactMetrics(
        len(reference & candidate), len(reference), len(candidate), reference == candidate
    )


def cell_metrics(
    expected: Mapping[Hashable, str],
    actual: Mapping[Hashable, str],
) -> ExactMetrics:
    """Score text at labeled (table, row, column) addresses, including explicit blanks.

    Addresses may include row/column spans to score merged cells. Missing blank
    cells differ from present blank cells. Extra addresses reduce precision.
    """
    matches = sum(
        address in actual and canonical_text(value) == canonical_text(actual[address])
        for address, value in expected.items()
    )
    return ExactMetrics(
        matches, len(expected), len(actual), matches == len(expected) == len(actual)
    )
