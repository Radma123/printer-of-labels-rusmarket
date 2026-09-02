#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Печать этикеток 100 x 72 мм на TSC TE200 (203 dpi) командами TSPL.

Кириллица печатается картинкой (Pillow -> команда BITMAP), потому что встроенные
шрифты принтера русского не знают. Штрихкод и QR рисует сам принтер.

Быстрый старт:
    python3 tsc_label.py --check                      # проверить окружение
    python3 tsc_label.py --demo --preview demo.png    # посмотреть демо-этикетку
    python3 tsc_label.py --pn C5NNF892A --preview p.png
    python3 tsc_label.py --pn C5NNF892A --printer TE200
"""

import argparse
import csv
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_DEFAULT = os.path.join(HERE, "CNH_All_Parts_not-Full_20Cols.csv")

PIL_OK, PIL_ERR = True, ""
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as exc:                                   # noqa: BLE001
    PIL_OK, PIL_ERR = False, str(exc)

# ---------------------------------------------------------------- параметры
DPI        = 203          # TE200 = 203 dpi = 8 точек на мм
LABEL_W_MM = 100.0        # ширина этикетки (поперёк, вдоль головки)
LABEL_H_MM = 72.0         # высота этикетки (по направлению подачи)
GAP_MM     = 3.0          # зазор между этикетками (как настроено в принтере)
SPEED      = 4            # дюймов/с
DENSITY    = 8            # 0..15, нагрев головки
MARGIN_MM  = 3.0          # поля, чтобы не печатать в самый край

# Пары (обычный, жирный). Берётся первая пара, которая реально есть на диске.
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Verdana.ttf",
     "/System/Library/Fonts/Supplemental/Verdana Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Tahoma.ttf",
     "/System/Library/Fonts/Supplemental/Tahoma Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
_FONTS = None


def mm(value_mm: float) -> int:
    """Миллиметры -> точки принтера."""
    return int(round(value_mm * DPI / 25.4))


def resolve_fonts():
    """Ищет пару шрифтов с кириллицей. Переопределяется переменными
    окружения LABEL_FONT / LABEL_FONT_BOLD."""
    global _FONTS
    if _FONTS:
        return _FONTS
    env = os.environ.get("LABEL_FONT")
    if env and os.path.exists(env):
        _FONTS = (env, os.environ.get("LABEL_FONT_BOLD", env))
        return _FONTS
    for reg, bold in FONT_CANDIDATES:
        if os.path.exists(reg):
            _FONTS = (reg, bold if os.path.exists(bold) else reg)
            return _FONTS
    for pattern in ("/System/Library/Fonts/Supplemental/*.ttf",
                    "/System/Library/Fonts/*.ttf",
                    "/usr/share/fonts/**/*.ttf"):
        found = sorted(glob.glob(pattern, recursive=True))
        if found:
            _FONTS = (found[0], found[0])
            return _FONTS
    raise SystemExit("Не найден ни один TTF-шрифт. Задайте путь: "
                     "export LABEL_FONT=/путь/к/шрифту.ttf")


def font(size_mm: float, bold: bool = False):
    reg, bld = resolve_fonts()
    return ImageFont.truetype(bld if bold else reg, mm(size_mm))


# ------------------------------------------------------------- работа с CSV
def find_row(csv_path: str, pn: str):
    """Ищет строку по каталожному номеру. Читает файл потоком, поэтому
    размер CSV значения не имеет."""
    needle = (pn.strip().upper() + ";").encode("utf-8")
    with open(csv_path, "rb") as fh:
        header_raw = fh.readline()
        for raw in fh:
            if raw.upper().startswith(needle):
                hdr = next(csv.reader([header_raw.decode("utf-8-sig", "replace")],
                                      delimiter=";", quotechar='"'))
                row = next(csv.reader([raw.decode("utf-8", "replace")],
                                      delimiter=";", quotechar='"'))
                return dict(zip(hdr, row))
    return None


def find_similar(csv_path: str, substr: str, limit: int = 15):
    """Подсказка: первые N каталожных номеров, содержащих подстроку."""
    needle = substr.strip().upper().encode("utf-8")
    out = []
    with open(csv_path, "rb") as fh:
        fh.readline()
        for raw in fh:
            pn = raw.split(b";", 1)[0]
            if needle in pn.upper():
                out.append(pn.decode("utf-8", "replace"))
                if len(out) >= limit:
                    break
    return out


def row_to_label(row: dict) -> dict:
    """20 колонок каталога -> поля, которые реально влезают на этикетку."""
    def col(key_part, default=""):
        for k, v in row.items():
            if key_part in k:
                return (v or "").strip()
        return default

    return {
        "pn":        col("display_pn") or col("part_number"),
        "desc_ru":   col("exact_description_ru"),
        "desc_en":   col("exact_description_en"),
        "category":  col("category_term_ru") or col("category_term_en"),
        "brand":     col("manufacturer"),
        "catalog":   col("source_catalog"),
        "status":    col("service_status"),
        "repl":      col("replacements"),
        "barcode":   col("part_number"),
    }


DEMO = {
    "pn": "C5NNF892A", "desc_ru": "ЖЕСТКАЯ ТРУБКА", "desc_en": "RIGID TUBE",
    "category": "ПОДБАРАБАНЬЕ ДЛЯ КРУГЛЫХ ЗУБЬЕВ", "brand": "FOR",
    "catalog": "Case IH (CSAG)", "status": "Поставляется",
    "repl": "D3NNF892A", "barcode": "C5NNF892A",
}


# --------------------------------------------------------------- отрисовка
def wrap(draw, text, fnt, max_w, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if draw.textlength(probe, font=fnt) <= max_w or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if lines and draw.textlength(lines[-1], font=fnt) > max_w:
        while lines[-1] and draw.textlength(lines[-1] + "…", font=fnt) > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


# Зоны, которые рисует сам принтер (в них картинка не пишется)
BC_X, BC_Y, BC_H = mm(MARGIN_MM), mm(46.0), mm(11.0)
QR_X, QR_Y, QR_CELL = mm(76.0), mm(45.0), 4


def render_label(d: dict) -> "Image.Image":
    """Весь текст этикетки одной монохромной картинкой 800x576 точек."""
    W, H = mm(LABEL_W_MM), mm(LABEL_H_MM)
    img = Image.new("1", (W, H), 1)                 # 1 = белый
    dr = ImageDraw.Draw(img)
    x0 = mm(MARGIN_MM)
    max_w = W - 2 * x0
    y = mm(2.5)

    f_pn = font(7.5, bold=True)
    dr.text((x0, y), d["pn"], font=f_pn, fill=0)
    y += int(f_pn.getbbox("Ay")[3] * 1.15)
    dr.line([(x0, y), (W - x0, y)], fill=0, width=2)
    y += mm(1.8)

    if d.get("desc_ru"):
        f = font(4.6, bold=True)
        for line in wrap(dr, d["desc_ru"], f, max_w, 2):
            dr.text((x0, y), line, font=f, fill=0)
            y += int(f.getbbox("Ay")[3] * 1.25)

    if d.get("desc_en"):
        f = font(3.4)
        for line in wrap(dr, d["desc_en"], f, max_w, 1):
            dr.text((x0, y), line, font=f, fill=0)
            y += int(f.getbbox("Ay")[3] * 1.35)

    y += mm(1.0)
    f = font(3.2)
    meta = []
    if d.get("brand"):
        meta.append(f"Бренд: {d['brand']}")
    if d.get("catalog"):
        meta.append(d["catalog"])
    if d.get("status"):
        meta.append(d["status"])
    if meta:
        for line in wrap(dr, "  ·  ".join(meta), f, max_w, 1):
            dr.text((x0, y), line, font=f, fill=0)
            y += int(f.getbbox("Ay")[3] * 1.3)
    if d.get("category"):
        for line in wrap(dr, d["category"], f, max_w, 1):
            dr.text((x0, y), line, font=f, fill=0)
            y += int(f.getbbox("Ay")[3] * 1.3)
    if d.get("repl"):
        for line in wrap(dr, "Замены: " + d["repl"], f, max_w, 1):
            dr.text((x0, y), line, font=f, fill=0)
            y += int(f.getbbox("Ay")[3] * 1.3)
    return img


def bitmap_cmd(img, x_dots: int, y_dots: int) -> bytes:
    """Картинка -> команда TSPL BITMAP. В TSPL бит 0 = чёрная точка, и Pillow
    в режиме '1' пакует биты так же, поэтому инверсия не нужна."""
    img = img.convert("1")
    w, h = img.size
    width_bytes = (w + 7) // 8
    if w % 8:
        padded = Image.new("1", (width_bytes * 8, h), 1)
        padded.paste(img, (0, 0))
        img = padded
    return (f"BITMAP {x_dots},{y_dots},{width_bytes},{h},0,".encode("ascii")
            + img.tobytes() + b"\r\n")


def build_job(d: dict, copies: int = 1) -> bytes:
    job = b""
    job += f"SIZE {LABEL_W_MM:g} mm,{LABEL_H_MM:g} mm\r\n".encode()
    job += f"GAP {GAP_MM:g} mm,0 mm\r\n".encode()
    job += f"SPEED {SPEED}\r\n".encode()
    job += f"DENSITY {DENSITY}\r\n".encode()
    job += b"DIRECTION 1,0\r\n"
    job += b"REFERENCE 0,0\r\n"
    job += b"SET TEAR ON\r\n"
    job += b"CLS\r\n"
    job += bitmap_cmd(render_label(d), 0, 0)
    code = (d.get("barcode") or d["pn"]).strip()
    if code:
        job += f'BARCODE {BC_X},{BC_Y},"128",{BC_H},1,0,2,4,"{code}"\r\n'.encode()
        job += f'QRCODE {QR_X},{QR_Y},M,{QR_CELL},A,0,"{code}"\r\n'.encode()
    job += f"PRINT {copies},1\r\n".encode()
    return job


def build_preview(d: dict, path: str) -> None:
    img = render_label(d).convert("L").convert("RGB")
    dr = ImageDraw.Draw(img)
    code = (d.get("barcode") or d["pn"]).strip()
    dr.rectangle([BC_X, BC_Y, BC_X + mm(52), BC_Y + BC_H + mm(4)], outline=(190, 190, 190))
    dr.text((BC_X + 6, BC_Y + 6), f"BARCODE {code}", font=font(3.0), fill=(120, 120, 120))
    dr.rectangle([QR_X, QR_Y, QR_X + QR_CELL * 29, QR_Y + QR_CELL * 29], outline=(190, 190, 190))
    dr.text((QR_X + 6, QR_Y + 6), "QR", font=font(3.0), fill=(120, 120, 120))
    dr.rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], outline=(210, 210, 210))
    img.save(path)


# ----------------------------------------------------------------- отправка
# lpstat выводит статус на языке системы ("принтер X свободен" в русской локали
# вместо "printer X is idle"), поэтому парсить конкретное слово нельзя — форсируем
# английскую локаль только для этого вызова, независимо от языка macOS.
_CUPS_ENV = dict(os.environ, LC_ALL="C", LANG="C")


def queues():
    try:
        out = subprocess.run(["lpstat", "-p"], capture_output=True, text=True,
                             timeout=15, env=_CUPS_ENV).stdout
    except Exception:                                       # noqa: BLE001
        return []
    return [ln.split()[1] for ln in out.splitlines() if ln.startswith("printer ")]


def send_cups(job: bytes, queue: str) -> None:
    res = subprocess.run(["lp", "-d", queue, "-o", "raw", "-"],
                         input=job, capture_output=True, env=_CUPS_ENV)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", "replace").strip()
        print(f"Не удалось отправить задание: {err}", file=sys.stderr)
        avail = queues()
        if avail:
            print("Доступные очереди: " + ", ".join(avail), file=sys.stderr)
        else:
            print("На этом Mac вообще нет добавленных принтеров. "
                  "Проверьте, что TE200 не проброшен в Windows-ВМ, и добавьте его "
                  "в «Системные настройки → Принтеры и сканеры».", file=sys.stderr)
        sys.exit(1)
    print(res.stdout.decode("utf-8", "replace").strip() or f"отправлено в {queue}")


def send_usb(job: bytes, vid: int = 0x1203) -> None:
    import usb.core, usb.util                                # noqa: PLC0415
    dev = usb.core.find(idVendor=vid)
    if dev is None:
        raise SystemExit("Принтер не найден на USB (включён? не занят виртуалкой?)")
    dev.set_configuration()
    intf = dev.get_active_configuration()[(0, 0)]
    ep = usb.util.find_descriptor(
        intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_OUT)
    ep.write(job, timeout=10000)
    print("отправлено по USB")


# -------------------------------------------------------------- диагностика
def check(csv_path: str) -> None:
    print("Pillow:       да" if PIL_OK else
          f"Pillow:       НЕТ ({PIL_ERR})\n"
          "              установите:  python3 -m pip install --user pillow")
    if PIL_OK:
        try:
            reg, bold = resolve_fonts()
            print("Шрифты:      ", reg)
            print("             ", bold)
        except SystemExit as exc:
            print("Шрифты:       НЕТ —", exc)
    qs = queues()
    print("Принтеры:    ", ", ".join(qs) if qs else
          "не найдено ни одной очереди CUPS\n"
          "              → отсоедините принтер от Windows-ВМ и добавьте его в macOS")
    print("Каталог CSV: ", csv_path if os.path.exists(csv_path) else f"НЕ НАЙДЕН ({csv_path})")
    if os.path.exists(csv_path):
        print("              размер %.2f ГБ" % (os.path.getsize(csv_path) / 1024 ** 3))
    print("Python:      ", sys.version.split()[0], "—", sys.executable)


# --------------------------------------------------------------------- CLI
def main() -> None:
    p = argparse.ArgumentParser(description="Печать этикеток 100x72 мм на TSC TE200")
    p.add_argument("--check", action="store_true", help="проверить окружение и выйти")
    p.add_argument("--pn", help="каталожный номер детали из CSV")
    p.add_argument("--find", help="найти каталожные номера по подстроке")
    p.add_argument("--csv", default=CSV_DEFAULT, help="путь к каталогу CSV")
    p.add_argument("--demo", action="store_true", help="демо-этикетка без CSV")
    p.add_argument("--preview", metavar="PNG", help="сохранить превью картинкой")
    p.add_argument("--out", metavar="FILE", help="сохранить задание TSPL в файл")
    p.add_argument("--printer", metavar="QUEUE", help="имя очереди CUPS")
    p.add_argument("--usb", action="store_true", help="печать напрямую через USB (pyusb)")
    p.add_argument("--copies", type=int, default=1)
    a = p.parse_args()

    if a.check:
        check(a.csv)
        return

    if a.find:
        if not os.path.exists(a.csv):
            raise SystemExit(f"CSV не найден: {a.csv}")
        hits = find_similar(a.csv, a.find)
        print("\n".join(hits) if hits else "ничего не найдено")
        return

    if not PIL_OK:
        raise SystemExit("Не установлен Pillow. Выполните:\n"
                         "    python3 -m pip install --user pillow")

    if a.demo or not a.pn:
        data = DEMO
        if not a.demo:
            print("Номер детали не задан — печатаю демо-этикетку "
                  "(--pn НОМЕР для реальной детали)", file=sys.stderr)
    else:
        if not os.path.exists(a.csv):
            raise SystemExit(f"CSV не найден: {a.csv}")
        row = find_row(a.csv, a.pn)
        if row is None:
            hint = find_similar(a.csv, a.pn, 10)
            msg = f"Деталь {a.pn} не найдена в каталоге."
            if hint:
                msg += "\nПохожие номера:\n  " + "\n  ".join(hint)
            raise SystemExit(msg)
        data = row_to_label(row)
        print(f"{data['pn']} — {data['desc_ru'] or data['desc_en']}")

    job = build_job(data, copies=a.copies)

    if a.preview:
        build_preview(data, a.preview)
        print(f"превью: {a.preview}")
    if a.out:
        with open(a.out, "wb") as fh:
            fh.write(job)
        print(f"задание: {a.out} ({len(job)} байт)")
    if a.printer:
        send_cups(job, a.printer)
    if a.usb:
        send_usb(job)
    if not any([a.preview, a.out, a.printer, a.usb]):
        sys.stdout.buffer.write(job)


if __name__ == "__main__":
    main()
