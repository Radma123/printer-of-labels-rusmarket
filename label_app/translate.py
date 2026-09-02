# -*- coding: utf-8 -*-
"""
Перевод наименования детали EN -> IT / FR / DE / ES / PT через бесплатный
API MyMemory (https://mymemory.translated.net/doc/spec.php).

Ключ не нужен. Лимит анонимно — 5 000 символов в сутки; если задать
переменную окружения MYMEMORY_EMAIL, лимит поднимается до 50 000.

Переводы кэшируются в translation_cache.json рядом с модулем, поэтому
повторная печать той же детали лимит не тратит и работает без сети.
"""

import json
import os
import threading
import urllib.parse
import urllib.request

API = "https://api.mymemory.translated.net/get"
LANGS = ("it", "fr", "de", "es", "pt")
LANG_NAMES = {
    "en": "English", "it": "Italiano", "fr": "Français",
    "de": "Deutsch", "es": "Español", "pt": "Português",
}

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, "translation_cache.json")
TIMEOUT = 12

_lock = threading.Lock()
_cache = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        except Exception:                                   # noqa: BLE001
            _cache = {}
    return _cache


def _save_cache() -> None:
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_cache, fh, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, CACHE_PATH)


def _fetch(text: str, lang: str) -> str:
    """Один запрос к MyMemory. Бросает исключение при сетевой ошибке."""
    params = {"q": text, "langpair": f"en|{lang}"}
    email = os.environ.get("MYMEMORY_EMAIL", "").strip()
    if email:
        params["de"] = email
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "cnh-label-app/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.load(resp)

    if data.get("quotaFinished"):
        raise RuntimeError("суточный лимит MyMemory исчерпан")
    out = (data.get("responseData") or {}).get("translatedText") or ""
    if not out or "MYMEMORY WARNING" in out.upper():
        raise RuntimeError(data.get("responseDetails") or "пустой ответ переводчика")
    return out


def translate(en_text: str, refresh: bool = False) -> dict:
    """
    EN -> {'en':…, 'it':…, …, 'source': {lang: 'cache'|'api'|'error'},
           'errors': {lang: текст ошибки}}
    Языки переводятся параллельно: пять запросов идут одновременно.
    """
    src = (en_text or "").strip()
    result = {"en": src.upper(), "source": {}, "errors": {}}
    for lang in LANGS:
        result[lang] = ""
    if not src:
        return result

    cache = _load_cache()
    key_base = src.upper()
    todo = []
    for lang in LANGS:
        key = f"{key_base}|{lang}"
        if not refresh and key in cache:
            result[lang] = cache[key]
            result["source"][lang] = "cache"
        else:
            todo.append(lang)

    fetched = {}

    def worker(lang):
        try:
            fetched[lang] = _fetch(src, lang)
        except Exception as exc:                            # noqa: BLE001
            result["errors"][lang] = str(exc)

    threads = [threading.Thread(target=worker, args=(l,)) for l in todo]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for lang in todo:
        if lang in fetched:
            # MyMemory иногда приклеивает хвостовую пунктуацию — на этикетке она лишняя.
            text = fetched[lang].strip().strip(" .,;:–—-").upper()
            result[lang] = text
            result["source"][lang] = "api"
            with _lock:
                cache[f"{key_base}|{lang}"] = text
        else:
            result["source"][lang] = "error"

    if fetched:
        with _lock:
            _save_cache()
    return result


def lines(en_text: str, refresh: bool = False):
    """Шесть строк этикетки в порядке EN, IT, FR, DE, ES, PT."""
    t = translate(en_text, refresh)
    return [t["en"]] + [t[l] for l in LANGS]


if __name__ == "__main__":                                  # быстрая проверка
    import sys
    for sample in (sys.argv[1:] or ["OIL FILTER", "FUEL FILTER", "TAPERED BEARING"]):
        t = translate(sample)
        print(f"\n{sample}")
        for lang in ("en",) + LANGS:
            mark = t["source"].get(lang, "")
            err = t["errors"].get(lang, "")
            print(f"  {lang}: {t[lang]:<34} {mark}{' ' + err if err else ''}")
