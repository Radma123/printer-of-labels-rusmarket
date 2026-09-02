# -*- coding: utf-8 -*-
"""
Доступ к каталогу CNH (CSV 1.14 ГБ, 3.5 млн строк).

Прямой перебор файла на каждый запрос — это ~40 секунд, для интерактивного
приложения не годится. Поэтому один раз строится индекс «каталожный номер ->
смещение в байтах», сортируется утилитой `sort` и дальше читается двоичным
поиском по mmap: любой поиск = единицы миллисекунд, память не расходуется.

Индекс кладётся рядом с CSV: <csv>.pnidx. Пересобирается, если CSV новее.
"""

import csv
import mmap
import os
import subprocess

DELIM = ";"


def index_path(csv_path: str) -> str:
    return csv_path + ".pnidx"


def index_is_fresh(csv_path: str) -> bool:
    idx = index_path(csv_path)
    return (os.path.exists(idx) and os.path.getsize(idx) > 0
            and os.path.getmtime(idx) >= os.path.getmtime(csv_path))


def build_index(csv_path: str, progress=None) -> str:
    """Собирает и сортирует индекс. progress(done_bytes, total_bytes)."""
    idx = index_path(csv_path)
    tmp = idx + ".tmp"
    total = os.path.getsize(csv_path)
    with open(csv_path, "rb") as fh, open(tmp, "wb") as out:
        offset = len(fh.readline())                   # пропускаем заголовок
        next_tick = 0
        for raw in fh:
            pn = raw.split(b";", 1)[0].strip().strip(b'"').upper()
            if pn:
                out.write(pn + b"\t" + str(offset).encode() + b"\n")
            offset += len(raw)
            if progress and offset > next_tick:
                progress(offset, total)
                next_tick = offset + 50 * 1024 * 1024
    # LC_ALL=C — байтовая сортировка, ровно та же, что у двоичного поиска ниже.
    subprocess.run(["sort", "-t", "\t", "-k1,1", tmp, "-o", idx],
                   env=dict(os.environ, LC_ALL="C"), check=True)
    os.remove(tmp)
    os.utime(idx, None)
    return idx


class Catalog:
    """Поиск строк каталога по индексу."""

    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self._idx_file = None
        self._mm = None
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as fh:
            self.header = next(csv.reader([fh.readline()], delimiter=DELIM))

    # -------------------------------------------------------------- индекс
    def open_index(self):
        if self._mm is not None:
            return
        self._idx_file = open(index_path(self.csv_path), "rb")
        self._mm = mmap.mmap(self._idx_file.fileno(), 0, access=mmap.ACCESS_READ)

    def close(self):
        if self._mm is not None:
            self._mm.close()
            self._idx_file.close()
            self._mm = None

    def _line_at(self, pos: int):
        """Начало строки, в которую попала позиция pos."""
        start = self._mm.rfind(b"\n", 0, pos) + 1
        end = self._mm.find(b"\n", start)
        if end < 0:
            end = len(self._mm)
        return start, self._mm[start:end]

    def _lower_bound(self, key: bytes) -> int:
        """Смещение первой строки индекса, чей ключ >= key."""
        lo, hi = 0, len(self._mm)
        while lo < hi:
            mid = (lo + hi) // 2
            start, line = self._line_at(mid)
            if start < lo:                     # строка началась левее окна
                start = lo
                end = self._mm.find(b"\n", start)
                line = self._mm[start:end if end > 0 else len(self._mm)]
            if line.split(b"\t", 1)[0] < key:
                lo = start + len(line) + 1
            else:
                hi = start
        return lo

    def _iter_from(self, key: bytes, limit: int):
        self.open_index()
        pos = self._lower_bound(key)
        while pos < len(self._mm) and limit > 0:
            end = self._mm.find(b"\n", pos)
            if end < 0:
                end = len(self._mm)
            line = self._mm[pos:end]
            pos = end + 1
            if not line:
                continue
            pn, _, off = line.partition(b"\t")
            yield pn.decode("utf-8", "replace"), int(off)
            limit -= 1

    # -------------------------------------------------------------- чтение
    def _row_at(self, offset: int) -> dict:
        with open(self.csv_path, "rb") as fh:
            fh.seek(offset)
            raw = fh.readline()
        row = next(csv.reader([raw.decode("utf-8", "replace")], delimiter=DELIM))
        return dict(zip(self.header, row))

    def get(self, pn: str):
        """Точное совпадение по каталожному номеру (регистр не важен)."""
        key = pn.strip().upper().encode("utf-8")
        if not key:
            return None
        for found, offset in self._iter_from(key, 1):
            if found.encode("utf-8") == key:
                return self._row_at(offset)
        return None

    def suggest(self, prefix: str, limit: int = 12):
        """Номера, начинающиеся с prefix — для автодополнения."""
        key = prefix.strip().upper().encode("utf-8")
        if not key:
            return []
        out = []
        for pn, _ in self._iter_from(key, limit * 4):
            if not pn.encode("utf-8").startswith(key):
                break
            out.append(pn)
            if len(out) >= limit:
                break
        return out


def column(row: dict, key_part: str, default: str = "") -> str:
    """Значение колонки по фрагменту её английского имени в скобках."""
    for k, v in row.items():
        if key_part in k:
            return (v or "").strip()
    return default


def row_to_fields(row: dict) -> dict:
    """Строка каталога -> поля, которые нужны этикетке."""
    return {
        "pn": column(row, "display_pn") or column(row, "part_number"),
        "barcode": column(row, "part_number"),
        "desc_en": column(row, "exact_description_en"),
        "desc_ru": column(row, "exact_description_ru"),
        "category_en": column(row, "category_term_en"),
        "category_ru": column(row, "category_term_ru"),
        "brand": column(row, "manufacturer"),
        "status": column(row, "service_status"),
        "replacements": column(row, "replacements"),
        "catalog": column(row, "source_catalog"),
    }
