"""六点盲文识读引擎（独立于排版引擎）。

把用户粘贴的 Unicode 六点盲文（U+2800 区段，允许盲文空格与换行）
解读为 ASCII 字母、数字、空格与换行。

规则：
  - 沿用英语一级盲文字母点位；
  - ⠠（点 6）只把紧随的一个字母转为大写；
  - ⠼（点 3456）开启数字状态：后续 a～i、j 点位读作 1～9、0，
    数字状态到词间格或普通换行结束；
  - ⠤（点 36）仅作行尾断词标记：去掉该格及其后的换行并接续同一词；
    数字词续行须以 ⠼ 重新起始；
  - 普通换行保留。

任何错误都带行/列定位；只要有错就不输出任何解读文本。
"""

from __future__ import annotations

from .braille import (
    CAPITAL_CELL,
    HYPHEN_CELL,
    LETTER_DOTS,
    NUMBER_CELL,
    SPACE_CELL,
    ValidationError,
    _line_col,
)

MAX_CELLS = 500

# 点位（frozenset） -> 小写字母；沿用排版引擎的一级字母点位
_DOTS_TO_LETTER: dict[frozenset[int], str] = {
    dots: letter for letter, dots in LETTER_DOTS.items()
}

# 数字状态下 a～i、j -> 1～9、0
_LETTER_TO_DIGIT: dict[str, str] = {
    "a": "1", "b": "2", "c": "3", "d": "4", "e": "5",
    "f": "6", "g": "7", "h": "8", "i": "9", "j": "0",
}

# 单元格分类
T_LETTER = 0      # a～z 的点位
T_SPACE = 1       # U+2800 盲文空格
T_CAPITAL = 2     # ⠠
T_NUMBER = 3      # ⠼
T_HYPHEN = 4      # ⠤
T_UNDEFINED = 5   # 其它六点盲文格（标点、未定义点位、七八点格）


def _dot_set(ch: str) -> frozenset[int]:
    """U+2800 区段盲文格 -> 凸起的点号集合（含点 7/8 时为七八点格）。"""
    bits = ord(ch) - 0x2800
    return frozenset(
        d for d in (1, 2, 3, 4, 5, 6, 7, 8) if bits & (1 << (d - 1))
    )


def _classify(ch: str) -> tuple[int, str | None]:
    """返回 (类别, 对应小写字母或 None)。"""
    if ch == SPACE_CELL:
        return T_SPACE, None
    if ch == CAPITAL_CELL:
        return T_CAPITAL, None
    if ch == NUMBER_CELL:
        return T_NUMBER, None
    if ch == HYPHEN_CELL:
        return T_HYPHEN, None
    dots = _dot_set(ch)
    if dots & {7, 8}:
        return T_UNDEFINED, None  # 七点/八点盲文格，未定义
    letter = _DOTS_TO_LETTER.get(dots)
    if letter is not None:
        return T_LETTER, letter
    return T_UNDEFINED, None


def _located(code: str, text: str, pos: int, message: str, length: int = 1) -> dict:
    line, col = _line_col(text, pos)
    return {
        "code": code,
        "pos": pos,
        "line": line,
        "col": col,
        "length": length,
        "message": message,
    }


def decode(text: str) -> dict:
    """识读 Unicode 盲文输入，返回 {"text", "stats", ...}。

    有任何非法输入时抛出 ValidationError（结构化行/列错误），
    此时不提供任何解读文本。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    errors: list[dict] = []

    # 预处理：逐行扫描，非盲文字符合并为连续区段报错；
    # 同时构造扁平 token 流：("cell", 偏移, 字符, 类别, 字母) / ("nl", 偏移)。
    flat: list[tuple] = []
    offset = 0
    has_letter = False
    for li, line in enumerate(lines):
        i = 0
        while i < len(line):
            ch = line[i]
            if 0x2800 <= ord(ch) <= 0x28FF:
                kind, letter = _classify(ch)
                flat.append(("cell", offset + i, ch, kind, letter))
                if kind == T_LETTER:
                    has_letter = True
                elif kind == T_UNDEFINED:
                    errors.append(_located(
                        "undefined_cell", normalized, offset + i,
                        f"第 {li + 1} 行第 {i + 1} 列的盲文格 {ch}"
                        f"（U+{ord(ch):04X}）不是英语一级字母或标记点位。",
                    ))
                i += 1
            else:
                start = i
                run_chars = []
                while i < len(line) and not (0x2800 <= ord(line[i]) <= 0x28FF):
                    run_chars.append(line[i])
                    i += 1
                run = "".join(run_chars)
                sample = run if len(run) <= 10 else run[:10] + "…"
                errors.append(_located(
                    "illegal_char", normalized, offset + start,
                    f"第 {li + 1} 行第 {start + 1} 列起含非盲文字符 {sample!r}："
                    f"仅允许 Unicode 六点盲文格、盲文空格（{SPACE_CELL}）与换行。",
                    length=len(run),
                ))
        if li + 1 < len(lines):
            flat.append(("nl", offset + len(line)))
        offset += len(line) + 1  # +1 为行尾换行

    if len(normalized) > MAX_CELLS:
        errors.append(_located(
            "too_long", normalized, 0,
            f"输入长度为 {len(normalized)} 格，超过 {MAX_CELLS} 格上限。",
        ))
    if not normalized:
        errors.append({
            "code": "empty",
            "message": "请输入至少一个盲文字母或数字格。",
        })
    elif not has_letter:
        errors.append({
            "code": "no_letter",
            "message": "输入中至少需要包含一个盲文字母（或数字）格。",
        })

    # ------------------------------------------------------------------
    # 扁平流扫描
    # ------------------------------------------------------------------
    n = len(flat)
    out: list[str] = []
    number_mode = False    # 当前处于数字状态
    pending_cap = False    # 上一个 ⠠ 等待紧随字母
    word_kind: str | None = None  # 当前词： "alpha" | "digit" | None（词间/行首）
    number_restart = False  # 下一个 ⠼ 是数字词续行的重新起始标记

    def cell_at(idx: int):
        """若 flat[idx] 为盲文格，返回 (偏移, 字符, 类别, 字母)，否则 None。"""
        if 0 <= idx < n and flat[idx][0] == "cell":
            return flat[idx][1:]
        return None

    def reset_word() -> None:
        nonlocal number_mode, pending_cap, word_kind, number_restart
        number_mode = False
        pending_cap = False
        word_kind = None
        number_restart = False

    p = 0
    while p < n:
        tok = flat[p]
        if tok[0] == "nl":
            out.append("\n")  # 普通换行保留
            reset_word()
            p += 1
            continue

        _, pos, ch, kind, letter = tok

        if kind == T_SPACE:
            out.append(" ")
            reset_word()
            p += 1
            continue

        if kind == T_UNDEFINED:
            # 点位错误已在预处理阶段记录；该格不产生解读，也不结束词，
            # 但会打断"紧随字母"的大写标记。
            pending_cap = False
            p += 1
            continue

        if kind == T_CAPITAL:
            nxt = cell_at(p + 1)
            if (
                nxt is not None and nxt[2] == T_LETTER
                and not number_mode and word_kind != "digit"
            ):
                pending_cap = True
            else:
                if number_mode or word_kind == "digit":
                    why = "数字状态中不使用大写标记"
                else:
                    why = "其后没有紧随的盲文字母格"
                errors.append(_located(
                    "isolated_mark", normalized, pos,
                    f"大写标记 {CAPITAL_CELL}（点 6）是孤立标记：{why}。",
                ))
                pending_cap = False
            p += 1
            continue

        if kind == T_NUMBER:
            nxt = cell_at(p + 1)
            if (word_kind is None or number_restart) and nxt is not None \
                    and nxt[2] == T_LETTER:
                # 合法数字词起始（紧随字母是否 a～j 由字母分支判定）
                word_kind = "digit"
                number_mode = True
                number_restart = False
            else:
                if word_kind is not None and not number_restart:
                    why = "数字标记只能出现在词首（或数字词续行行首）"
                else:
                    why = "数字标记后须紧随 a～j 的字母点位"
                errors.append(_located(
                    "isolated_mark", normalized, pos,
                    f"数字标记 {NUMBER_CELL}（点 3456）是孤立标记：{why}。",
                ))
                number_mode = False
                number_restart = False
            p += 1
            continue

        if kind == T_HYPHEN:
            nxt = flat[p + 1] if p + 1 < n else None
            if nxt is None or nxt[0] != "nl":
                # 行内（后面同行还有盲文格）连字符
                errors.append(_located(
                    "inline_hyphen", normalized, pos,
                    f"断词标记 {HYPHEN_CELL}（点 36）只能位于行尾，"
                    f"行内不允许连字符。",
                ))
                p += 1
                continue
            # 行尾断词：下一行行首须接续同一词
            cont = cell_at(p + 2)  # 换行之后的首格（可能为 None=空行/文件结束）
            if word_kind == "digit":
                if cont is not None and cont[2] == T_NUMBER:
                    # 合法数字续行：去掉连字符与换行，⠼ 在续行行首重新起始
                    number_restart = True
                    pending_cap = False
                    p += 2  # 跳过连字符格与换行，落到 ⠼
                    continue
                errors.append(_located(
                    "bad_number_continuation", normalized,
                    cont[0] if cont is not None else pos,
                    "数字词以行尾断词标记续行时，续行须以数字标记 "
                    f"{NUMBER_CELL}（点 3456）重新起始。",
                ))
            else:
                if cont is not None and cont[2] in (T_LETTER, T_CAPITAL) \
                        and word_kind is not None:
                    # 合法字母词续行：去掉连字符与换行，词类型保持字母词
                    word_kind = "alpha"
                    number_mode = False
                    p += 2  # 跳过连字符格与换行
                    continue
                if word_kind is None:
                    errors.append(_located(
                        "isolated_mark", normalized, pos,
                        f"断词标记 {HYPHEN_CELL}（点 36）前没有可接续的词。",
                    ))
                elif cont is not None and cont[2] == T_NUMBER:
                    errors.append(_located(
                        "isolated_mark", normalized, cont[0],
                        f"字母词续行行首不能以数字标记 {NUMBER_CELL}（点 3456）"
                        f"起始：续行须直接接续字母。",
                    ))
                else:
                    errors.append(_located(
                        "isolated_mark", normalized, pos,
                        f"断词标记 {HYPHEN_CELL}（点 36）之后是空行或输入结束，"
                        f"没有可接续的盲文字母格。",
                    ))
            # 接续不合法：该换行按普通换行保留并重置词状态
            p += 1  # 落到换行 token，下轮正常处理
            continue

        # kind == T_LETTER
        if number_mode:
            digit = _LETTER_TO_DIGIT.get(letter)
            if digit is None:
                errors.append(_located(
                    "undefined_cell", normalized, pos,
                    f"盲文格 {ch} 位于数字状态中：数字状态只允许 a～j 的点位"
                    f"（读作 1～9、0）。",
                ))
                p += 1
                continue
            word_kind = "digit"
            out.append(digit)
        else:
            word_kind = "alpha"
            out.append(letter.upper() if pending_cap else letter)
        pending_cap = False
        p += 1

    if errors:
        raise ValidationError(errors)

    decoded = "".join(out)
    return {
        "text": decoded,
        "stats": {
            "input_cells": len(normalized),
            "output_chars": len(decoded),
            "lines": len(lines),
        },
    }
