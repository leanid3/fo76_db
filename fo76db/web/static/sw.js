// Service worker FO76 DB (PWA). Отдаётся как /sw.js, чтобы управлять всем сайтом; __VERSION__ подставляет сервер.
// Стратегия — «сначала сеть»: свежие данные, если сервер доступен (за 4 с), иначе последняя сохранённая копия
// страницы или ответа API. Так на телефоне без связи с домом остаётся видно, что где лежит, на момент последнего открытия.
const CACHE = "fo76db-__VERSION__";
const PRECACHE = [
  "/home", "/static/app.css", "/static/app.js", "/static/tabulator.min.js", "/static/tabulator_midnight.min.css",
  "/static/icons/icon.svg", "/static/icons/icon-192.png",
];
const NO_CACHE = ["/api/tasks", "/login", "/sw.js"];
const TIMEOUT = 4000;
const MAX_ENTRIES = 120;  // сверх предзагрузки: самые старые записи удаляются, кэш не растёт бесконечно

async function trim(cache) {
  const keys = await cache.keys();
  const extra = keys.filter(r => !PRECACHE.includes(new URL(r.url).pathname));
  for (const r of extra.slice(0, Math.max(0, extra.length - MAX_ENTRIES))) await cache.delete(r);  // keys() — по порядку добавления
}

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("fo76db-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("timeout")), ms);
    promise.then(r => { clearTimeout(t); resolve(r); }, err => { clearTimeout(t); reject(err); });
  });
}

const OFFLINE = `<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Нет связи — FO76 DB</title>
<link rel="stylesheet" href="/static/app.css"></head><body><main style="max-width:480px;margin:12vh auto;padding:0 16px">
<h1>☢ FO76 DB</h1><p>Сервер недоступен, а эта страница ещё не открывалась с этого устройства.</p>
<p class="muted">Откройте <a href="/home">главную</a> или <a href="/inventory">инвентарь</a> — они могли сохраниться.</p>
</main></body></html>`;

self.addEventListener("fetch", e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || NO_CACHE.some(p => url.pathname.startsWith(p))) return;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const resp = await withTimeout(fetch(req), TIMEOUT);
      // кэшируются только успешные ответы; переход на /login (нет токена) не кэшируется
      if (resp.ok && !resp.redirected) e.waitUntil(cache.put(req, resp.clone()).then(() => trim(cache)).catch(() => {}));
      return resp;
    } catch (err) {
      const hit = await cache.match(req, {ignoreVary: true});
      if (hit) {  // ответ из кэша помечается: страница покажет «нет связи», а не выдаст старые данные за свежие
        const h = new Headers(hit.headers); h.set("X-FO76-Cache", "1");
        return new Response(hit.body, {status: hit.status, statusText: hit.statusText, headers: h});
      }
      if (req.mode === "navigate") return new Response(OFFLINE, {headers: {"Content-Type": "text/html; charset=utf-8"}});
      return Response.error();
    }
  })());
});
