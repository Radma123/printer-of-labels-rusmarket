# -*- coding: utf-8 -*-
"""
Code 128 — тот же символ, что стоит на оригинальных этикетках CNH.

Возвращается не картинка, а список ширин полос в модулях: первая полоса
чёрная, дальше чередование. Одну и ту же раскладку рисуют и превью в
браузере (SVG), и превью печати (PNG) — расхождения между ними быть не может.
Сам принтер печатает штрихкод своей командой TSPL BARCODE.
"""

# 107 шаблонов: по 6 цифр — ширины полос/пробелов в модулях.
_PATTERNS = (
    "212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 "
    "221312 231212 112232 122132 122231 113222 123122 123221 223211 221132 "
    "221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 "
    "212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 "
    "231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 "
    "231131 213113 213311 213131 311123 311321 331121 312113 312311 332111 "
    "314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 "
    "112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 "
    "111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 "
    "214121 412121 111143 111341 131141 114113 114311 411113 411311 113141 "
    "114131 311141 411131 211412 211214 211232 2331112"
).split()

START_A, START_B, START_C, STOP = 103, 104, 105, 106
CODE_A, CODE_B, CODE_C = 101, 100, 99


def _digit_run(text: str, i: int) -> int:
    n = 0
    while i + n < len(text) and text[i + n].isdigit():
        n += 1
    return n


def encode(text: str):
    """Строка -> список значений Code 128 (без стартового и контрольного)."""
    values, mode, i = [], None, 0
    while i < len(text):
        run = _digit_run(text, i)
        # Режим C вдвое плотнее, но пары цифр должны быть полными.
        use_c = run >= 4 if (i > 0 or run < len(text)) else run >= 2
        if use_c and run % 2:
            run -= 1
        if use_c and run >= 2:
            if mode != "C":
                values.append(START_C if mode is None else CODE_C)
                mode = "C"
            for k in range(0, run, 2):
                values.append(int(text[i + k:i + k + 2]))
            i += run
            continue
        if mode != "B":
            values.append(START_B if mode is None else CODE_B)
            mode = "B"
        ch = text[i]
        code = ord(ch)
        if code < 32 or code > 126:
            raise ValueError(f"символ {ch!r} нельзя закодировать в Code 128B")
        values.append(code - 32)
        i += 1
    if not values:
        values = [START_B]
    return values


def pattern(text: str):
    """
    Строка -> {'widths': [...], 'modules': N}.
    widths[0] — чёрная полоса, дальше цвета чередуются.
    """
    values = encode(text)
    start = values[0]
    checksum = start
    for pos, val in enumerate(values[1:], start=1):
        checksum += pos * val
    values.append(checksum % 103)
    values.append(STOP)

    widths = []
    for val in values:
        widths.extend(int(c) for c in _PATTERNS[val])
    return {"widths": widths, "modules": sum(widths)}


if __name__ == "__main__":
    import sys
    for arg in (sys.argv[1:] or ["84565867", "C5NNF892A"]):
        p = pattern(arg)
        print(arg, "->", p["modules"], "модулей,", len(p["widths"]), "полос")
