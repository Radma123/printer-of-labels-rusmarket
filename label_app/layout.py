# -*- coding: utf-8 -*-
"""
Геометрия этикетки — прямая копия координат из скачанного макета Claude
Design (`Label 100x72.dc.html`, раздел `<section class="page" id="label">`).

Макет — HTML/CSS-документ 72mm x 100mm (портретная ориентация: так
нарисован на реальных этикетках CNH, см. фото). Значения ниже — это те
же числа, что в inline-style макета, просто вынесенные в один файл,
чтобы их не пришлось держать синхронно в трёх местах (Python-рендер,
браузерное превью, TSPL).

Физический принтер TSC TE200 откалиброван на рулон 100mm (поперёк
головки) x 72mm (вдоль подачи), Media Sensor = GAP, зазор 3mm.
Макет же нарисован 72 x 100 (портрет). Числа совпадают, только
переставлены местами, поэтому готовое изображение перед отправкой на
печать поворачивается на 90° (см. render.build_tspl) — так оно точно
ложится на откалиброванный рулон. Если этикетка ляжет текстом не в ту
сторону, в приложении есть чекбокс «повернуть на 180°».

CSS-единицы макета — mm и px вперемешку. Конвертация та же, что
использует сам конструктор (`doc-page.js`): 1mm = 96/25.4 px (обычные
CSS-пиксели, 96 dpi), см. `PX_PER` в `doc-page.js`.
"""

PX_PER_MM = 96 / 25.4                     # CSS px -> mm, как в doc-page.js

LABEL_W_MM = 72.0                         # ширина макета (портрет)
LABEL_H_MM = 100.0                        # высота макета
PAD_MM = 4.0                              # padding:4mm у .page
GAP_MM = 3.0                              # gap:3mm у flex-колонки .page

CONTENT_W_MM = LABEL_W_MM - 2 * PAD_MM    # 64mm — рабочая ширина контента

# Физический рулон принтера: 100mm поперёк головки,
# 72mm вдоль подачи. Ровно те же два числа, что и у макета, переставленные.
PRINT_W_MM = 100.0
PRINT_H_MM = 72.0
PRINT_GAP_MM = 3.0
DPI = 203
SPEED = 4
DENSITY = 8

# ------------------------------------------------------------ шапка (логотипы)
# Каждый логотип в макете — контейнер с overflow:hidden и картинкой,
# отмасштабированной и сдвинутой абсолютным позиционированием (typical
# "cover + crop" приём). crop — окно (offset, size) в мм поверх
# картинки, отображённой в размере disp (тоже в мм).
LOGOS = {
    "cnh": {
        "file": "logo1.png",
        "box": {"w": 26.0, "h": 13.3},                # видимый контейнер
        "disp": {"w": 32.5, "h": 32.5},                # картинка отображена в этом размере
        "off": {"x": 3.49, "y": 9.51},                 # смещение картинки (кроп)
    },
    "eye": {
        "file": "logo2.png",
        "box": {"w": 7.0, "h": 4.9},
        "disp": {"w": 8.87, "h": 5.02},
        "off": {"x": 0.92, "y": 0.11},
        "margin_top": 4.0,                             # margin-top:4mm у этого блока в шапке
    },
    "fsc": {
        "file": "logo3.png",
        "box": {"w": 15.0, "h": 17.7},
        "disp": {"w": 40.2, "h": 28.1},
        "off": {"x": 12.6, "y": 2.95},
    },
}
HEADER_GAP_MM = 2.0                       # gap:2mm; при space-between реально больше (см. ниже)
HEADER_ORDER = ("cnh", "eye", "fsc")

# ------------------------------------------------------------------- строки
DESC = {"size": 3.8, "weight": "bold", "letter_spacing": 0.1,
        "line_height": 1.2, "gap": 0.8, "margin_top": 1.0, "max_lines": 6}

MADE_IN = {"size": 2.9, "letter_spacing": 0.05, "line_height": 1.15}

BARCODE_ROW = {"height_px": 73, "gap_px": 0.32 * PX_PER_MM, "bar_height_px": 58}

PN = {"size": 6.5, "weight": "bold", "letter_spacing": 1.4, "line_height": 1.0,
      "font": "monospace"}

PCS = {"size": 3.0, "letter_spacing": 0.2, "gap": 3.0, "line_height": 1.15}

DEFAULTS = {
    "made_in": "Türkiye",
    "pcs": "1",
    "rotate180": False,
}

FONT_MONO_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Menlo.ttc",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]


def mm_to_dots(value_mm: float, dpi: int = DPI) -> int:
    return int(round(value_mm * dpi / 25.4))


def as_dict() -> dict:
    """Геометрия для фронтенда — тот же набор чисел, что использует
    render.py, чтобы DOM-превью (реальный flexbox в браузере) и
    серверный PNG/TSPL совпадали."""
    return {
        "label": {"w": LABEL_W_MM, "h": LABEL_H_MM},
        "pad": PAD_MM, "gap": GAP_MM, "content_w": CONTENT_W_MM,
        "px_per_mm": PX_PER_MM,
        "logos": LOGOS, "header_order": list(HEADER_ORDER),
        "header_gap": HEADER_GAP_MM,
        "desc": DESC, "made_in": MADE_IN, "barcode_row": BARCODE_ROW,
        "pn": PN, "pcs": PCS,
        "print": {"w": PRINT_W_MM, "h": PRINT_H_MM},
    }
