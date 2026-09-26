"""六点盲文识读引擎测试。"""

import pytest

from app.braille import (
    CAPITAL_CELL,
    HYPHEN_CELL,
    LETTER_DOTS,
    NUMBER_CELL,
    SPACE_CELL,
    dots_to_unicode,
)
from app.reader import MAX_CELLS, ValidationError, decode


def dec(braille: str) -> str:
    return decode(braille)["text"]


def err_codes(braille: str):
    with pytest.raises(ValidationError) as ei:
        decode(braille)
    return [(e["code"], e.get("line"), e.get("col")) for e in ei.value.errors]


def first_error(braille: str) -> dict:
    with pytest.raises(ValidationError) as ei:
        decode(braille)
    return ei.value.errors[0]


def br_word(word: str) -> str:
    """ASCII 字母/数字词 -> 盲文（仅用于测试构造输入）。"""
    out = []
    if word and word[0].isdigit():
        out.append(NUMBER_CELL)
    for ch in word:
        if ch.isdigit():
            letter = "abcdefghij"[9 if ch == "0" else int(ch) - 1]
            out.append(dots_to_unicode(LETTER_DOTS[letter]))
        elif ch.isupper():
            out.append(CAPITAL_CELL + dots_to_unicode(LETTER_DOTS[ch.lower()]))
        else:
            out.append(dots_to_unicode(LETTER_DOTS[ch]))
    return "".join(out)


# ---------------------------------------------------------------------------
# 正常解读
# ---------------------------------------------------------------------------

def test_lowercase_letters_grade1_dots():
    alphabet = "".join(dots_to_unicode(d) for d in LETTER_DOTS.values())
    assert dec(alphabet) == "abcdefghijklmnopqrstuvwxyz"


def test_capital_marks_only_next_one_letter():
    assert dec(CAPITAL_CELL + dots_to_unicode(LETTER_DOTS["a"]) + "⠃") == "Ab"
    assert dec(br_word("Hello")) == "Hello"
    # 连续两个大写：各自需要 ⠠；单个 ⠠ 只大写一个字母
    assert dec(br_word("Ab")) == "Ab"


def test_number_sign_aj_to_digits():
    assert dec(NUMBER_CELL + "⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚") == "1234567890"
    assert dec(br_word("2026")) == "2026"


def test_number_mode_ends_at_braille_space():
    assert dec("⠼⠁" + SPACE_CELL + "⠃") == "1 b"
    assert dec(br_word("1") + SPACE_CELL + br_word("2")) == "1 2"


def test_number_mode_ends_at_plain_newline():
    assert dec(NUMBER_CELL + "⠁\n⠅") == "1\nk"
    # 普通换行保留；新行默认字母状态
    assert dec("⠁\n⠃") == "a\nb"


def test_two_braille_spaces_become_two_ascii_spaces():
    assert dec("⠁" + SPACE_CELL * 2 + "⠃") == "a  b"


def test_trailing_and_blank_newlines_preserved():
    assert dec("⠁\n") == "a\n"
    assert dec("⠁\n\n⠃") == "a\n\nb"


def test_crlf_normalized():
    assert dec("⠁\r\n⠃") == "a\nb"


def test_words_with_space_and_capital():
    src = br_word("Hello") + SPACE_CELL + br_word("Braille")
    assert dec(src) == "Hello Braille"


def test_stats():
    r = decode("⠁⠃\n⠉")
    assert r["stats"] == {"input_cells": 4, "output_chars": 4, "lines": 2}


# ---------------------------------------------------------------------------
# 行尾断词
# ---------------------------------------------------------------------------

def test_hyphen_newline_joins_alpha_word():
    assert dec("⠠⠺⠕⠗⠇⠙" + HYPHEN_CELL + "\n⠋⠁⠍⠕⠥⠎") == "Worldfamous"
    # 不输出该换行
    assert "\n" not in dec("⠁⠃" + HYPHEN_CELL + "\n⠉⠙")


def test_hyphen_newline_continuation_keeps_capital_marker():
    assert dec("⠁" + HYPHEN_CELL + "\n" + CAPITAL_CELL + "⠃") == "aB"


def test_digit_word_continuation_must_restart_number_sign():
    assert dec(br_word("10") + HYPHEN_CELL + "\n" + br_word("26")) == "1026"
    assert dec("⠼⠁" + HYPHEN_CELL + "\n⠼⠃") == "12"


def test_multi_segment_digit_continuation():
    assert dec("⠼⠁" + HYPHEN_CELL + "\n⠼⠃" + HYPHEN_CELL + "\n⠼⠉") == "123"


def test_alpha_word_continues_through_blank_space_then_restart_invalid():
    # 续行行首带盲文空格不算接续
    err = first_error("⠁" + HYPHEN_CELL + "\n" + SPACE_CELL + "⠃")
    assert err["code"] == "isolated_mark"


# ---------------------------------------------------------------------------
# 错误：定位且不输出
# ---------------------------------------------------------------------------

def test_empty_and_space_only():
    assert err_codes("")[0][0] == "empty"
    assert err_codes(SPACE_CELL)[0][0] == "no_letter"
    assert err_codes(SPACE_CELL * 3)[0][0] == "no_letter"


def test_too_long():
    err = first_error("⠁" * (MAX_CELLS + 1))
    assert err["code"] == "too_long"
    decode("⠁" * MAX_CELLS)  # 边界可用


def test_non_braille_characters_are_located():
    err = first_error("ab")
    assert err["code"] == "illegal_char"
    assert (err["line"], err["col"]) == (1, 1)

    err = first_error("⠁\n\t⠃")
    assert err["code"] == "illegal_char"
    assert (err["line"], err["col"]) == (2, 1)

    err = first_error("⠁中⠃")
    assert err["code"] == "illegal_char"
    assert (err["line"], err["col"]) == (1, 2)
    assert err["length"] == 1

    # 连续非盲文字符合并为一处
    with pytest.raises(ValidationError) as ei:
        decode("⠁abc⠃")
    illegal = [e for e in ei.value.errors if e["code"] == "illegal_char"]
    assert len(illegal) == 1
    assert illegal[0]["length"] == 3


def test_undefined_six_dot_cells():
    # 常见标点格（逗号 2、问号 236 等）均未定义
    for ch in ["⠂", "⠦", "⠖", "⠣"]:
        err = first_error(ch + "⠁")
        assert err["code"] == "undefined_cell"
        assert (err["line"], err["col"]) == (1, 1)


def test_seven_eight_dot_cells_undefined():
    err = first_error("⣿⠁")  # U+28FF
    assert err["code"] == "undefined_cell"
    assert (err["line"], err["col"]) == (1, 1)


def test_isolated_capital_mark():
    # 行尾、词间格后不紧随字母、数字状态中
    codes = [c for c, _l, _c2 in err_codes(CAPITAL_CELL)]
    assert "isolated_mark" in codes
    assert first_error("⠁" + CAPITAL_CELL)["code"] == "isolated_mark"
    assert first_error(
        "⠁" + SPACE_CELL + CAPITAL_CELL + SPACE_CELL + "⠃"
    )["code"] == "isolated_mark"
    # 词间格后的新词词首大写是合法的
    assert dec("⠁" + SPACE_CELL + CAPITAL_CELL + "⠃") == "a B"
    assert first_error("⠼⠁" + CAPITAL_CELL)["code"] == "isolated_mark"
    assert first_error(CAPITAL_CELL + CAPITAL_CELL + "⠁")["code"] == "isolated_mark"


def test_isolated_number_sign():
    codes = [c for c, _l, _c2 in err_codes(NUMBER_CELL)]
    assert "isolated_mark" in codes
    # 数字标记后非字母（空格）
    assert first_error(NUMBER_CELL + SPACE_CELL + "⠁")["code"] == "isolated_mark"
    # 词中再次出现数字标记
    assert first_error("⠼⠁" + NUMBER_CELL + "⠃")["code"] == "isolated_mark"
    # 字母词中间出现数字标记
    assert first_error("⠁" + NUMBER_CELL + "⠃")["code"] == "isolated_mark"
    # 大写标记后紧跟数字标记
    assert first_error(CAPITAL_CELL + NUMBER_CELL + "⠁")["code"] == "isolated_mark"


def test_k_to_z_in_number_mode_is_undefined():
    err = first_error(NUMBER_CELL + "⠅")
    assert err["code"] == "undefined_cell"
    assert (err["line"], err["col"]) == (1, 2)
    # w（点 2456）同样超出 a～j
    err = first_error(NUMBER_CELL + "⠺")
    assert err["code"] == "undefined_cell"


def test_inline_hyphen_is_located():
    err = first_error("⠁" + HYPHEN_CELL + "⠃")
    assert err["code"] == "inline_hyphen"
    assert (err["line"], err["col"]) == (1, 2)
    # 空格之后、行尾出现断词标记：前面没有词，属孤立标记
    assert first_error("⠁" + SPACE_CELL + HYPHEN_CELL + "\n⠃")["code"] == "isolated_mark"


def test_hyphen_at_end_of_last_line_is_isolated():
    err = first_error("⠁" + HYPHEN_CELL + "\n")
    assert err["code"] == "isolated_mark"
    assert (err["line"], err["col"]) == (1, 2)


def test_hyphen_followed_by_blank_line():
    err = first_error("⠁" + HYPHEN_CELL + "\n\n⠃")
    assert err["code"] == "isolated_mark"


def test_bad_number_continuation_missing_number_sign():
    err = first_error("⠼⠁" + HYPHEN_CELL + "\n⠃")
    assert err["code"] == "bad_number_continuation"
    assert (err["line"], err["col"]) == (2, 1)


def test_alpha_continuation_with_number_sign_is_isolated():
    err = first_error("⠁" + HYPHEN_CELL + "\n" + NUMBER_CELL + "⠃")
    assert err["code"] == "isolated_mark"
    assert (err["line"], err["col"]) == (2, 1)


def test_errors_never_produce_partial_text():
    # 任何错误都抛出 ValidationError，不返回部分解读文本
    for bad in [
        "⠁\t⠃",
        "⠂",
        "⠼⠅",
        "⠁⠤⠼",
    ]:
        with pytest.raises(ValidationError):
            decode(bad)


def test_multiple_errors_all_collected_with_positions():
    with pytest.raises(ValidationError) as ei:
        decode("⠂" + SPACE_CELL + "⠦\n⠁" + HYPHEN_CELL + "⠃")
    codes = [e["code"] for e in ei.value.errors]
    assert "undefined_cell" in codes
    assert "inline_hyphen" in codes
    for e in ei.value.errors:
        assert e.get("line") and e.get("col")


# ---------------------------------------------------------------------------
# 与排版引擎的往返对照
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word", [
    "a", "z", "Hello", "Braille", "World",
    "quick", "brown", "fox",
])
def test_roundtrip_alpha_words(word):
    assert dec(br_word(word)) == word


@pytest.mark.parametrize("number", ["0", "1", "2026", "007", "1234567890"])
def test_roundtrip_digit_words(number):
    assert dec(br_word(number)) == number


def test_roundtrip_multiline_typeset_output():
    from app.braille import typeset
    source = "Hello Braille\nThe quick brown fox\n2026 007"
    laid = typeset(source, 40)["braille_text"]
    assert dec(laid) == source
