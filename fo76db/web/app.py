"""Веб-интерфейс: FastAPI + Jinja2 + Tabulator. Запуск: python -m fo76db serve.

Здесь — приложение, защита (токен, CSRF, заголовки), вход, PWA-файлы и /healthz; страницы и API — в `routes/`."""
from __future__ import annotations

import html
import secrets
import time
import urllib.parse
import urllib.request

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__, config, maintenance
from .common import HERE, _eq, _local, templates
from .routes import actions, events, inventory, items, launcher, plans, settings

API_DESCRIPTION = """Локальный API утилиты FO76 DB: каталог предметов, инвентарь, роллы, события, настройки.

**Доступ.** С этого компьютера (127.0.0.1, без прокси) токен не нужен. Из сети, если в настройках задан токен, передавайте
`Authorization: Bearer <токен>` (или cookie `fo76db_token`, или `?token=` один раз). Без токена — 401.
Изменяющие запросы с чужого `Origin` без Bearer отклоняются (защита от CSRF). Для браузерного фронтенда на другом адресе
добавьте его в `cors_origins` в `config.toml`. Запись путей, настроек сети, конфига IOM и подобное — только с этого компьютера."""

app = FastAPI(title="FO76 DB", version=__version__, description=API_DESCRIPTION)

app.add_middleware(GZipMiddleware, minimum_size=2048)

def _openapi() -> dict:
    """Схема OpenAPI; теги — по первому сегменту пути (/api/items → items), чтобы генераторы клиентов делили методы по группам."""
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    tags = set()
    for path, ops in schema["paths"].items():
        parts = [x for x in path.split("/") if x and x != "api"]
        tag = parts[0] if parts else "root"
        for op in ops.values():
            op.setdefault("tags", [tag])
            tags.add(tag)
    schema["tags"] = [{"name": t} for t in sorted(tags)]
    schema["components"].setdefault("securitySchemes", {})["bearer"] = {"type": "http", "scheme": "bearer", "description": "token из config.toml / «Настройки → Доступ по сети»"}
    app.openapi_schema = schema
    return schema

app.openapi = _openapi

app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

templates.env.globals["version"] = __version__

# ---------- доступ не с этого компьютера: токен ----------
# Токен (config.toml: token, или FO76DB_TOKEN) нужен для всех запросов, кроме локальных: телефон (PWA), другой компьютер,
# Docker с пробросом порта, обратный прокси (tailscale serve, Caddy) — у них есть X-Forwarded-For.
# Вход: ссылка ?token=<токен> один раз или форма /login; дальше — cookie на год.

COOKIE = "fo76db_token"

OPEN_PATHS = ("/static/", "/manifest.webmanifest", "/sw.js", "/login", "/favicon.ico", "/healthz")

@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """Изменяющие запросы — только со страниц этого же сайта (Sec-Fetch-Site / Origin): иначе любая открытая
    вкладка могла бы дёргать запуск загрузок и запись конфига через «простой» POST."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and not _bearer_ok(request, config.load().get("token") or ""):
        site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")
        if site is not None and site not in ("same-origin", "none"):
            return JSONResponse({"detail": "запрос с чужого сайта"}, status_code=403)
        if origin and origin != "null" and urllib.parse.urlsplit(origin).netloc != request.headers.get("host", ""):
            # за прокси Host может быть внешним — сверяем и с X-Forwarded-Host
            if urllib.parse.urlsplit(origin).netloc != request.headers.get("x-forwarded-host", ""):
                return JSONResponse({"detail": "запрос с чужого сайта"}, status_code=403)
    return await call_next(request)

def _csp(request: Request) -> str:
    """Скрипты — только свои файлы и инлайн-блоки с nonce; /docs и /redoc (Swagger с CDN) — только запрет встраивания."""
    if request.url.path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        return "frame-ancestors 'none'"
    return (f"default-src 'self'; script-src 'self' 'nonce-{request.state.nonce}'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'")

@app.middleware("http")
async def security_headers(request: Request, call_next):
    request.state.nonce = secrets.token_urlsafe(16)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy", _csp(request))
    return resp

@app.middleware("http")
async def token_auth(request: Request, call_next):
    token = config.load().get("token") or ""
    path = request.url.path
    if not token or _local(request) or path.startswith(OPEN_PATHS):
        return await call_next(request)
    if _eq(request.cookies.get(COOKIE, ""), token) or _bearer_ok(request, token):
        return await call_next(request)
    if (given := request.query_params.get("token")) is not None and _eq(given, token):
        query = urllib.parse.urlencode([(k, v) for k, v in request.query_params.multi_items() if k != "token"])
        resp = RedirectResponse(_safe_next(path) + (f"?{query}" if query else ""), status_code=303)
        _set_cookie(resp, request, token)
        return resp
    if path.startswith("/api/") or request.method != "GET":
        return JSONResponse({"detail": "нужен токен доступа"}, status_code=401)
    return RedirectResponse(f"/login?next={urllib.parse.quote(str(request.url.path))}", status_code=303)

def _bearer_ok(request: Request, token: str) -> bool:
    auth = request.headers.get("authorization") or ""
    return bool(token) and auth[:7].lower() == "bearer " and _eq(auth[7:].strip(), token)

def _set_cookie(resp: Response, request: Request, token: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, token, max_age=365 * 86400, httponly=True, samesite="lax", secure=secure)

if _cors := config.load().get("cors_origins"):  # добавляется последним — значит снаружи token_auth: preflight идёт без токена
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=list(_cors), allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])

LOGIN_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Вход — FO76 DB</title>
<link rel="stylesheet" href="/static/app.css"><link rel="manifest" href="/manifest.webmanifest"></head>
<body><main style="max-width:420px;margin:12vh auto;padding:0 16px">
<h1>☢ FO76 DB</h1><p class="muted">Доступ не с этого компьютера защищён токеном (настройка <code>token</code>).</p>
<form method="post" action="/login" style="display:flex;gap:8px">
<input type="hidden" name="next" value="{next}"><input type="password" name="token" placeholder="Токен" autofocus required style="flex:1">
<button class="primary">Войти</button></form>{error}</main></body></html>"""

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(next: str = "/home"):
    return LOGIN_HTML.format(next=html.escape(_safe_next(next)), error="")

_fails: dict[str, list[float]] = {}  # IP -> времена неудачных входов (скользящее окно)

def _throttled(ip: str) -> bool:
    now = time.monotonic()
    fresh = [t for t in _fails.get(ip, []) if now - t < 300]
    _fails[ip] = fresh
    return len(fresh) >= 5

@app.post("/login", include_in_schema=False)
async def login(request: Request):
    ip = request.client.host if request.client else ""
    if _throttled(ip):
        return HTMLResponse(LOGIN_HTML.format(next="/home", error='<p class="no">Слишком много попыток, подождите 5 минут</p>'), status_code=429)
    form = urllib.parse.parse_qs((await request.body()).decode())
    token, nxt = (form.get("token") or [""])[0], _safe_next((form.get("next") or ["/home"])[0])
    expected = config.load().get("token") or ""
    if expected and _eq(token, expected):
        resp = RedirectResponse(nxt, status_code=303)
        _set_cookie(resp, request, expected)
        return resp
    _fails.setdefault(ip, []).append(time.monotonic())
    return HTMLResponse(LOGIN_HTML.format(next=html.escape(nxt), error='<p class="no">Неверный токен</p>'), status_code=401)

def _safe_next(nxt: str) -> str:
    """Только путь этого сайта: без схемы и хоста (открытый редирект)."""
    return nxt if nxt.startswith("/") and not nxt.startswith(("//", "/\\")) else "/home"

# ---------- PWA: манифест и service worker (с корня сайта, чтобы область действия была «/») ----------

@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    icon = "/static/icons/icon"
    return JSONResponse({
        "name": "FO76 DB", "short_name": "FO76 DB", "lang": "ru",
        "description": "База предметов, инвентаря и событий Fallout 76",
        "id": "/home", "start_url": "/home", "scope": "/", "display": "standalone",
        "background_color": "#0f1412", "theme_color": "#161d1a",
        "icons": [
            {"src": f"{icon}.svg", "sizes": "any", "type": "image/svg+xml"},
            {"src": f"{icon}-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": f"{icon}-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": f"{icon}-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Инвентарь", "url": "/inventory"},
            {"name": "События", "url": "/events"},
            {"name": "Роллы", "url": "/rolls"},
        ],
    }, media_type="application/manifest+json")

@app.get("/sw.js", include_in_schema=False)
def service_worker():
    js = (HERE / "static" / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", __version__)
    return Response(js, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse("/static/icons/icon.svg")

@app.get("/healthz")
def healthz():
    """Без токена (для Docker HEALTHCHECK и мониторинга): только состояние, без данных пользователя."""
    try:
        h = maintenance.health()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": type(e).__name__}, status_code=503)
    return {"ok": True, "version": h["version"], "catalog_release": h["catalog_release"]}

for _m in (items, inventory, plans, actions, events, settings, launcher):  # порядок — как раньше в одном файле
    app.include_router(_m.router)
