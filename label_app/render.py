# -*- coding: utf-8 -*-
"""
Отрисовка этикетки в PNG (точное превью печати) и сборка задания TSPL
для TSC TE200 — реализация макета Claude Design `Label 100x72.dc.html`
(геометрия и стили — в layout.py, там же объяснение про поворот на 90°
перед печатью).

Текст и логотипы уходят на принтер картинкой (команда BITMAP), штрихкод
рисуем сами тем же Code 128, что и на настоящих этикетках CNH (barcode.py),
чтобы гарантированно совпадал с превью в браузере пиксель в пиксель.
"""

import glob
import os

from PIL import Image, ImageDraw, ImageFont

import barcode as bc
from layout import (BARCODE_ROW, CONTENT_W_MM, DENSITY, DESC, DPI, GAP_MM,
                    HEADER_GAP_MM, HEADER_ORDER, LABEL_H_MM, LABEL_W_MM,
                    LOGOS, MADE_IN, PAD_MM, PCS, PN, PRINT_GAP_MM,
                    PRINT_H_MM, PRINT_W_MM, PX_PER_MM, SPEED,
                    TWEAK_SCALE_MAX, TWEAK_SCALE_MIN,
                    FONT_MONO_CANDIDATES, mm_to_dots)

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR = os.path.join(HERE, "static", "logos")

FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/System/Library/Fonts/Helvetica.ttc",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
_fonts = None
_mono = None


def _font_files():
    global _fonts
    if _fonts:
        return _fonts
    env = os.environ.get("LABEL_FONT")
    if env and os.path.exists(env):
        _fonts = (env, os.environ.get("LABEL_FONT_BOLD", env))
        return _fonts
    for reg, bold in FONT_CANDIDATES:
        if os.path.exists(reg):
            _fonts = (reg, bold if os.path.exists(bold) else reg)
            return _fonts
    found = sorted(glob.glob("/System/Library/Fonts/Supplemental/*.ttf"))
    if not found:
        raise RuntimeError("не найден ни один TTF-шрифт, задайте LABEL_FONT")
    _fonts = (found[0], found[0])
    return _fonts


def _mono_file():
    global _mono
    if _mono:
        return _mono
    env = os.environ.get("LABEL_FONT_MONO")
    candidates = ([env] if env else []) + FONT_MONO_CANDIDATES
    for path in candidates:
        if path and os.path.exists(path):
            _mono = path
            return _mono
    _mono = _font_files()[1]                             # жирный обычный — запасной вариант
    return _mono


class Canvas:
    """Холст этикетки в миллиметрах поверх монохромной картинки 1-bit."""

    def __init__(self, scale: int = 1):
        self.scale = scale
        self.px_per_mm = DPI / 25.4 * scale
        self.w = int(round(LABEL_W_MM * self.px_per_mm))
        self.h = int(round(LABEL_H_MM * self.px_per_mm))
        self.img = Image.new("1", (self.w, self.h), 1)      # 1 = белый
        self.dr = ImageDraw.Draw(self.img)

    def px(self, value_mm: float) -> int:
        return int(round(value_mm * self.px_per_mm))

    def font(self, size_mm: float, bold: bool = False, mono: bool = False):
        if mono:
            path = _mono_file()
        else:
            reg, bld = _font_files()
            path = bld if bold else reg
        return ImageFont.truetype(path, max(5, int(round(size_mm * self.px_per_mm))))

    def text(self, x_mm, y_mm, text, size_mm, bold=False, mono=False, anchor="la",
             letter_spacing_mm=0.0):
        if not text:
            return
        if letter_spacing_mm:
            self.tracked(x_mm, y_mm, text, size_mm, letter_spacing_mm, bold, mono, anchor)
            return
        self.dr.text((self.px(x_mm), self.px(y_mm)), text,
                     font=self.font(size_mm, bold, mono), fill=0, anchor=anchor)

    def text_width(self, text, size_mm, bold=False, mono=False) -> float:
        return self.dr.textlength(text, font=self.font(size_mm, bold, mono)) / self.px_per_mm

    def fit_size(self, text, size_mm, max_w_mm, bold=False, mono=False,
                letter_spacing_mm=0.0) -> float:
        """Уменьшает кегль, только если строка не влезает — макет этого не
        предусматривает (авторские тексты короткие), это подстраховка для
        длинных переводов реальных наименований из CSV."""
        if not text or max_w_mm <= 0:
            return size_mm
        width = self.tracked_width(text, size_mm, letter_spacing_mm, bold, mono)
        if width <= max_w_mm:
            return size_mm
        return max(1.6, size_mm * max_w_mm / width)

    def tracked(self, x_mm, y_mm, text, size_mm, spacing_mm, bold=True, mono=False,
               anchor="la"):
        if anchor[0] == "m":
            x_mm -= self.tracked_width(text, size_mm, spacing_mm, bold, mono) / 2
            anchor = "l" + anchor[1]
        x = x_mm
        for ch in text:
            self.dr.text((self.px(x), self.px(y_mm)), ch,
                         font=self.font(size_mm, bold, mono), fill=0, anchor=anchor)
            x += self.text_width(ch, size_mm, bold, mono) + spacing_mm

    def tracked_width(self, text, size_mm, spacing_mm, bold=True, mono=False) -> float:
        if not text:
            return 0.0
        return (sum(self.text_width(c, size_mm, bold, mono) for c in text)
                + spacing_mm * (len(text) - 1))

    def fill(self, x_mm, y_mm, w_mm, h_mm):
        self.dr.rectangle([self.px(x_mm), self.px(y_mm),
                           self.px(x_mm + w_mm), self.px(y_mm + h_mm)], fill=0)

    def paste_crop(self, path, box_x_mm, box_y_mm, spec, scale=1.0,
                   work_px_per_mm=20.0):
        """Логотип из макета: картинка отображена в spec['disp'] мм, из неё
        вырезано окно spec['off']..+box размером spec['box'] (те же
        offset/scale, что задаёт inline-style в исходном .dc.html).

        `scale` — ручная правка размера из панели макета: окно кропа в
        исходной картинке от неё не зависит, меняется только размер, в
        который готовый кроп кладётся на этикетку."""
        if not os.path.exists(path):
            return False
        src = Image.open(path).convert("RGBA")
        white = Image.new("RGBA", src.size, (255, 255, 255, 255))
        src = Image.alpha_composite(white, src).convert("L")
        disp_w = max(1, int(round(spec["disp"]["w"] * work_px_per_mm)))
        disp_h = max(1, int(round(spec["disp"]["h"] * work_px_per_mm)))
        resized = src.resize((disp_w, disp_h), Image.LANCZOS)
        ox = int(round(spec["off"]["x"] * work_px_per_mm))
        oy = int(round(spec["off"]["y"] * work_px_per_mm))
        bw = int(round(spec["box"]["w"] * work_px_per_mm))
        bh = int(round(spec["box"]["h"] * work_px_per_mm))
        cropped = resized.crop((ox, oy, ox + bw, oy + bh))
        target_w = self.px(spec["box"]["w"] * scale)
        target_h = self.px(spec["box"]["h"] * scale)
        cropped = cropped.resize((max(1, target_w), max(1, target_h)), Image.LANCZOS)
        cropped = cropped.point(lambda v: 255 if v > 200 else 0).convert("1")
        self.img.paste(cropped, (self.px(box_x_mm), self.px(box_y_mm)))
        return True


def _logo_path(name):
    return os.path.join(LOGO_DIR, LOGOS[name]["file"])


def _tweak(data: dict, key: str):
    """Ручная правка блока: (dx, dy, scale). См. layout.default_tweaks."""
    raw = ((data.get("tweaks") or {}).get(key)) or {}

    def num(name, default):
        try:
            return float(raw.get(name, default))
        except (TypeError, ValueError):
            return default

    scale = min(TWEAK_SCALE_MAX, max(TWEAK_SCALE_MIN, num("scale", 1.0)))
    return num("dx", 0.0), num("dy", 0.0), scale


def _box(key, x, y, w, h):
    """Рамка блока в системе координат макета (мм, 72x100, портрет).
    Уезжает на фронтенд, чтобы поверх картинки-превью можно было положить
    невидимые прямоугольники и таскать их мышью."""
    return {"key": key, "x": round(x, 3), "y": round(y, 3),
            "w": round(max(w, 0.0), 3), "h": round(max(h, 0.0), 3)}


def draw_header(cv: Canvas, top_mm, tw):
    """Три логотипа в ряд: justify-content:space-between, align-items:flex-start."""
    dx, dy, s = tw
    widths = [LOGOS[k]["box"]["w"] * s for k in HEADER_ORDER]
    # Ряд всегда во всю рабочую ширину: масштаб меняет размер самих
    # логотипов, а не разгон ряда, иначе при увеличении крайний логотип
    # уезжал бы за край этикетки.
    row_w = CONTENT_W_MM
    free = row_w - sum(widths)
    n_gaps = len(HEADER_ORDER) - 1
    gap = HEADER_GAP_MM * s + max(0.0, free - HEADER_GAP_MM * s * n_gaps) / n_gaps

    x = PAD_MM + dx
    row_top = top_mm + dy
    max_h = 0.0
    for i, key in enumerate(HEADER_ORDER):
        spec = LOGOS[key]
        y = row_top + spec.get("margin_top", 0.0) * s
        cv.paste_crop(_logo_path(key), x, y, spec, scale=s)
        max_h = max(max_h, y + spec["box"]["h"] * s - row_top)
        x += spec["box"]["w"] * s + (gap if i < n_gaps else 0)
    return _box("header", PAD_MM + dx, row_top, row_w, max_h), top_mm + max_h


def draw_desc(cv: Canvas, lines, top_mm, tw):
    """6 строк наименования (EN + 5 языков), letter-spacing 0.1мм, bold."""
    dx, dy, s = tw
    shown = [ln for ln in lines[:DESC["max_lines"]] if ln]
    size_mm = DESC["size"] * s
    spacing = DESC["letter_spacing"] * s
    line_h = size_mm * DESC["line_height"]
    gap = DESC["gap"] * s
    flow_top = top_mm + DESC["margin_top"] * s
    y = flow_top + dy
    box_top = y
    for line in shown:
        size = cv.fit_size(line, size_mm, CONTENT_W_MM, bold=True,
                           letter_spacing_mm=spacing)
        cv.text(PAD_MM + dx, y, line, size, bold=True, letter_spacing_mm=spacing)
        y += line_h + gap
    height = (len(shown) * line_h + max(0, len(shown) - 1) * gap) if shown else 0.0
    return (_box("desc", PAD_MM + dx, box_top, CONTENT_W_MM, height),
            flow_top + height)


def draw_made_in(cv: Canvas, made_in, top_mm, tw):
    dx, dy, s = tw
    size_mm = MADE_IN["size"] * s
    text = f"Made in {made_in}".strip()
    cv.text(PAD_MM + dx, top_mm + dy, text, size_mm,
            letter_spacing_mm=MADE_IN["letter_spacing"] * s)
    height = size_mm * MADE_IN["line_height"]
    width = cv.tracked_width(text, size_mm, MADE_IN["letter_spacing"] * s, bold=False)
    return (_box("made_in", PAD_MM + dx, top_mm + dy, max(width, 8.0), height),
            top_mm + height)


def draw_barcode(cv: Canvas, code, top_mm, tw):
    """Ряд штрихкода: контейнер 73px высотой, бары прижаты к низу, 58px
    высотой (те же пропорции, что в макете) — но реальный Code 128,
    а не декоративный узор из исходного прототипа.

    По ширине бары занимают BARCODE_ROW['width_frac'] (по умолчанию 70%)
    рабочей ширины и стоят по центру: во всю ширину, как было в макете,
    сканеру не остаётся «тихой зоны» по краям."""
    dx, dy, s = tw
    row_h_mm = BARCODE_ROW["height_px"] / PX_PER_MM * s
    bar_h_mm = BARCODE_ROW["bar_height_px"] / PX_PER_MM * s
    bars_w_mm = CONTENT_W_MM * BARCODE_ROW["width_frac"] * s
    left = PAD_MM + (CONTENT_W_MM - bars_w_mm) / 2 + dx
    bar_top = top_mm + dy + row_h_mm - bar_h_mm

    # Символ, которого нет в Code 128 (кириллица в номере и т.п.), не должен
    # ронять всю этикетку: рисуем её без полос, а про ошибку кодирования
    # пользователю и так говорит строка статуса под полем штрихкода.
    pat = None
    if code:
        try:
            pat = bc.pattern(code)
        except ValueError:
            pat = None
    if pat:
        module = bars_w_mm / pat["modules"]
        x, dark = left, True
        for width in pat["widths"]:
            if dark:
                cv.fill(x, bar_top, module * width, bar_h_mm)
            x += module * width
            dark = not dark
    return (_box("barcode", left, bar_top, bars_w_mm, bar_h_mm),
            top_mm + row_h_mm)


def draw_pn(cv: Canvas, pn, top_mm, tw):
    dx, dy, s = tw
    size_mm = PN["size"] * s
    spacing = PN["letter_spacing"] * s
    size = cv.fit_size(pn, size_mm, CONTENT_W_MM, bold=True, mono=True,
                       letter_spacing_mm=spacing)
    y = top_mm + dy
    cv.text(LABEL_W_MM / 2 + dx, y, pn, size, bold=True, mono=True,
            letter_spacing_mm=spacing, anchor="ma")
    width = cv.tracked_width(pn, size, spacing, bold=True, mono=True)
    height = size_mm * PN["line_height"]
    return (_box("pn", LABEL_W_MM / 2 + dx - width / 2, y, max(width, 8.0), height),
            top_mm + height)


def draw_pcs(cv: Canvas, pcs, min_top_mm, tw):
    """margin-top:auto в макете — прижато к нижнему краю, но не ближе
    GAP_MM к предыдущему элементу (минимум, который auto-margin не может
    нарушить; если контента слишком много, ряд просто съезжает ниже
    "идеальной" прижатой позиции, а не наезжает на PN).

    При полных 6 строках наименования и заданных в макете размерах шрифтов
    контент почти вплотную подходит к нижнему краю (запас <1мм по расчёту
    в мм из CSS-констант макета) — реальные метрики шрифта Arial в Pillow
    чуть выше эталонного Helvetica в браузере, поэтому здесь дополнительно
    ограничиваем сверху, чтобы строка PCS гарантированно не обрезалась
    краем этикетки, лишь слегка ужимая последний отступ вместо обрезания."""
    dx, dy, s = tw
    size_mm = PCS["size"] * s
    spacing = PCS["letter_spacing"] * s
    height = size_mm * PCS["line_height"]
    flush_y = LABEL_H_MM - PAD_MM - height
    hard_cap = LABEL_H_MM - height - 0.3
    y = min(max(min_top_mm, flush_y), hard_cap) + dy
    x = PAD_MM + dx
    cv.text(x, y, "PCS", size_mm, letter_spacing_mm=spacing)
    w = cv.tracked_width("PCS", size_mm, spacing, bold=False) + PCS["gap"] * s
    cv.text(x + w, y, str(pcs), size_mm, bold=True, letter_spacing_mm=spacing)
    total_w = w + cv.tracked_width(str(pcs), size_mm, spacing, bold=True)
    return _box("pcs", x, y, max(total_w, 8.0), height)


def draw_label(cv: Canvas, data: dict):
    """Рисует этикетку и возвращает рамки блоков (мм в системе макета)."""
    lines = (data.get("lines") or [])[:DESC["max_lines"]]
    boxes = []

    box, y = draw_header(cv, PAD_MM, _tweak(data, "header"))
    boxes.append(box)
    y += GAP_MM
    box, y = draw_desc(cv, lines, y, _tweak(data, "desc"))
    boxes.append(box)
    y += GAP_MM
    box, y = draw_made_in(cv, data.get("made_in", ""), y, _tweak(data, "made_in"))
    boxes.append(box)
    y += GAP_MM
    box, y = draw_barcode(cv, data.get("barcode") or data.get("pn", ""), y,
                          _tweak(data, "barcode"))
    boxes.append(box)
    y += GAP_MM
    box, y = draw_pn(cv, data.get("pn", ""), y, _tweak(data, "pn"))
    boxes.append(box)
    boxes.append(draw_pcs(cv, data.get("pcs", "1"), y + GAP_MM, _tweak(data, "pcs")))
    return boxes


def render(data: dict, scale: int = 1) -> Image.Image:
    cv = Canvas(scale)
    draw_label(cv, data)
    return cv.img


def render_with_boxes(data: dict, scale: int = 1):
    """Картинка + рамки блоков — для интерактивного превью, где рамки
    служат ручками перетаскивания поверх изображения."""
    cv = Canvas(scale)
    boxes = draw_label(cv, data)
    return cv.img, boxes


def render_for_print(data: dict, scale: int = 1) -> Image.Image:
    """То же изображение, что уходит в TSPL: макет 72x100 повёрнут на 90°,
    чтобы лечь на физический рулон 100x72 (см. build_tspl). Превью в
    браузере показывает исходную, портретную картинку и поворачивает её
    средствами CSS — поворот на 90° кратен прямому углу и потому ничего
    не искажает, так что на экране видно ровно те же пиксели, что уйдут
    на принтер, просто в удобной для чтения ориентации."""
    img = render(data, scale=scale)
    img = img.transpose(Image.ROTATE_90)                # 72x100 -> 100x72
    if data.get("rotate180"):
        img = img.transpose(Image.ROTATE_180)
    return img


# ---------------------------------------------------------------------- TSPL
def _bitmap_cmd(img: Image.Image, x_dots: int = 0, y_dots: int = 0) -> bytes:
    """Картинка -> команда BITMAP. В TSPL, как и в Pillow '1', бит 0 = чёрный."""
    img = img.convert("1")
    w, h = img.size
    width_bytes = (w + 7) // 8
    if w % 8:
        padded = Image.new("1", (width_bytes * 8, h), 1)
        padded.paste(img, (0, 0))
        img = padded
    return (f"BITMAP {x_dots},{y_dots},{width_bytes},{h},0,".encode("ascii")
            + img.tobytes() + b"\r\n")


def build_tspl(data: dict, copies: int = 1) -> bytes:
    """
    Готовое задание для TSC TE200.

    Макет нарисован 72(ш) x 100(в) мм — портрет, как настоящие этикетки
    CNH. Рулон в принтере откалиброван на 100(ш) x 72(в) мм (см.
    layout.py). Числа совпадают, только переставлены, поэтому картинку
    целиком поворачиваем на 90° перед отправкой — так она укладывается
    на физический рулон без обрезки и без искажения пропорций.

    Направление поворота (по часовой/против) не проверялось на реальном
    принтере. Если первая физическая этикетка ляжет текстом вверх ногами
    или в зеркале — включите data["rotate180"] (чекбокс в интерфейсе) и
    напечатайте снова; переворачивать код не придётся.
    """
    img = render_for_print(data, scale=1)

    job = b""
    job += f"SIZE {PRINT_W_MM:g} mm,{PRINT_H_MM:g} mm\r\n".encode()
    job += f"GAP {PRINT_GAP_MM:g} mm,0 mm\r\n".encode()
    job += f"SPEED {SPEED}\r\n".encode()
    job += f"DENSITY {DENSITY}\r\n".encode()
    job += b"DIRECTION 1,0\r\nREFERENCE 0,0\r\nSET TEAR ON\r\nCLS\r\n"
    job += _bitmap_cmd(img)
    job += f"PRINT {max(1, int(copies))},1\r\n".encode()
    return job


if __name__ == "__main__":
    demo = {
        "lines": ["OIL FILTER", "FILTRO OLIO", "FILTRE À HUILE", "ÖLFILTER",
                  "FILTRO DE ACEITE", "FILTRO DE ÓLEO"],
        "made_in": "Türkiye", "pn": "84565867", "barcode": "84565867", "pcs": "1",
    }
    out = os.path.join(HERE, "demo_label.png")
    render(demo, scale=4).convert("L").save(out)
    print("превью:", out)
    print("TSPL:", len(build_tspl(demo)), "байт")
