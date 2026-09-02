#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальное веб-приложение для этикеток CNH 100 x 72 мм.

    python3 label_app/server.py            # откроет http://127.0.0.1:8765

Что делает сервер:
  * ищет деталь в CSV-каталоге по каталожному номеру (через индекс, мгновенно);
  * переводит английское наименование на IT/FR/DE/ES/PT бесплатным API;
  * отдаёт раскладку Code 128 для превью в браузере;
  * рисует точное превью печати (PNG) и печатает на TSC TE200 через CUPS.

Слушает только 127.0.0.1 — наружу ничего не открывается.
"""

import base64
import http.server
import io
import json
import os
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import barcode as bc                                        # noqa: E402
import catalog                                              # noqa: E402
import render                                               # noqa: E402
import translate as tr                                      # noqa: E402
from layout import DEFAULTS                                 # noqa: E402
import layout as layout_mod                                 # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
CSV_PATH = os.environ.get(
    "LABEL_CSV",
    os.path.join(os.path.dirname(HERE), "CNH_All_Parts_not-Full_20Cols.csv"))
PORT = int(os.environ.get("LABEL_PORT", "8765"))

_cat = None
_cat_lock = threading.Lock()
_index_state = {"running": False, "done": 0, "total": 0, "error": ""}

# lpstat/lp переводят вывод на язык системы, поэтому парсить его можно
# только в английской локали — иначе на русской macOS очередь не находится.
_CUPS_ENV = dict(os.environ, LC_ALL="C", LANG="C")


def get_catalog():
    """Каталог открывается лениво: без CSV приложение всё равно работает."""
    global _cat
    with _cat_lock:
        if _cat is None and os.path.exists(CSV_PATH):
            _cat = catalog.Catalog(CSV_PATH)
        return _cat


def build_index_async():
    def work():
        _index_state.update(running=True, done=0, error="",
                            total=os.path.getsize(CSV_PATH))
        try:
            catalog.build_index(
                CSV_PATH,
                progress=lambda done, total: _index_state.update(done=done, total=total))
        except Exception as exc:                             # noqa: BLE001
            _index_state["error"] = str(exc)
        finally:
            _index_state["running"] = False
            global _cat
            with _cat_lock:
                if _cat is not None:
                    _cat.close()
                _cat = None
    threading.Thread(target=work, daemon=True).start()


def printers():
    # lpstat -p / -a печатают локализованный текст статуса ("принтер X
    # свободен") даже с LC_ALL=C — на macOS lpstat берёт язык из системных
    # настроек, а не из окружения процесса. -e — единственный режим, где
    # выводятся только имена очередей, без переводимого текста вокруг.
    try:
        out = subprocess.run(["lpstat", "-e"], capture_output=True, text=True,
                             timeout=10, env=_CUPS_ENV).stdout
    except Exception:                                        # noqa: BLE001
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- ответы
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def fail(self, message, code=400):
        self.json({"error": message}, code)

    def log_message(self, fmt, *args):                       # тише в консоли
        pass

    # -------------------------------------------------------------- статика
    def serve_static(self, rel):
        path = os.path.normpath(os.path.join(STATIC, rel.lstrip("/")))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self.fail("не найдено", 404)
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".png": "image/png", ".svg": "image/svg+xml",
        }.get(os.path.splitext(path)[1], "application/octet-stream")
        with open(path, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        one = lambda k, d="": (q.get(k) or [d])[0]           # noqa: E731

        if url.path in ("/", "/index.html"):
            return self.serve_static("index.html")
        if not url.path.startswith("/api/"):
            return self.serve_static(url.path)

        if url.path == "/api/status":
            return self.json({
                "csv": CSV_PATH,
                "csv_exists": os.path.exists(CSV_PATH),
                "index_ready": (os.path.exists(CSV_PATH)
                                and catalog.index_is_fresh(CSV_PATH)),
                "index": _index_state,
                "printers": printers(),
                "defaults": DEFAULTS,
                "layout": layout_mod.as_dict(),
                "langs": ["en"] + list(tr.LANGS),
                "lang_names": tr.LANG_NAMES,
            })

        if url.path == "/api/layout":
            return self.json({"layout": layout_mod.as_dict()})

        if url.path == "/api/barcode":
            code = one("text").strip()
            if not code:
                return self.json({"widths": [], "modules": 0})
            try:
                return self.json(bc.pattern(code))
            except ValueError as exc:
                return self.fail(str(exc))

        if url.path == "/api/part":
            cat = get_catalog()
            if cat is None:
                return self.fail(f"CSV не найден: {CSV_PATH}", 503)
            if not catalog.index_is_fresh(CSV_PATH):
                return self.fail("индекс каталога ещё не построен", 409)
            row = cat.get(one("pn"))
            if row is None:
                return self.json({"found": False,
                                  "suggest": cat.suggest(one("pn"), 8)})
            fields = catalog.row_to_fields(row)
            payload = {"found": True, "fields": fields}
            if one("translate", "1") == "1" and fields["desc_en"]:
                payload["translation"] = tr.translate(fields["desc_en"])
            return self.json(payload)

        if url.path == "/api/suggest":
            cat = get_catalog()
            if cat is None or not catalog.index_is_fresh(CSV_PATH):
                return self.json({"items": []})
            return self.json({"items": cat.suggest(one("q"), int(one("limit", "10")))})

        if url.path == "/api/preview.png":
            data = json.loads(one("data", "{}"))
            scale = max(1, min(6, int(one("scale", "3"))))
            # По умолчанию отдаём картинку в ориентации, в которой она
            # реально уйдёт на печать (повёрнута на 90°, см.
            # render.render_for_print) — иначе превью не совпадает с тем,
            # что физически напечатает принтер. mode=design — исходный
            # портретный макет 72x100, как в Claude Design.
            if one("mode", "print") == "design":
                img = render.render(data, scale=scale).convert("L")
            else:
                img = render.render_for_print(data, scale=scale).convert("L")
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return self._send(200, buf.getvalue(), "image/png")

        return self.fail("неизвестный метод API", 404)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.fail("некорректный JSON")

        if url.path == "/api/translate":
            text = (body.get("text") or "").strip()
            if not text:
                return self.fail("пустой текст")
            return self.json(tr.translate(text, refresh=bool(body.get("refresh"))))

        if url.path == "/api/index/build":
            if not os.path.exists(CSV_PATH):
                return self.fail(f"CSV не найден: {CSV_PATH}", 503)
            if not _index_state["running"]:
                build_index_async()
            return self.json({"started": True, "index": _index_state})

        if url.path == "/api/preview":
            # Картинка и рамки блоков — одним ответом: рамки считает тот же
            # проход отрисовки, что и картинку, поэтому ручки перетаскивания
            # на фронтенде всегда лежат ровно там, где нарисован блок.
            data = body.get("label") or {}
            scale = max(1, min(6, int(body.get("scale") or 3)))
            try:
                img, boxes = render.render_with_boxes(data, scale=scale)
            except Exception as exc:                         # noqa: BLE001
                # Иначе исключение уходит в трейсбек и браузер получает
                # оборванный ответ — превью просто молча не появляется.
                return self.fail(f"не удалось нарисовать этикетку: {exc}", 500)
            buf = io.BytesIO()
            img.convert("L").save(buf, "PNG")
            return self.json({
                "png": "data:image/png;base64,"
                       + base64.b64encode(buf.getvalue()).decode("ascii"),
                "boxes": boxes,
                "design": {"w": layout_mod.LABEL_W_MM, "h": layout_mod.LABEL_H_MM},
                # Угол (CSS, по часовой), под которым портретный макет
                # ложится на рулон принтера: render_for_print крутит
                # картинку на 90° ПРОТИВ часовой (PIL ROTATE_90), то есть
                # на экране это те же -90° = 270°.
                "print_angle": 90 if data.get("rotate180") else 270,
            })

        if url.path == "/api/print":
            queue = (body.get("printer") or "").strip()
            if not queue:
                return self.fail("не выбран принтер")
            copies = max(1, min(999, int(body.get("copies") or 1)))
            job = render.build_tspl(body.get("label") or {}, copies)
            res = subprocess.run(["lp", "-d", queue, "-o", "raw", "-"],
                                 input=job, capture_output=True, env=_CUPS_ENV)
            if res.returncode != 0:
                return self.fail(res.stderr.decode("utf-8", "replace").strip()
                                 or "CUPS отклонил задание", 500)
            return self.json({"ok": True, "copies": copies,
                              "message": res.stdout.decode("utf-8", "replace").strip()})

        if url.path == "/api/tspl":
            job = render.build_tspl(body.get("label") or {},
                                    int(body.get("copies") or 1))
            path = os.path.join(HERE, "last_job.tspl")
            with open(path, "wb") as fh:
                fh.write(job)
            return self.json({"ok": True, "path": path, "bytes": len(job)})

        return self.fail("неизвестный метод API", 404)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    if not os.path.exists(CSV_PATH):
        print(f"! CSV не найден: {CSV_PATH}\n  поиск по каталогу будет недоступен, "
              f"всё остальное работает")
    elif not catalog.index_is_fresh(CSV_PATH):
        print("! Индекс каталога не построен — соберите его кнопкой в приложении "
              "(один раз, ~2 минуты)")

    url = f"http://127.0.0.1:{PORT}/"
    print(f"Этикетки CNH: {url}   (Ctrl+C — остановить)")
    if os.environ.get("LABEL_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    with Server(("127.0.0.1", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nостановлено")


if __name__ == "__main__":
    main()
