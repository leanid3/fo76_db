// Общие помощники для страниц
const RU = window.FO76_RU || {};
// Обёртка над Tabulator для всех таблиц:
// - узкий экран (телефон, PWA): fitColumns сжимает колонки в ширину экрана и строки вытягиваются в высоту, поэтому там
//   fitDataFill (колонки своей ширины, прокрутка вбок);
// - height: "calc(100vh - Npx)" заменяется расчётом от реального положения таблицы (панель фильтров переносится на
//   несколько строк, на телефоне 100vh включает адресную строку) и пересчитывается при изменении окна;
// - placeholder по умолчанию и сообщение при ошибке загрузки данных (раньше таблица оставалась пустой без объяснений).
if (window.Tabulator) {
  const narrow = window.matchMedia("(max-width: 720px)");
  window.Tabulator = class extends window.Tabulator {
    constructor(el, opts = {}) {
      opts = { ...opts };
      if (narrow.matches && opts.layout === "fitColumns") opts.layout = "fitDataFill";
      const auto = typeof opts.height === "string" && /^calc\(100vh/.test(opts.height);
      const node = typeof el === "string" ? document.querySelector(el) : el;
      const fit = () => Math.max(260, Math.floor(window.innerHeight - node.getBoundingClientRect().top - 24));
      if (auto && node) opts.height = fit();
      if (opts.placeholder === undefined) opts.placeholder = "Ничего не найдено — измените фильтры";
      super(el, opts);
      if (auto && node) {
        let t;
        window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => this.setHeight(fit()), 120); });
      }
      this.on("dataLoadError", err => {
        const msg = (err && err.message) || String(err || "");
        toast("Не удалось загрузить данные" + (msg ? ": " + msg : ""), "err");
        this.alert("Не удалось загрузить данные — обновите страницу", "error");
      });
    }
  };
}
// Страница, у которой пункт меню активен, получает aria-current
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("nav a.active").forEach(a => a.setAttribute("aria-current", "page")));
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.headers.get("X-FO76-Cache")) { const b = document.getElementById("offline"); if (b) b.hidden = false; }
  if (!r.ok) {
    const t = await r.text();
    let msg = t;
    try { const d = JSON.parse(t).detail; msg = typeof d === "string" ? d : JSON.stringify(d); } catch (e) { }
    throw new Error(msg);
  }
  return r.json();
}
function post(url, body, method = "POST") {
  return api(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
// ---------- Сообщения и диалоги (вместо alert/confirm/prompt: те блокируют окно, не стилизуются и плохо работают в десктоп-окне) ----------
function toast(msg, kind = "info", ms) {
  let box = document.getElementById("toasts");
  if (!box) {
    box = document.createElement("div"); box.id = "toasts"; box.setAttribute("aria-live", "polite");
    document.body.append(box);
  }
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg;
  if (kind === "err") t.setAttribute("role", "alert");
  t.onclick = () => t.remove();
  box.append(t);
  setTimeout(() => t.remove(), ms || (kind === "err" ? 9000 : 4500));
}
// Окно с вопросом: input — строка ввода (def — значение по умолчанию), options — выпадающий список [{value, label}].
// Результат: true/false (вопрос), строка (ввод или выбранное значение), null (отмена).
function uiDialog({ text, input = false, def = "", options = null, ok = "OK", cancel = "Отмена", danger = false, alertOnly = false }) {
  return new Promise(resolve => {
    const d = document.createElement("dialog"); d.className = "uidlg";
    const p = document.createElement("p"); p.textContent = text; d.append(p);
    let field = null;
    if (options) {
      field = document.createElement("select");
      for (const o of options) field.add(new Option(o.label, o.value));
    } else if (input) {
      field = document.createElement("input"); field.value = def;
    }
    if (field) { field.setAttribute("aria-label", text.split("\n")[0]); d.append(field); }
    const row = document.createElement("div"); row.className = "uidlg-btns";
    const bOk = document.createElement("button"); bOk.textContent = ok; bOk.className = danger ? "danger" : "primary";
    row.append(bOk);
    let bNo = null;
    if (!alertOnly) { bNo = document.createElement("button"); bNo.textContent = cancel; row.prepend(bNo); }
    d.append(row);
    let result = alertOnly ? true : null;
    // resolve не ждёт события close: в скрытой вкладке оно откладывается; Esc закрывает окно штатно (close → отмена)
    const finish = () => { if (d.isConnected) { d.remove(); resolve(result); } };
    bOk.onclick = () => { result = field ? field.value : true; if (d.open) d.close(); finish(); };
    if (bNo) bNo.onclick = () => { if (d.open) d.close(); finish(); };
    if (field) field.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); bOk.click(); } };
    d.addEventListener("close", finish);
    document.body.append(d);
    d.showModal();
    (field || (danger && bNo) || bOk).focus();
  });
}
const uiConfirm = (text, opts = {}) => uiDialog({ text, ...opts }).then(v => v === true);
const uiPrompt = (text, def = "") => uiDialog({ text, input: true, def });
// Блокирует кнопку на время действия: повторный клик не запустит его второй раз
async function busy(btn, fn) {
  if (btn.disabled) return;
  btn.disabled = true;
  try { return await fn(); } finally { btn.disabled = false; }
}
function debounce(fn, ms = 180) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
// Поле поиска получает фокус сразу только там, где есть мышь/клавиатура: на телефоне это открыло бы экранную клавиатуру
document.addEventListener("DOMContentLoaded", () => {
  if (window.matchMedia("(pointer: fine)").matches) document.querySelector("input[data-autofocus]")?.focus();
});
function stars(n) { return n ? '<span class="stars">' + "★".repeat(n) + "</span>" : ""; }
function esc(s) { return (s ?? "").toString().replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function itemLink(cell) {
  const d = cell.getData(); const v = cell.getValue();
  return d.id ? `<a href="/item/${d.id}">${esc(v || d.name_en || d.name)}</a>` : esc(v || "");
}
// Поиск по нескольким полям сразу, с поддержкой * и ?
function textMatcher(q, fields) {
  q = q.trim().toLowerCase();
  if (!q) return () => true;
  const re = /[*?]/.test(q) ? new RegExp(q.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".")) : null;
  return d => fields.some(f => { const v = (d[f] ?? "").toString().toLowerCase(); return re ? re.test(v) : v.includes(q); });
}
async function loadNukes() {
  const el = document.getElementById("nukes"); if (!el) return;
  try {
    const d = await api("/api/nukes");
    if (!d.ALPHA) { el.textContent = ""; return; }
    el.innerHTML = `☢ Alpha <b>${d.ALPHA}</b> Bravo <b>${d.BRAVO}</b> Charlie <b>${d.CHARLIE}</b>`;
    el.title = "NukaCrypt, неделя с " + (d.date || "").slice(0, 10);
  } catch (e) { el.textContent = ""; }
}
document.addEventListener("DOMContentLoaded", loadNukes);

// ---------- Выбранный персонаж и изученные схемы ----------
function currentChar() {
  try { return localStorage.getItem("fo76.char") || ""; } catch (e) { return ""; }
}
// ?char=<id> в адресе выбирает персонажа (ссылки «не изучено у …»)
(() => {
  const ch = new URLSearchParams(location.search).get("char");
  if (ch !== null) try { localStorage.setItem("fo76.char", ch); } catch (e) { }
})();
let KNOWN = {};  // {FormID схемы: "auto" | "manual"} у выбранного персонажа
async function loadKnown() {
  const ch = currentChar();
  KNOWN = ch ? await api("/api/known?character_id=" + ch) : {};
  return KNOWN;
}
// plans — FormID схем через запятую (у самой схемы — она сама). null — у предмета нет схемы.
function knownState(plans) {
  if (!plans || !currentChar()) return null;
  const st = plans.split(",").map(f => KNOWN[f]);
  return st.includes("auto") ? "auto" : st.includes("manual") ? "manual" : "no";
}
function knownBadge(plans) {
  const s = knownState(plans);
  if (s === null) return "";
  if (s === "auto") return '<span class="yes" title="схема была в инвентаре с пометкой «изучено»">✔ авто</span>';
  if (s === "manual") return '<span class="yes kb" tabindex="0" role="button" title="отмечено вручную; клик — снять">✔</span>';
  return '<span class="no kb" tabindex="0" role="button" title="клик — отметить изученной">—</span>';
}
// Клик по отметке: переключить ручную отметку (только если схема одна — иначе непонятно, какую отмечать)
async function toggleKnown(plans) {
  const ch = currentChar();
  if (!ch || !plans || plans.includes(",")) return false;
  const s = knownState(plans);
  if (s === "auto") return false;
  const known = s !== "manual";
  await post("/api/known", { character_id: +ch, formid: plans, known });
  if (known) KNOWN[plans] = "manual"; else delete KNOWN[plans];
  return true;
}
// Таблица Tabulator: колонка «Изучено» по полю с FormID схем
function knownColumn(field = "plans", extra = {}) {
  return {
    title: "Изучено", field, width: 90, hozAlign: "center",
    headerTooltip: "Изучена ли схема у персонажа, выбранного в шапке",
    sorter: (a, b, ra, rb) => ["auto", "manual", "no", null].indexOf(knownState(a)) - ["auto", "manual", "no", null].indexOf(knownState(b)),
    formatter: c => knownBadge(c.getValue()),
    cellClick: async (e, cell) => { if (await toggleKnown(cell.getValue())) cell.getRow().reformat(); },
    ...extra,
  };
}
document.addEventListener("DOMContentLoaded", () => {
  const sel = document.getElementById("who"); if (!sel) return;
  sel.value = currentChar();
  if (sel.value !== currentChar()) sel.value = "";
  sel.addEventListener("change", async () => {
    try { localStorage.setItem("fo76.char", sel.value); } catch (e) { }
    await loadKnown();
    document.dispatchEvent(new CustomEvent("charchange"));
  });
});

// ---------- Таблицы: колонки, экспорт, сохранённые поиски ----------
const STORAGE_OK = (() => { try { localStorage.setItem("fo76.t", "1"); localStorage.removeItem("fo76.t"); return true; } catch (e) { return false; } })();
// Выпадающий список «Колонки»: показать/скрыть (порядок — перетаскиванием заголовков)
function addColumnPicker(table, toolbar) {
  const wrap = document.createElement("span"); wrap.className = "colpick";
  const b = document.createElement("button"); b.textContent = "☰ Колонки"; b.title = "Показать или скрыть колонки. Порядок меняется перетаскиванием заголовка";
  const box = document.createElement("div"); box.className = "colpick-box card"; box.hidden = true;
  b.onclick = e => {
    e.stopPropagation();
    box.innerHTML = "";
    for (const col of table.getColumns()) {
      const title = col.getDefinition().title; if (!title) continue;
      const l = document.createElement("label"); l.className = "chk";
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = col.isVisible();
      cb.onchange = () => cb.checked ? col.show() : col.hide();
      l.append(cb, " " + title.replace(/<[^>]*>.*$/s, "")); box.append(l);
    }
    const all = document.createElement("button"); all.textContent = "Показать все";
    all.onclick = () => { for (const col of table.getColumns()) col.show(); box.querySelectorAll("input").forEach(cb => cb.checked = true); };
    const reset = document.createElement("button"); reset.textContent = "Сбросить вид"; reset.title = "Вернуть колонки, их ширину, порядок и сортировку по умолчанию";
    reset.onclick = () => {
      const id = table.options.persistenceID;
      try { for (const k of Object.keys(localStorage)) if (k.startsWith(`tabulator-${id}-`)) localStorage.removeItem(k); } catch (e) { }
      location.reload();
    };
    box.append(all, reset);
    box.hidden = !box.hidden;
  };
  box.onclick = e => e.stopPropagation();
  document.addEventListener("click", () => box.hidden = true);
  wrap.append(b, box);
  toolbar.insertBefore(wrap, toolbar.querySelector(".counter"));
}
// Общие опции таблиц: перетаскивание колонок, меню видимости, запоминание раскладки (если доступно хранилище)
// Версия сохранённого вида: при смене колонок увеличить — старые сохранённые ширины/порядок/видимость не применяются
const TABLE_VIEW_VERSION = 1;
function tableOpts(id, opts) {
  const base = { movableColumns: true, columnDefaults: {} };
  if (STORAGE_OK) Object.assign(base, { persistence: { columns: ["width", "visible"], sort: true }, persistenceID: `${id}.v${TABLE_VIEW_VERSION}` });
  return { ...base, ...opts, columnDefaults: { ...base.columnDefaults, ...(opts.columnDefaults || {}) } };
}
// Кнопки выгрузки отфильтрованных строк (только видимые колонки)
function addExport(table, toolbar, name) {
  addColumnPicker(table, toolbar);
  const stamp = () => name + "-" + new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  for (const [fmt, title] of [["csv", "CSV"], ["json", "JSON"]]) {
    const b = document.createElement("button");
    b.textContent = "⭳ " + title; b.title = "Выгрузить отфильтрованные строки";
    b.onclick = () => table.download(fmt, `${stamp()}.${fmt}`, fmt === "csv" ? { bom: true, delimiter: ";" } : {});
    toolbar.insertBefore(b, toolbar.querySelector(".counter"));
  }
}
// Сохранённые поиски: параметры адресной строки страницы
async function addSavedSearches(toolbar, apply) {
  const sel = document.createElement("select");
  sel.title = "Сохранённые поиски";
  const page = location.pathname;
  async function fill() {
    const list = await api("/api/saved?page=" + encodeURIComponent(page));
    sel.innerHTML = '<option value="">★ Сохранённые…</option>'
      + list.map(s => `<option value="${s.id}" data-params="${esc(s.params)}">${esc(s.name)}</option>`).join("")
      + '<option value="+">＋ Сохранить текущий</option>' + (list.length ? '<option value="-">✕ Удалить выбранный…</option>' : "");
  }
  sel.onchange = async () => {
    const v = sel.value;
    if (v === "+") {
      const name = await uiPrompt("Название поиска");
      if (name) await post("/api/saved", { page, name, params: location.search.slice(1) });
      await fill();
    } else if (v === "-") {
      const names = [...sel.options].filter(o => o.dataset.params !== undefined);
      const id = await uiDialog({ text: "Какой поиск удалить?", options: names.map(o => ({ value: o.value, label: o.text })), ok: "Удалить", danger: true });
      if (id) await api("/api/saved/" + id, { method: "DELETE" });
      await fill();
    } else if (v) {
      const params = sel.selectedOptions[0].dataset.params;
      history.replaceState(null, "", "?" + params);
      apply(new URLSearchParams(params));
      sel.value = "";
    }
  };
  await fill();
  toolbar.insertBefore(sel, toolbar.querySelector(".counter"));
}
// Поля фильтров <-> адресная строка
// Последние фильтры страницы запоминаются в браузере (кроме текста поиска) и возвращаются, если открыть её без параметров
const REMEMBER_SKIP = ["q"];
const filtersKey = () => "fo76.filters." + location.pathname;
function readParams(ids, params) {
  if (!params) {
    params = new URLSearchParams(location.search);
    if (![...params.keys()].length && STORAGE_OK) {
      try { params = new URLSearchParams(localStorage.getItem(filtersKey()) || ""); } catch (e) { }
    }
  }
  for (const id of ids) {
    const el = document.getElementById(id), v = params.get(id);
    if (el.type === "checkbox") el.checked = v === "1"; else el.value = v ?? "";
  }
}
function writeParams(ids) {
  const u = new URLSearchParams();
  for (const id of ids) {
    const el = document.getElementById(id);
    const v = el.type === "checkbox" ? (el.checked ? "1" : "") : el.value;
    if (v) u.set(id, v);
  }
  history.replaceState(null, "", "?" + u);
  if (STORAGE_OK) {
    const keep = new URLSearchParams(u); for (const k of REMEMBER_SKIP) keep.delete(k);
    try { localStorage.setItem(filtersKey(), keep.toString()); } catch (e) { }
  }
}

// ---------- Автотеги (редкость, сезон, откуда) ----------
let ATAGS = {};  // {код: {label, color, group, group_ru}}
let ATAG_ORDER = [];
async function loadAutoTags() {
  const list = await api("/api/autotags");
  ATAG_ORDER = list.map(t => t.code);
  ATAGS = Object.fromEntries(list.map(t => [t.code, t]));
  return list;
}
function autoTagBadge(t) {
  return `<span class="tag atag atag-${esc(t.group)}" style="--c:${esc(t.color)}" title="${esc(t.group_ru)}">${esc(t.label)}</span>`;
}
function autoTagBadges(codes) {
  return (codes || []).filter(c => ATAGS[c]).sort((a, b) => ATAG_ORDER.indexOf(a) - ATAG_ORDER.indexOf(b))
    .map(c => autoTagBadge(ATAGS[c])).join("");
}
function autoTagLabels(codes) { return (codes || []).map(c => ATAGS[c] ? ATAGS[c].label : "").join(" "); }
// <optgroup> по группам; prefix — чтобы отличать от пользовательских тегов в одном списке
function autoTagOptions(prefix = "") {
  const groups = {};
  for (const c of ATAG_ORDER) (groups[ATAGS[c].group_ru] ??= []).push(ATAGS[c]);
  return Object.entries(groups).map(([g, ts]) => `<optgroup label="${esc(g)}">` +
    ts.map(t => `<option value="${esc(prefix + t.code)}">${esc(t.label)} (${t.used})</option>`).join("") + "</optgroup>").join("");
}

// ---------- Легендарные эффекты по звёздам и нужные роллы ----------
// Шаблон звезды: как textMatcher, плюс варианты через | (Bloodied|Furious). Совпадает с rolls.matcher на сервере.
function starMatcher(q) {
  const alts = (q || "").split("|").map(s => s.trim()).filter(Boolean).map(a => textMatcher(a, ["text", "en", "ru"]));
  return alts.length ? s => alts.some(m => m(s)) : null;
}
// «★★ Rapid · Стремительность — описание»; hits — номера звёзд, совпавших с хотелкой (подсвечиваются)
function slotsHtml(slots, hits = []) {
  return (slots || []).map(s => `<div class="legslot${hits.includes(s.star) ? " hit" : ""}">${"★".repeat(s.star)} ` +
    (s.en ? `<b>${esc(s.en)}</b>${s.ru ? " · " + esc(s.ru) : ""} — ` : "") + esc(s.text) + "</div>").join("");
}
const ROLL_GRADES = { god: ["Год-ролл", "god"], partial: ["Частично", "partial"], scrip: ["На скрип", "scrip"] };
function rollBadge(r) {
  if (!r) return "";
  const [label, cls] = ROLL_GRADES[r.grade];
  const tip = r.want ? `${r.want}: совпало ${r.hits.length} из ${r.need} (★ ${r.hits.join(", ")})` : "Ни одна звезда не совпала с хотелками этого типа";
  return `<span class="tag roll-${cls}" title="${esc(tip)}">${label}</span>` + (r.want ? ` <span class="small muted">${esc(r.want)}${r.grade === "partial" ? ` ${r.hits.length}/${r.need}` : ""}</span>` : "");
}
function rollText(r) { return r ? ROLL_GRADES[r.grade][0] + (r.want ? " — " + r.want : "") : ""; }

// PWA: service worker (только в безопасном контексте — localhost или HTTPS) и отметка «нет связи»
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(e => console.warn("service worker:", e));
}
function markOnline() { const el = document.getElementById("offline"); if (el) el.hidden = navigator.onLine; }
window.addEventListener("online", markOnline);
window.addEventListener("offline", markOnline);
document.addEventListener("DOMContentLoaded", markOnline);

// Клавиши раскладки Pip-Boy: Q / E — вкладки, A / D — разделы вкладки, «/» — строка поиска (вне полей ввода)
document.addEventListener("keydown", e => {
  if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || e.target.isContentEditable) return;
  const step = (sel, d) => {
    const a = [...document.querySelectorAll(sel)], i = a.findIndex(x => x.classList.contains("active"));
    if (a.length && (i >= 0 || d)) location.href = a[(Math.max(i, 0) + d + a.length) % a.length].href;
  };
  const k = e.key.toLowerCase();
  if (k === "/") { const q = document.querySelector("input[type=search]"); if (q) { e.preventDefault(); q.focus(); } return; }
  if (document.documentElement.dataset.layout !== "pipboy") return;
  const dir = { q: -1, e: 1, й: -1, у: 1 }[k], sub = { a: -1, d: 1, ф: -1, в: 1 }[k];  // русская раскладка: те же клавиши
  if (dir) step(".tabs-main a", dir); else if (sub) step(".tabs-sub a", sub);
});

// Клавиатура: элементы-«кнопки» внутри ячеек таблиц (.kb) нажимаются Enter/Пробелом
document.addEventListener("keydown", e => {
  if ((e.key === "Enter" || e.key === " ") && e.target.classList?.contains("kb")) { e.preventDefault(); e.target.click(); }
});
// Телефон: длинную панель фильтров (поиск + 3 и более списков/флажков) прячет кнопка «Фильтры»
document.addEventListener("DOMContentLoaded", () => {
  for (const tb of document.querySelectorAll(".toolbar")) {
    const search = tb.querySelector(":scope > input[type=search]");
    const rest = tb.querySelectorAll(":scope > select, :scope > label.chk");
    if (!search || rest.length < 3) continue;
    tb.classList.add("collapsible", "collapsed");
    const b = document.createElement("button"); b.type = "button"; b.className = "filters-toggle";
    b.setAttribute("aria-expanded", "false");
    const upd = () => {
      const on = [...rest].filter(x => x.matches("select") ? x.value : x.querySelector("input")?.checked).length;
      b.textContent = "Фильтры" + (on ? ` (${on})` : "") + (tb.classList.contains("collapsed") ? " ▾" : " ▴");
    };
    b.addEventListener("click", () => {
      const c = tb.classList.toggle("collapsed"); b.setAttribute("aria-expanded", String(!c)); upd();
    });
    tb.addEventListener("change", upd);
    search.after(b); upd();
  }
});

// Баннер «вышла новая версия»: /api/update спрашивает GitHub не чаще раза в 6 часов; «Скрыть» запоминает версию на сервере
document.addEventListener("DOMContentLoaded", async () => {
  try {
    const u = await api("/api/update");
    if (!u.available) return;
    const main = document.getElementById("main"); if (!main) return;
    const b = document.createElement("div"); b.className = "modwarn updnote"; b.setAttribute("role", "status");
    const t = document.createElement("span");
    t.append(Object.assign(document.createElement("b"), { textContent: `Вышла новая версия ${u.latest.tag}` }), ` (у вас ${u.current}). `);
    const a = Object.assign(document.createElement("a"), { href: u.latest.url, target: "_blank", rel: "noopener", textContent: "Что нового и где скачать" });
    const x = Object.assign(document.createElement("button"), { type: "button", textContent: "Скрыть", title: "Не напоминать об этой версии" });
    x.onclick = async () => { try { await post("/api/update/dismiss", { tag: u.latest.tag }); } catch (e) { /* не с этого компьютера: скроем до перезагрузки */ } b.remove(); };
    b.append(t, a, " ", x); main.prepend(b);
  } catch (e) { /* сервер недоступен или нет связи — баннера просто нет */ }
});

// «← к списку» на карточке предмета: вернуться туда, откуда пришли (с теми же фильтрами), иначе — в каталог
document.addEventListener("click", e => {
  const a = e.target.closest("a.back");
  if (a && document.referrer.startsWith(location.origin) && history.length > 1) { e.preventDefault(); history.back(); }
});

// ---------- уведомления в браузере (дополнение к desktop): вкладка раз в 30 с забирает новое из /api/notifications ----------
const BN = {
  on: () => { try { return localStorage.getItem("fo76_bn") === "1"; } catch (e) { return false; } },
  state() {
    if (!("Notification" in window)) return "unsupported";
    if (Notification.permission === "denied") return "denied";
    return Notification.permission === "granted" && BN.on() ? "on" : "off";
  },
  async enable() {
    if (!("Notification" in window)) throw new Error("Браузер не поддерживает уведомления (нужен localhost или HTTPS)");
    if (await Notification.requestPermission() !== "granted") throw new Error("Разрешение не выдано: проверьте настройки сайта в браузере");
    localStorage.setItem("fo76_bn", "1");
    localStorage.setItem("fo76_bn_last", String((await api("/api/notifications")).last));  // накопившееся не показываем
    BN.start();
  },
  disable() { try { localStorage.removeItem("fo76_bn"); } catch (e) { /* без хранилища нечего выключать */ } },
  show(title, body, tag) {
    const n = new Notification(title, { body, tag, icon: "/static/icons/icon-192.png" });
    n.onclick = () => { window.focus(); n.close(); };
  },
  async poll() {
    if (BN.state() !== "on") return;
    try {
      const last = localStorage.getItem("fo76_bn_last");
      const r = await api("/api/notifications" + (last === null ? "" : "?after=" + last));
      for (const i of r.items) BN.show(i.title, i.body, "fo76-" + i.id);  // tag: та же вкладка/браузер не покажет дубль
      localStorage.setItem("fo76_bn_last", String(r.last));
    } catch (e) { /* сервер недоступен — попробуем в следующий раз */ }
  },
  start() { if (!BN.timer) { BN.timer = setInterval(BN.poll, 30000); BN.poll(); } },
};
document.addEventListener("DOMContentLoaded", () => { if (BN.state() === "on") BN.start(); });
