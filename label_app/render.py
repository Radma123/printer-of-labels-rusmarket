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

    def paste_crop(self, path, box_x_mm, box_y_mm, spec, work_px_per_mm=20.0):
        """Логотип из макета: картинка отображена в spec['disp'] мм, из неё
        вырезано окно spec['off']..+box размером spec['box'] (те же
        offset/scale, что задаёт inline-style в исходном .dc.html)."""
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
        target_w, target_h = self.px(spec["box"]["w"]), self.px(spec["box"]["h"])
        cropped = cropped.resize((max(1, target_w), max(1, target_h)), Image.LANCZOS)
        cropped = cropped.point(lambda v: 255 if v > 200 else 0).convert("1")
        self.img.paste(cropped, (self.px(box_x_mm), self.px(box_y_mm)))
        return True


def _logo_path(name):
    return os.path.join(LOGO_DIR, LOGOS[name]["file"])


def draw_header(cv: Canvas):
    """Три логотипа в ряд: justify-content:space-between, align-items:flex-start."""
    widths = [LOGOS[k]["box"]["w"] for k in HEADER_ORDER]
    total_w = sum(widths)
    free = CONTENT_W_MM - total_w
    n_gaps = len(HEADER_ORDER) - 1
    gap = HEADER_GAP_MM + max(0.0, free - HEADER_GAP_MM * n_gaps) / n_gaps

    x = PAD_MM
    row_top = PAD_MM
    max_h = 0.0
    for i, key in enumerate(HEADER_ORDER):
        spec = LOGOS[key]
        y = row_top + spec.get("margin_top", 0.0)
        cv.paste_crop(_logo_path(key), x, y, spec)
        max_h = max(max_h, y + spec["box"]["h"] - row_top)
        x += spec["box"]["w"] + (gap if i < n_gaps else 0)
    return row_top + max_h


def draw_desc(cv: Canvas, lines, top_mm):
    """6 строк наименования (EN + 5 языков), letter-spacing 0.1мм, bold."""
    y = top_mm + DESC["margin_top"]
    line_h = DESC["size"] * DESC["line_height"]
    for i, line in enumerate(lines[:DESC["max_lines"]]):
        if not line:
            continue
        size = cv.fit_size(line, DESC["size"], CONTENT_W_MM, bold=True,
                           letter_spacing_mm=DESC["letter_spacing"])
        cv.text(PAD_MM, y, line, size, bold=True, letter_spacing_mm=DESC["letter_spacing"])
        y += line_h + DESC["gap"]
    return y - DESC["gap"] if lines[:DESC["max_lines"]] else top_mm + DESC["margin_top"]


def draw_made_in(cv: Canvas, made_in, top_mm):
    text = f"Made in {made_in}".strip()
    cv.text(PAD_MM, top_mm, text, MADE_IN["size"],
            letter_spacing_mm=MADE_IN["letter_spacing"])
    return top_mm + MADE_IN["size"] * MADE_IN["line_height"]


def draw_barcode(cv: Canvas, code, top_mm):
    """Ряд штрихкода: контейнер 73px высотой, бары прижаты к низу, 32px
    высотой (те же пропорции, что в макете) — но реальный Code 128,
    а не декоративный узор из исходного прототипа."""
    row_h_mm = BARCODE_ROW["height_px"] / PX_PER_MM
    bar_h_mm = BARCODE_ROW["bar_height_px"] / PX_PER_MM
    bar_top = top_mm + row_h_mm - bar_h_mm

    if code:
        pat = bc.pattern(code)
        module = CONTENT_W_MM / pat["modules"]
        x, dark = PAD_MM, True
        for width in pat["widths"]:
            if dark:
                cv.fill(x, bar_top, module * width, bar_h_mm)
            x += module * width
            dark = not dark
    return top_mm + row_h_mm


def draw_pn(cv: Canvas, pn, top_mm):
    size = cv.fit_size(pn, PN["size"], CONTENT_W_MM, bold=True, mono=True,
                       letter_spacing_mm=PN["letter_spacing"])
    cv.text(LABEL_W_MM / 2, top_mm, pn, size, bold=True, mono=True,
            letter_spacing_mm=PN["letter_spacing"], anchor="ma")
    return top_mm + PN["size"] * PN["line_height"]


def draw_pcs(cv: Canvas, pcs, min_top_mm):
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
    flush_y = LABEL_H_MM - PAD_MM - PCS["size"] * PCS["line_height"]
    hard_cap = LABEL_H_MM - PCS["size"] * PCS["line_height"] - 0.3
    y = min(max(min_top_mm, flush_y), hard_cap)
    cv.text(PAD_MM, y, "PCS", PCS["size"], letter_spacing_mm=PCS["letter_spacing"])
    w = cv.text_width("PCS", PCS["size"]) + PCS["gap"]
    cv.text(PAD_MM + w, y, str(pcs), PCS["size"], bold=True,
            letter_spacing_mm=PCS["letter_spacing"])


def draw_label(cv: Canvas, data: dict):
    lines = (data.get("lines") or [])[:DESC["max_lines"]]
    y = draw_header(cv)
    y += GAP_MM
    y = draw_desc(cv, lines, y)
    y += GAP_MM
    y = draw_made_in(cv, data.get("made_in", ""), y)
    y += GAP_MM
    y = draw_barcode(cv, data.get("barcode") or data.get("pn", ""), y)
    y += GAP_MM
    y = draw_pn(cv, data.get("pn", ""), y)
    draw_pcs(cv, data.get("pcs", "1"), y + GAP_MM)


def render(data: dict, scale: int = 1) -> Image.Image:
    cv = Canvas(scale)
    draw_label(cv, data)
    return cv.img


def render_for_print(data: dict, scale: int = 1) -> Image.Image:
    """То же изображение, что уходит в TSPL: макет 72x100 повёрнут на 90°,
    чтобы лечь на физический рулон 100x72 (см. build_tspl). Используется и
    для реального задания печати, и для «точного превью печати» в браузере —
    по умолчанию показываем именно эту, повёрнутую, ориентацию, а не
    исходный портретный макет, иначе превью не совпадает с тем, что
    физически выйдет из принтера."""
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
