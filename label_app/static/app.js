// Приложение этикеток CNH 72x100 (портрет — макет Claude Design
// Label 100x72.dc.html). Один файл, без сборки, без npm.
//
// Превью — не отдельная вёрстка этикетки, а та самая картинка 203 dpi,
// которую рисует render.py и которая уходит на принтер. Браузер только
// поворачивает её (поворот кратен 90° ничего не искажает, поэтому на
// экране ровно те же пиксели) и кладёт поверх прозрачные рамки, за
// которые блоки можно таскать мышью. Все правки макета (сдвиг и размер
// блоков) уходят на сервер вместе с данными этикетки, так что печатается
// ровно то, что видно.

const $ = (id) => document.getElementById(id);

const LANGS = ["it", "fr", "de", "es", "pt"];
const FLAGS = { en: "🇬🇧", it: "🇮🇹", fr: "🇫🇷", de: "🇩🇪", es: "🇪🇸", pt: "🇵🇹" };

let previewReqId = 0;
let barcodeReqId = 0;

const DEFAULTS_KEY = "cnh-label-defaults-v2";
const TWEAKS_KEY = "cnh-label-tweaks-v1";

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

async function getJSON(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function loadDefaults() {
  try { return JSON.parse(localStorage.getItem(DEFAULTS_KEY) || "{}"); }
  catch { return {}; }
}

const state = {
  lines: { en: "", it: "", fr: "", de: "", es: "", pt: "" },
  // геометрия макета с сервера (layout.as_dict) — нужна только для
  // названий блоков и границ ползунка размера
  layout: null,
  // ручные правки: {ключ: {dx, dy, scale}} в миллиметрах макета
  tweaks: {},
  boxes: [],
  selected: null,
  angle: 0,            // поворот превью на экране, градусы по часовой
  printAngle: 90,      // угол, под которым картинка ложится на рулон
  pxPerMm: 96 / 25.4,  // уточняется замером в браузере
  dragging: false,
};

// ------------------------------------------------------------ инициализация
async function init() {
  const status = await getJSON("/api/status");
  state.layout = status.layout;
  state.tweaks = loadTweaks();

  buildLangRows();
  buildTweakRows();
  fillPrinters(status.printers);
  applyDefaults({ ...status.defaults, ...loadDefaults() });
  renderIndexBox(status);
  setStatusLine(status);

  measurePxPerMm();
  wireEvents();
  loadBarcode();
  updateLabelText();
  loadPreview();
}

function setStatusLine(status) {
  const bits = [];
  bits.push(status.csv_exists ? "CSV найден" : "CSV не найден");
  bits.push(status.index_ready ? "индекс готов" : "индекс не готов");
  bits.push(status.printers.length ? `принтеры: ${status.printers.join(", ")}` : "принтеры не найдены");
  $("status").textContent = bits.join(" · ");
}

function renderIndexBox(status) {
  const box = $("indexBox");
  if (!status.csv_exists) {
    box.classList.remove("hidden");
    $("indexText").textContent = `CSV не найден по пути ${status.csv}. Поиск по номеру недоступен, остальное работает.`;
    $("indexBuild").classList.add("hidden");
    return;
  }
  if (status.index_ready) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  $("indexText").textContent = "Индекс каталога не построен — поиск по номеру недоступен.";
}

function fillPrinters(list) {
  const sel = $("printer");
  sel.innerHTML = "";
  if (!list.length) {
    sel.appendChild(new Option("принтеры не найдены (проверьте CUPS)", ""));
    return;
  }
  for (const p of list) sel.appendChild(new Option(p, p));
  const saved = loadDefaults().printer;
  if (saved && list.includes(saved)) sel.value = saved;
}

function buildLangRows() {
  const wrap = $("langRows");
  wrap.innerHTML = "";
  for (const lang of LANGS) {
    const row = document.createElement("div");
    row.className = "lang-row";
    row.id = `row-${lang}`;
    row.innerHTML = `<div class="flag">${FLAGS[lang]}</div>
      <input id="lang-${lang}" spellcheck="false" data-lang="${lang}">`;
    wrap.appendChild(row);
  }
}

function applyDefaults(d) {
  $("madeIn").value = d.made_in || "Türkiye";
  $("pcs").value = d.pcs || "1";
  $("rotate180").checked = !!d.rotate180;
}

// -------------------------------------------------------------- наименование
function updateLabelText() {
  schedulePreview();
}

function labelPayload() {
  const order = ["en", ...LANGS];
  return {
    lines: order.map((l) => state.lines[l] || "").filter(Boolean),
    made_in: $("madeIn").value,
    pn: $("pn").value.trim(),
    barcode: $("barcode").value.trim(),
    pcs: $("pcs").value,
    rotate180: $("rotate180").checked,
    tweaks: state.tweaks,
  };
}

// ------------------------------------------------------------------ штрихкод
// Сам штрихкод рисует сервер вместе с этикеткой; здесь только проверяем,
// что строка вообще кодируется в Code 128, и показываем это пользователю.
const scheduleBarcode = debounce(loadBarcode, 250);

async function loadBarcode() {
  const text = $("barcode").value.trim();
  const myId = ++barcodeReqId;
  if (!text) { $("bcStatus").textContent = ""; return; }
  try {
    const data = await getJSON(`/api/barcode?text=${encodeURIComponent(text)}`);
    if (myId !== barcodeReqId) return;
    $("bcStatus").textContent = `Code 128 · ${data.modules} модулей`;
    $("bcStatus").classList.remove("err");
  } catch (e) {
    if (myId !== barcodeReqId) return;
    $("bcStatus").textContent = "Не удалось закодировать: " + e.message;
    $("bcStatus").classList.add("err");
  }
  schedulePreview();
}

// --------------------------------------------------------------- перевод
function setLangValues(t) {
  state.lines.en = t.en || state.lines.en;
  $("descEn").value = state.lines.en;
  for (const lang of LANGS) {
    const el = $(`lang-${lang}`);
    const row = $(`row-${lang}`);
    if (!row.classList.contains("edited")) {
      state.lines[lang] = t[lang] || "";
      el.value = state.lines[lang];
    }
    row.classList.remove("pending", "failed");
    const src = (t.source || {})[lang];
    if (t.errors && t.errors[lang]) {
      row.classList.add("failed");
      row.title = t.errors[lang];
    } else {
      row.title = src === "cache" ? "из кэша" : "переведено сейчас";
    }
  }
  updateLabelText();
}

function markPending() {
  for (const lang of LANGS) $(`row-${lang}`).classList.add("pending");
}

const doTranslate = debounce(async (refresh) => {
  const text = $("descEn").value.trim();
  state.lines.en = text.toUpperCase();
  if (!text) { for (const l of LANGS) { state.lines[l] = ""; $(`lang-${l}`).value = ""; } updateLabelText(); return; }
  markPending();
  $("trStatus").textContent = "Переводим…";
  $("trStatus").classList.remove("err");
  try {
    const t = await getJSON("/api/translate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, refresh: !!refresh }),
    });
    setLangValues(t);
    const failed = LANGS.filter((l) => t.errors && t.errors[l]);
    $("trStatus").textContent = failed.length
      ? `Не удалось перевести: ${failed.join(", ")} — впишите вручную`
      : "Переведено (MyMemory API)";
    if (failed.length) $("trStatus").classList.add("err");
  } catch (e) {
    for (const lang of LANGS) $(`row-${lang}`).classList.remove("pending");
    $("trStatus").textContent = "Ошибка перевода: " + e.message + " — впишите вручную";
    $("trStatus").classList.add("err");
  }
}, 500);

// ------------------------------------------------------------- поиск детали
async function findPart() {
  const pn = $("pn").value.trim();
  $("partInfo").textContent = "";
  $("partInfo").classList.remove("err");
  if (!pn) return;
  $("partInfo").textContent = "Ищем…";
  try {
    const data = await getJSON(`/api/part?pn=${encodeURIComponent(pn)}&translate=1`);
    if (!data.found) {
      $("partInfo").textContent = data.suggest && data.suggest.length
        ? "Не найдено. Похожие номера: " + data.suggest.join(", ")
        : "Каталожный номер не найден в CSV.";
      $("partInfo").classList.add("err");
      return;
    }
    const f = data.fields;
    $("pn").value = f.pn || pn;
    if ($("bcSame").checked) $("barcode").value = f.barcode || f.pn || pn;
    let info = f.desc_ru ? `RU: ${f.desc_ru}` : "";
    if (f.brand) info += (info ? " · " : "") + `бренд ${f.brand}`;
    if (f.status) info += (info ? " · " : "") + f.status;
    if (f.replacements) info += (info ? " · " : "") + `замены: ${f.replacements}`;
    $("partInfo").textContent = info || "Найдено.";

    if (f.desc_en) {
      $("descEn").value = f.desc_en;
      if (data.translation) setLangValues(data.translation);
      else doTranslate(false);
    }
    loadBarcode();
  } catch (e) {
    $("partInfo").textContent = "Ошибка: " + e.message;
    $("partInfo").classList.add("err");
  }
}

const suggestPn = debounce(async () => {
  const q = $("pn").value.trim();
  const dl = $("pnList");
  if (!q) { dl.innerHTML = ""; return; }
  try {
    const data = await getJSON(`/api/suggest?q=${encodeURIComponent(q)}&limit=12`);
    dl.innerHTML = (data.items || []).map((v) => `<option value="${v}">`).join("");
  } catch { /* каталог недоступен — тихо игнорируем */ }
}, 200);

// ============================================================== превью печати
const schedulePreview = debounce(() => loadPreview(), 300);
const scheduleDragPreview = debounce(() => loadPreview(2), 110);

async function loadPreview(scale) {
  const myId = ++previewReqId;
  try {
    const data = await getJSON("/api/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: labelPayload(), scale: scale || 4 }),
    });
    if (myId !== previewReqId) return;
    $("exactImg").src = data.png;
    state.printAngle = data.print_angle;
    state.boxes = data.boxes || [];
    applyBoxes();
    showPreviewError("");
  } catch (e) {
    if (myId !== previewReqId) return;
    // Молча гасить нельзя: тогда на месте превью просто остаётся пустая
    // рамка и непонятно, что сломалось.
    showPreviewError(/HTTP 404/.test(e.message)
      ? "Превью не отвечает: сервер запущен старой версией. Перезапустите "
        + "приложение (scripts/launch.sh restart)."
      : "Превью не построилось: " + e.message);
  }
}

function showPreviewError(text) {
  const box = $("previewErr");
  box.textContent = text;
  box.classList.toggle("hidden", !text);
}

// ---------------------------------------------------------- поворот и масштаб
function measurePxPerMm() {
  // Реальный размер миллиметра в CSS-пикселях: нужен, чтобы перевести
  // сдвиг мыши на экране в миллиметры макета.
  const probe = document.createElement("div");
  probe.style.cssText = "position:absolute;visibility:hidden;width:100mm;height:0";
  document.body.appendChild(probe);
  const w = probe.getBoundingClientRect().width;
  probe.remove();
  if (w > 0) state.pxPerMm = w / 100;
}

function zoomFactor() {
  return parseFloat($("zoom").value) / 5;             // 5 на ползунке = 100%
}

function layoutStage() {
  // #labelWrap — прямоугольник 72x100мм; поворачиваем и масштабируем его
  // целиком, а #viewport подгоняем под габарит повёрнутого прямоугольника,
  // чтобы этикетка не наезжала на края и не обрезалась.
  const z = zoomFactor();
  const a = (state.angle * Math.PI) / 180;
  const w = 72 * state.pxPerMm * z;
  const h = 100 * state.pxPerMm * z;
  const bw = Math.abs(w * Math.cos(a)) + Math.abs(h * Math.sin(a));
  const bh = Math.abs(w * Math.sin(a)) + Math.abs(h * Math.cos(a));

  const vp = $("viewport");
  vp.style.width = `${bw}px`;
  vp.style.height = `${bh}px`;

  const wrap = $("labelWrap");
  wrap.style.left = `${(bw - 72 * state.pxPerMm) / 2}px`;
  wrap.style.top = `${(bh - 100 * state.pxPerMm) / 2}px`;
  wrap.style.transform = `rotate(${state.angle}deg) scale(${z})`;

  $("angle").value = String(Math.round(state.angle));
  $("angleVal").textContent = `${Math.round(state.angle)}°`;
}

function setAngle(deg) {
  state.angle = ((Math.round(deg) % 360) + 360) % 360;
  layoutStage();
}

// -------------------------------------------------- рамки-манипуляторы блоков
function applyBoxes() {
  if (state.dragging) return;          // не ломаем перетаскивание на лету
  const overlay = $("overlay");
  overlay.innerHTML = "";
  for (const b of state.boxes) {
    const el = document.createElement("div");
    el.className = "hit" + (state.selected === b.key ? " sel" : "");
    el.dataset.key = b.key;
    el.title = elementName(b.key) + " — тяните, чтобы подвинуть";
    el.style.left = `${b.x}mm`;
    el.style.top = `${b.y}mm`;
    el.style.width = `${b.w}mm`;
    el.style.height = `${b.h}mm`;
    el.addEventListener("pointerdown", startDrag);
    overlay.appendChild(el);
  }
}

function elementName(key) {
  const names = (state.layout && state.layout.element_names) || {};
  return names[key] || key;
}

function tweakOf(key) {
  if (!state.tweaks[key]) state.tweaks[key] = { dx: 0, dy: 0, scale: 1 };
  return state.tweaks[key];
}

function startDrag(ev) {
  if (!$("editMode").checked) return;
  ev.preventDefault();
  const el = ev.currentTarget;
  const key = el.dataset.key;
  select(key);

  const t = tweakOf(key);
  const startX = ev.clientX, startY = ev.clientY;
  const baseDx = t.dx, baseDy = t.dy;
  const a = (state.angle * Math.PI) / 180;
  const cos = Math.cos(a), sin = Math.sin(a);
  const k = state.pxPerMm * zoomFactor();

  state.dragging = true;
  el.classList.add("drag");
  el.setPointerCapture(ev.pointerId);

  const move = (e) => {
    const sx = e.clientX - startX, sy = e.clientY - startY;
    // экранный сдвиг -> миллиметры макета: обратный поворот на тот же угол
    t.dx = baseDx + (sx * cos + sy * sin) / k;
    t.dy = baseDy + (-sx * sin + sy * cos) / k;
    // мгновенная реакция рамки, картинка догонит следующим ответом сервера
    el.style.transform = `translate(${t.dx - baseDx}mm, ${t.dy - baseDy}mm)`;
    updateTweakRow(key);
    scheduleDragPreview();
  };
  const up = () => {
    el.removeEventListener("pointermove", move);
    el.removeEventListener("pointerup", up);
    el.removeEventListener("pointercancel", up);
    el.classList.remove("drag");
    state.dragging = false;
    saveTweaks();
    loadPreview();                    // финальная картинка в полном качестве
  };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", up);
}

function select(key) {
  state.selected = key;
  for (const el of document.querySelectorAll(".hit"))
    el.classList.toggle("sel", el.dataset.key === key);
  for (const row of document.querySelectorAll(".tweak-row"))
    row.classList.toggle("sel", row.dataset.key === key);
}

function nudge(dx, dy) {
  if (!state.selected) return;
  const t = tweakOf(state.selected);
  t.dx += dx;
  t.dy += dy;
  updateTweakRow(state.selected);
  saveTweaks();
  schedulePreview();
}

// ------------------------------------------------------- панель правки макета
function buildTweakRows() {
  const wrap = $("tweakRows");
  const keys = (state.layout && state.layout.elements) || [];
  const min = (state.layout && state.layout.scale_min) || 0.3;
  const max = (state.layout && state.layout.scale_max) || 2.5;
  wrap.innerHTML = "";
  for (const key of keys) {
    const row = document.createElement("div");
    row.className = "tweak-row";
    row.dataset.key = key;
    row.innerHTML = `
      <span class="name">${elementName(key)}</span>
      <input type="range" class="sc" min="${min}" max="${max}" step="0.01" value="1">
      <span class="val">×1.00</span>
      <span class="off"></span>
      <button class="reset" title="вернуть блок на место">⟲</button>`;
    row.querySelector(".sc").addEventListener("input", (e) => {
      tweakOf(key).scale = parseFloat(e.target.value);
      select(key);
      updateTweakRow(key);
      saveTweaks();
      schedulePreview();
    });
    row.querySelector(".name").addEventListener("click", () => select(key));
    row.querySelector(".reset").addEventListener("click", () => {
      state.tweaks[key] = { dx: 0, dy: 0, scale: 1 };
      updateTweakRow(key);
      saveTweaks();
      schedulePreview();
    });
    wrap.appendChild(row);
    updateTweakRow(key);
  }
}

function updateTweakRow(key) {
  const row = document.querySelector(`.tweak-row[data-key="${key}"]`);
  if (!row) return;
  const t = tweakOf(key);
  row.querySelector(".sc").value = String(t.scale);
  row.querySelector(".val").textContent = "×" + t.scale.toFixed(2);
  const moved = Math.abs(t.dx) > 0.005 || Math.abs(t.dy) > 0.005;
  row.querySelector(".off").textContent = moved ? `${mm(t.dx)} / ${mm(t.dy)} мм` : "";
  row.classList.toggle("changed", moved || Math.abs(t.scale - 1) > 0.005);
}

function mm(v) {
  const r = Math.abs(v) < 0.05 ? 0 : v;              // без «-0.0» у нуля
  return (r >= 0 ? "+" : "") + r.toFixed(1);
}

function loadTweaks() {
  const base = (state.layout && state.layout.tweaks) || {};
  const fresh = {};
  for (const key of Object.keys(base)) fresh[key] = { ...base[key] };
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(TWEAKS_KEY) || "{}"); }
  catch { saved = {}; }
  for (const key of Object.keys(fresh)) {
    const s = saved[key];
    if (!s) continue;
    fresh[key] = {
      dx: Number(s.dx) || 0,
      dy: Number(s.dy) || 0,
      scale: Number(s.scale) > 0 ? Number(s.scale) : 1,
    };
  }
  return fresh;
}

function saveTweaks() {
  localStorage.setItem(TWEAKS_KEY, JSON.stringify(state.tweaks));
}

function resetTweaks() {
  for (const key of Object.keys(state.tweaks))
    state.tweaks[key] = { dx: 0, dy: 0, scale: 1 };
  for (const key of Object.keys(state.tweaks)) updateTweakRow(key);
  saveTweaks();
  loadPreview();
}

// ------------------------------------------------------------------- печать
async function doPrint() {
  const printer = $("printer").value;
  if (!printer) { $("printStatus").textContent = "Выберите принтер."; $("printStatus").classList.add("err"); return; }
  $("printStatus").textContent = "Печатаем…";
  $("printStatus").classList.remove("err");
  try {
    const res = await getJSON("/api/print", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ printer, copies: $("copies").value, label: labelPayload() }),
    });
    $("printStatus").textContent = `Отправлено в ${printer} (${res.copies} шт.)`;
  } catch (e) {
    $("printStatus").textContent = "Ошибка печати: " + e.message;
    $("printStatus").classList.add("err");
  }
}

async function savePng() {
  const data = encodeURIComponent(JSON.stringify(labelPayload()));
  const a = document.createElement("a");
  a.href = `/api/preview.png?scale=6&data=${data}`;
  a.download = `label_${($("pn").value || "label").trim()}.png`;
  a.click();
}

async function saveTspl() {
  try {
    const res = await getJSON("/api/tspl", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: labelPayload(), copies: $("copies").value }),
    });
    $("printStatus").textContent = `TSPL сохранён: ${res.path} (${res.bytes} байт)`;
  } catch (e) {
    $("printStatus").textContent = "Ошибка сохранения TSPL: " + e.message;
    $("printStatus").classList.add("err");
  }
}

function saveDefaults() {
  const d = {
    made_in: $("madeIn").value, pcs: $("pcs").value,
    rotate180: $("rotate180").checked, printer: $("printer").value,
  };
  localStorage.setItem(DEFAULTS_KEY, JSON.stringify(d));
  $("printStatus").textContent = "Значения по умолчанию сохранены в этом браузере.";
}

async function buildIndex() {
  $("indexBuild").disabled = true;
  $("indexBar").classList.remove("hidden");
  await getJSON("/api/index/build", { method: "POST" }).catch(() => {});
  const poll = setInterval(async () => {
    const s = await getJSON("/api/status");
    const idx = s.index;
    if (idx.total) $("indexBar").value = Math.round((idx.done / idx.total) * 100);
    if (!idx.running) {
      clearInterval(poll);
      $("indexBuild").disabled = false;
      renderIndexBox(s);
      setStatusLine(s);
    }
  }, 1000);
}

// ------------------------------------------------------------------- события
function wireEvents() {
  $("find").addEventListener("click", findPart);
  $("pn").addEventListener("keydown", (e) => { if (e.key === "Enter") findPart(); });
  $("pn").addEventListener("input", () => {
    suggestPn();
    if ($("bcSame").checked) $("barcode").value = $("pn").value.trim();
    scheduleBarcode();
    schedulePreview();
  });

  $("descEn").addEventListener("input", () => doTranslate(false));
  $("retranslate").addEventListener("click", () => doTranslate(true));
  $("langRows").addEventListener("input", (e) => {
    if (e.target.dataset.lang) {
      $(`row-${e.target.dataset.lang}`).classList.add("edited");
      state.lines[e.target.dataset.lang] = e.target.value;
      updateLabelText();
    }
  });

  $("barcode").addEventListener("input", () => { $("bcSame").checked = false; scheduleBarcode(); });
  $("bcSame").addEventListener("change", () => {
    if ($("bcSame").checked) { $("barcode").value = $("pn").value.trim(); loadBarcode(); }
  });

  for (const id of ["madeIn", "pcs"]) $(id).addEventListener("input", updateLabelText);
  $("rotate180").addEventListener("change", schedulePreview);

  // поворот превью
  $("rotCw").addEventListener("click", () => setAngle(snap90(state.angle + 90)));
  $("rotCcw").addEventListener("click", () => setAngle(snap90(state.angle - 90)));
  $("angle").addEventListener("input", (e) => setAngle(parseFloat(e.target.value)));
  $("angleRead").addEventListener("click", () => setAngle(0));
  $("anglePrint").addEventListener("click", () => setAngle(state.printAngle));
  $("zoom").addEventListener("input", layoutStage);
  window.addEventListener("resize", layoutStage);

  // правка макета
  $("editMode").addEventListener("change", () => {
    $("overlay").classList.toggle("off", !$("editMode").checked);
  });
  $("resetTweaks").addEventListener("click", resetTweaks);
  document.addEventListener("keydown", (e) => {
    if (!state.selected || !$("editMode").checked) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
    const step = e.shiftKey ? 0.1 : 0.5;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0],
                    ArrowUp: [0, -step], ArrowDown: [0, step] };
    const m = moves[e.key];
    if (!m) return;
    e.preventDefault();
    // стрелки двигают блок по экрану, а не по макету: если превью
    // повёрнуто, «вправо» для глаза и «вправо» в макете — разные оси
    const a = (state.angle * Math.PI) / 180;
    nudge(m[0] * Math.cos(a) + m[1] * Math.sin(a),
          -m[0] * Math.sin(a) + m[1] * Math.cos(a));
  });

  $("print").addEventListener("click", doPrint);
  $("printBrowser").addEventListener("click", () => window.print());
  $("savePng").addEventListener("click", savePng);
  $("saveTspl").addEventListener("click", saveTspl);
  $("saveDefaults").addEventListener("click", saveDefaults);
  $("indexBuild").addEventListener("click", buildIndex);

  layoutStage();
}

function snap90(deg) {
  return Math.round(deg / 90) * 90;
}

init().catch((e) => { $("status").textContent = "Ошибка инициализации: " + e.message; });
