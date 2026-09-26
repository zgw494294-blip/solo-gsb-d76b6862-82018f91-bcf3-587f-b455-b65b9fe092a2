"""六点盲文识读引擎：把 Unicode 六点盲文解读回 ASCII 文本。

与转写方向对应的识读规则：
- 沿用英语一级字母点位；盲文空格（U+2800）解读为词间空格，普通换行原样保留；
- ⠠（点 6）只把紧随的一个字母转为大写；
- ⠼（点 3456）使后续 a～i、j 点位分别读作 1～9、0，
  数字状态到词间格或普通换行结束；
- ⠤（点 36）仅作行尾断词标记：去掉该格及其后的换行并接续同一词，
  数字词续行须以 ⠼ 重新起始；
- 孤立标记、未定义点位、行内连字符与不合法的数字续行均按盲文行、列
  定位报错，且不返回任何部分解读文本。
"""

from __future__ import annotations

from .braille import (
    CAPITAL_CELL,
    DIGIT_LETTER,
    HYPHEN_CELL,
    LETTER_DOTS,
    NUMBER_CELL,
    SPACE_CELL,
    ValidationError,
    dots_to_unicode,
    line_col,
)

MAX_CELLS = 500

# Unicode 盲文字符 -> 小写字母
_LETTER_CELL = {dots_to_unicode(dots): ch for ch, dots in LETTER_DOTS.items()}
# 字母 -> 数字（a～i -> 1～9，j -> 0）
_LETTER_DIGIT = {letter: digit for digit, letter in DIGIT_LETTER.items()}


def _cell_dots(ch: str) -> frozenset[int]:
    """盲文字符 -> 点号集合（位 0～7 依次对应点 1～8）。"""
    bits = ord(ch) - 0x2800
    return frozenset(bit + 1 for bit in range(8) if bits >> bit & 1)


def decode(text: str) -> dict:
    """把 Unicode 六点盲文解读为 ASCII 字母、数字、空格与换行。

    输入非法时抛出 ValidationError（errors 含盲文行、列定位），
    不返回任何部分解读文本。
    """
    errors: list[dict] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    n = len(normalized)

    n_cells = sum(1 for ch in normalized if "⠀" <= ch <= "⣿")
    if normalized == "":
        errors.append({"code": "empty", "message": "请输入至少一格盲文。"})
    if n_cells > MAX_CELLS:
        errors.append({
            "code": "too_long",
            "message": f"输入共 {n_cells} 格盲文，超过 {MAX_CELLS} 格上限。",
        })

    out: list[str] = []
    number_mode = False
    pending_capital: int | None = None  # 等待紧随字母的大写标记位置

    def located(code: str, pos: int, detail: str, length: int = 1) -> None:
        line, col = line_col(normalized, pos)
        errors.append({
            "code": code, "pos": pos, "line": line, "col": col,
            "length": length,
            "message": f"第 {line} 行第 {col} 列{detail}",
        })

    def isolated_capital(pos: int) -> None:
        located(
            "isolated_capital", pos,
            f"的大写标记 {CAPITAL_CELL} 后没有紧随的字母：孤立标记。",
        )

    def enter_number(pos: int) -> None:
        """在 pos 处的数字标记格进入数字状态；下一格不是字母点位记孤立标记。"""
        nonlocal number_mode
        number_mode = True
        if pos + 1 >= n or normalized[pos + 1] not in _LETTER_CELL:
            located(
                "isolated_number", pos,
                f"的数字标记 {NUMBER_CELL} 后没有紧随的数字"
                f"（a～i、j 点位）：孤立标记。",
            )

    i = 0
    while i < n:
        ch = normalized[i]

        if ch == "\n":
            if pending_capital is not None:
                isolated_capital(pending_capital)
                pending_capital = None
            out.append("\n")
            number_mode = False
            i += 1
            continue

        if not "⠀" <= ch <= "⣿":
            # 非法字符：连续段合并为一条错误
            j = i + 1
            while (
                j < n
                and normalized[j] != "\n"
                and not "⠀" <= normalized[j] <= "⣿"
            ):
                j += 1
            sample = normalized[i:j]
            if len(sample) > 10:
                sample = sample[:10] + "…"
            located(
                "illegal_char", i,
                f"起含非法字符 {sample!r}：仅允许 Unicode 六点盲文、"
                f"盲文空格（U+2800）与换行。",
                length=j - i,
            )
            i = j
            continue

        if ch == SPACE_CELL:
            if pending_capital is not None:
                isolated_capital(pending_capital)
                pending_capital = None
            out.append(" ")
            number_mode = False
        elif ch in _LETTER_CELL:
            letter = _LETTER_CELL[ch]
            if number_mode:
                digit = _LETTER_DIGIT.get(letter)
                if digit is None:
                    located(
                        "number_letter", i,
                        f"的 {ch}（字母 {letter} 点位）出现在数字状态中："
                        f"数字状态只把 a～i、j 点位读作 1～9、0。",
                    )
                else:
                    out.append(digit)
            else:
                out.append(letter.upper() if pending_capital is not None else letter)
                pending_capital = None
        elif ch == CAPITAL_CELL:
            if number_mode:
                located(
                    "number_capital", i,
                    f"的大写标记 {CAPITAL_CELL} 出现在数字状态中："
                    f"数字状态到词间格或普通换行才结束。",
                )
            else:
                if pending_capital is not None:
                    isolated_capital(pending_capital)
                pending_capital = i
        elif ch == NUMBER_CELL:
            if pending_capital is not None:
                isolated_capital(pending_capital)
                pending_capital = None
            if number_mode:
                located(
                    "number_sign_repeat", i,
                    f"的数字标记 {NUMBER_CELL} 出现在数字状态中："
                    f"数字状态到词间格或普通换行才结束。",
                )
            else:
                enter_number(i)
        elif ch == HYPHEN_CELL:
            if pending_capital is not None:
                isolated_capital(pending_capital)
                pending_capital = None
            if i + 1 < n and normalized[i + 1] == "\n":
                # 行尾断词：去掉该格及其后的换行，接续同一词
                was_number = number_mode
                number_mode = False
                hyphen = i
                i += 2
                if i < n and normalized[i] == NUMBER_CELL:
                    # 续行以 ⠼ 重新起始（数字词续行必须如此）
                    enter_number(i)
                    i += 1
                elif was_number:
                    if i < n and normalized[i] != "\n":
                        located(
                            "bad_digit_continuation", i,
                            f"：数字词断行后的续行须以数字标记 {NUMBER_CELL} "
                            f"重新起始。",
                        )
                    else:
                        located(
                            "bad_digit_continuation", hyphen,
                            f"的断词标记 {HYPHEN_CELL}：数字词续行须以数字标记 "
                            f"{NUMBER_CELL} 重新起始。",
                        )
                elif i >= n or normalized[i] == "\n":
                    located(
                        "hyphen_no_continuation", hyphen,
                        f"的断词标记 {HYPHEN_CELL} 后缺少续行内容。",
                    )
                continue
            if i + 1 >= n:
                located(
                    "hyphen_no_continuation", i,
                    f"的断词标记 {HYPHEN_CELL} 位于输入末尾：缺少换行与续行内容。",
                )
            else:
                located(
                    "inline_hyphen", i,
                    f"的连字符 {HYPHEN_CELL} 位于行内："
                    f"{HYPHEN_CELL} 仅作行尾断词标记。",
                )
        else:
            dots = _cell_dots(ch)
            dot_text = "·".join(str(d) for d in sorted(dots))
            located(
                "undefined_cell", i,
                f"的盲文格 {ch}（点 {dot_text}）未定义：仅支持一级字母、"
                f"{CAPITAL_CELL}、{NUMBER_CELL}、{HYPHEN_CELL} 与盲文空格。",
            )
        i += 1

    if pending_capital is not None:
        isolated_capital(pending_capital)

    if errors:
        raise ValidationError(errors)

    result = "".join(out)
    return {
        "text": result,
        "cells": n_cells,
        "chars": len(result),
        "lines": result.count("\n") + 1,
    }
