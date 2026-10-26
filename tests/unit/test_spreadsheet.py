from rag_pre_ingest.pipeline.spreadsheet import trim_empty_tails


def test_trim_only_styled_empty_tails_preserving_inner_and_leading_blanks() -> None:
    source = [
        ["", "A", "", "B", "", ""],
        ["", "", "", "", "", ""],
        ["", "C", "", "D", "", ""],
        [""] * 6,
    ]
    assert trim_empty_tails(source, []) == [["", "A", "", "B"], [""] * 4, ["", "C", "", "D"]]
    assert len(source) == 4 and len(source[0]) == 6


def test_populated_merge_extents_are_kept_but_empty_styled_merges_are_not() -> None:
    assert trim_empty_tails([["Title", ""], ["", ""]], [(0, 0, 1, 4), (4, 4, 6, 8)]) == [
        ["Title", "", "", "", ""],
        ["", "", "", "", ""],
    ]


def test_empty_sheets_and_zero_values() -> None:
    assert trim_empty_tails([["", ""]], [(0, 0, 2, 3)]) == []
    assert trim_empty_tails([["0", "False", ""]], []) == [["0", "False"]]
