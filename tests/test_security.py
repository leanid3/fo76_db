"""Токен, «локальные» эндпоинты, CSRF, экранирование /login."""


def test_login_escapes_next(remote):
    r = remote.get("/login", params={"next": '/"><script>alert(1)</script>'})
    assert r.status_code == 200 and "<script>alert" not in r.text and "&quot;&gt;" in r.text


def test_login_rejects_backslash_next(remote):
    assert 'value="/home"' in remote.get("/login", params={"next": "/\\evil.com"}).text


def test_no_token_means_open(remote):
    assert remote.get("/home").status_code == 200


def test_token_required_remote(remote, monkeypatch):
    monkeypatch.setenv("FO76DB_TOKEN", "secret")
    assert remote.get("/api/log", follow_redirects=False).status_code == 401
    assert remote.get("/home", follow_redirects=False).status_code == 303


def test_token_cookie_and_non_ascii(remote, monkeypatch):
    monkeypatch.setenv("FO76DB_TOKEN", "secret")
    remote.cookies.set("fo76db_token", "secret")
    assert remote.get("/home").status_code == 200
    remote.cookies.clear()
    r = remote.get("/home", headers={b"cookie": "fo76db_token=пароль".encode()}, follow_redirects=False)
    assert r.status_code == 303  # не 500


def test_local_needs_no_token(client, monkeypatch):
    monkeypatch.setenv("FO76DB_TOKEN", "secret")
    assert client.get("/home").status_code == 200


def test_remote_cannot_write_paths_even_with_token(remote, monkeypatch):
    monkeypatch.setenv("FO76DB_TOKEN", "secret")
    remote.cookies.set("fo76db_token", "secret")
    assert remote.post("/api/paths", json={"game_data": ""}).status_code == 403
    assert remote.post("/api/iom/restore", json={"sha1": "x"}).status_code == 403
    assert remote.delete("/api/log").status_code == 403
    assert remote.post("/api/actions/apply", json={"sha1": "x", "confirm": True}).status_code == 403


def test_csrf_cross_site_blocked(client):
    r = client.post("/api/paths", json={"game_data": ""}, headers={"Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.post("/api/paths", json={"game_data": ""}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_csrf_same_origin_allowed(client):
    r = client.post("/api/iom/validate", json={"data": {}}, headers={"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_login_throttle(remote, monkeypatch):
    from fo76db.web import app as A
    A._fails.clear()
    monkeypatch.setenv("FO76DB_TOKEN", "secret")
    codes = [remote.post("/login", data={"token": "bad"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    A._fails.clear()


def test_security_headers(client):
    h = client.get("/home").headers
    assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"


def test_csp_nonce_on_pages(client):
    r = client.get("/home")
    csp = r.headers["content-security-policy"]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp.split("style-src")[0]
    assert f'nonce="{nonce}"' in r.text and "<script>" not in r.text


def test_glossary_page(client):
    r = client.get("/glossary")
    assert r.status_code == 200 and "FormID" in r.text


def test_filepick_start_not_in_powershell_script(monkeypatch):
    """Путь старта передаётся окружением: кавычки Юникода в имени папки не выходят из строки скрипта."""
    from fo76db import filepick
    monkeypatch.setattr(filepick.sys, "platform", "win32")
    nasty = "C:\\a\u2019; Remove-Item -Recurse C:\\x; \u2018"
    script = filepick._command(True, nasty, "t")[-1]
    assert "Remove-Item" not in script and "$env:FO76_START" in script
