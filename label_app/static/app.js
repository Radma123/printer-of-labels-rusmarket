// Приложение этикеток CNH 72x100 (портрет — макет Claude Design
// Label 100x72.dc.html). Один файл, без сборки, без npm.
//
// Разметка превью (index.html/.page) — прямая копия структуры и
// inline-стилей исходного макета, поэтому DOM-превью строит сам браузер
// (реальный flexbox), без ручного позиционирования в JS. Штрихкод считает
// сервер (barcode.py) — та же раскладка, что и у PNG/печати.

const $ = (id) => document.getElementById(id);

const LANGS = ["it", "fr", "de", "es", "pt"];
const FLAGS = { en: "🇬🇧", it: "🇮🇹", fr: "🇫🇷", de: "🇩🇪", es: "🇪🇸", pt: "🇵🇹" };

let barcodeReqId = 0;
let previewReqId = 0;
let BARCODE_ROW = { height_px: 73, bar_height_px: 58 };   // перезаписывается из /api/status

const DEFAULTS_KEY = "cnh-label-defaults-v2";

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
};

// ------------------------------------------------------------ инициализация
async function init() {
  const status = await getJSON("/api/status");
  if (status.layout && status.layout.barcode_row) BARCODE_ROW = status.layout.barcode_row;

  buildLangRows();
  fillPrinters(status.printers);
  applyDefaults({ ...status.defaults, ...loadDefaults() });
  renderIndexBox(status);
  setStatusLine(status);

  wireEvents();
  scheduleBarcode();
  updateLabelText();
  applyZoom();
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
  const d = $("descBox");
  d.innerHTML = "";
  const order = ["en", ...LANGS];
  for (const lang of order) {
    const text = (state.lines[lang] || "").trim();
    if (!text) continue;
    const row = document.createElement("div");
    row.className = "desc-line";
    row.textContent = text;
    d.appendChild(row);
  }
  $("madeInEl").textContent = `Made in ${$("madeIn").value}`.trim();
  $("pcsVal").textContent = $("pcs").value;
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
  };
}

// ------------------------------------------------------------------ штрихкод
const scheduleBarcode = debounce(loadBarcode, 250);

async function loadBarcode() {
  const text = $("barcode").value.trim();
  $("pnEl").textContent = $("pn").value.trim();
  const svg = $("bcSvg");
  const myId = ++barcodeReqId;
  if (!text) { svg.innerHTML = ""; $("bcStatus").textContent = ""; return; }
  try {
    const data = await getJSON(`/api/barcode?text=${encodeURIComponent(text)}`);
    if (myId !== barcodeReqId) return;
    drawBarcodeSvg(svg, data.widths);
    $("bcStatus").textContent = `Code 128 · ${data.modules} модулей`;
    $("bcStatus").classList.remove("err");
  } catch (e) {
    if (myId !== barcodeReqId) return;
    svg.innerHTML = "";
    $("bcStatus").textContent = "Не удалось закодировать: " + e.message;
    $("bcStatus").classList.add("err");
  }
  schedulePreview();
}

function drawBarcodeSvg(svg, widths) {
  // Бары прижаты к низу ряда (align-items:flex-end); повторяем через
  // viewBox: рисуем полосы только в нижней части общей высоты. Размеры —
  // из layout.py (BARCODE_ROW), чтобы не разъезжались с сервером.
  const total = widths.reduce((a, b) => a + b, 0) || 1;
  const rowH = BARCODE_ROW.height_px, barH = BARCODE_ROW.bar_height_px, barTop = rowH - barH;
  svg.setAttribute("viewBox", `0 0 ${total} ${rowH}`);
  let x = 0, dark = true, rects = "";
  for (const w of widths) {
    if (dark) rects += `<rect x="${x}" y="${barTop}" width="${w}" height="${barH}" fill="#000"/>`;
    x += w; dark = !dark;
  }
  svg.innerHTML = rects;
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

// -------------------------------------------------------------- точный preview
const schedulePreview = debounce(loadExactPreview, 350);

async function loadExactPreview() {
  if (!$("exact").checked) return;
  const myId = ++previewReqId;
  const data = encodeURIComponent(JSON.stringify(labelPayload()));
  const img = $("exactImg");
  try {
    const res = await fetch(`/api/preview.png?scale=4&data=${data}`);
    if (!res.ok) throw new Error("сервер вернул " + res.status);
    const blob = await res.blob();
    if (myId !== previewReqId) return;
    img.src = URL.createObjectURL(blob);
  } catch (e) {
    if (myId !== previewReqId) return;
    console.warn("превью печати недоступно:", e);
  }
}

function toggleExact() {
  const on = $("exact").checked;
  $("exactImg").classList.toggle("hidden", !on);
  $("label").classList.toggle("hidden", on);
  // Точное превью — уже повёрнутая (100x72, альбомная) картинка, как
  // уходит на печать; сам макет (#label) остаётся портретным (72x100).
  $("labelWrap").classList.toggle("landscape", on);
  if (on) loadExactPreview();
}

// ------------------------------------------------------------------- зум
function applyZoom() {
  const factor = parseFloat($("zoom").value) / 5;    // 5 = 100%
  $("labelWrap").style.transform = `scale(${factor})`;
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
    loadBarcode();
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

  $("barcode").addEventListener("input", () => { $("bcSame").checked = false; loadBarcode(); });
  $("bcSame").addEventListener("change", () => {
    if ($("bcSame").checked) { $("barcode").value = $("pn").value.trim(); loadBarcode(); }
  });

  for (const id of ["madeIn", "pcs"]) $(id).addEventListener("input", updateLabelText);
  $("rotate180").addEventListener("change", schedulePreview);

  $("exact").addEventListener("change", toggleExact);
  $("zoom").addEventListener("input", applyZoom);

  $("print").addEventListener("click", doPrint);
  $("printBrowser").addEventListener("click", () => window.print());
  $("savePng").addEventListener("click", savePng);
  $("saveTspl").addEventListener("click", saveTspl);
  $("saveDefaults").addEventListener("click", saveDefaults);
  $("indexBuild").addEventListener("click", buildIndex);
}

init().catch((e) => { $("status").textContent = "Ошибка инициализации: " + e.message; });
