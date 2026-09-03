from docket.markers import Doc, begin_marker, end_marker

TEXT = "# Title\n\n- [ ] a\n\n___\n\nsteps\n\n___\n\n- [ ] b\n"


def _without_block(lines: list[str], name: str) -> list[str]:
    out, inside = [], False
    for line in lines:
        if line.strip() == begin_marker(name):
            inside = True
            continue
        if line.strip() == end_marker(name):
            inside = False
            continue
        if not inside:
            out.append(line)
    return out


def test_markers_inserted_after_first_rule_only():
    doc = Doc.from_text(TEXT)
    assert doc.ensure_block_after_rule("scratch") is True
    lines = doc.lines
    rule = lines.index("___")
    assert lines[rule + 1] == ""
    assert lines[rule + 2] == begin_marker("scratch")
    assert lines[rule + 3] == end_marker("scratch")
    # Second rule untouched, and the first rule is the one that got the block.
    assert lines.count("___") == 2
    assert lines.count(begin_marker("scratch")) == 1


def test_insertion_preserves_every_original_line():
    doc = Doc.from_text(TEXT)
    doc.ensure_block_after_rule("scratch")
    doc.append_to_block("scratch", ["- 2026-09-03: hello"])
    stripped = _without_block(doc.lines, "scratch")
    # One blank line was added between the rule and the block.
    original = TEXT.split("\n")
    assert [line for line in stripped if line != ""] == [
        line for line in original if line != ""
    ]
    assert doc.block_lines("scratch") == ["- 2026-09-03: hello"]


def test_ensure_is_idempotent():
    doc = Doc.from_text(TEXT)
    doc.ensure_block_after_rule("scratch")
    once = doc.to_text()
    assert doc.ensure_block_after_rule("scratch") is False
    assert doc.to_text() == once


def test_replace_block_touches_only_inner_lines():
    text = f"before\n{begin_marker('focus')}\nold\n{end_marker('focus')}\nafter\n"
    doc = Doc.from_text(text)
    assert doc.replace_block("focus", ["new1", "new2"]) is True
    assert doc.to_text() == (
        f"before\n{begin_marker('focus')}\nnew1\nnew2\n{end_marker('focus')}\nafter\n"
    )


def test_replace_block_missing_markers_is_noop():
    doc = Doc.from_text(TEXT)
    assert doc.replace_block("focus", ["x"]) is False
    assert doc.to_text() == TEXT


def test_crlf_preserved():
    crlf = TEXT.replace("\n", "\r\n")
    doc = Doc.from_text(crlf)
    doc.ensure_block_after_rule("scratch")
    out = doc.to_text()
    assert "\r\n" in out and "\n\n" not in out.replace("\r\n", "")
    assert out.startswith("# Title\r\n")


def test_no_rule_appends_at_end():
    doc = Doc.from_text("# only\n\nbody\n")
    doc.ensure_block_after_rule("scratch")
    assert doc.lines[-3:] == [begin_marker("scratch"), end_marker("scratch"), ""]
