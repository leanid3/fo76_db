# Устройство

Python 3.14, FastAPI + Jinja2, SQLite (WAL), на фронте Tabulator 6.3.1 (`fo76db/web/static/`). Сборщиков и npm нет.

## Модули

| Файл | Что делает |
|---|---|
| `fo76db/cli.py` | Команды `catalog`, `history`, `import`, `events`, `watch`, `notify`, `serve` (`--open` — открыть браузер), `--version`. Собранный бинарник без аргументов = `serve --open` |
| `fo76db/config.py` | Настройки: значения по умолчанию плюс `config.toml` плюс `FO76DB_GAME_DATA`. `game_data()` — папка Data игры, `{game_data}` в путях выгрузок. `expand()` разворачивает glob и пропускает пустые файлы-заготовки |
| `fo76db/db.py` | Папка данных `ROOT` (`_home()`: `FO76DB_HOME`, папка пользователя у бинарника, корень репозитория), схема SQLite, `connect()`, миграции колонок (`MIGRATIONS`), разовые правки данных, `meta` |
| `fo76db/sources/esm.py`, `strings.py` | Чтение `SeventySix.esm` (FormID, EditorID, FULL) и строковых таблиц из `Localization.ba2` |
| `fo76db/sources/dumps.py` | Релизы fwdekker/fo76-dumps: список через GitHub API, скачивание и распаковка 7z в `data/cache/`; `sevenzip()` ищет 7-Zip |
| `pyproject.toml`, `packaging/`, `Dockerfile`, `compose.yaml`, `.github/workflows/build.yml` | Сборка: пакет, PyInstaller (`packaging/fo76db.spec`, лицензии — `packaging/third_party.py`), Flatpak (`packaging/flatpak/`), Docker, GitHub Actions — см. [packaging.md](packaging.md) |
| `mkdocs.yml`, `packaging/pages/prepare.py`, `.github/workflows/pages.yml` | Сайт документации на GitHub Pages |
| `.devcontainer/devcontainer.json` | GitHub Codespaces / Dev Containers |
| `LICENSE`, `CREDITS.md`, `fo76db/web/static/tabulator.LICENSE.txt` | Лицензия (GNU AGPL v3 или новее), благодарности и источники, лицензия Tabulator |
| `fo76db/sources/wiki_patches.py` | Названия и даты обновлений из таблицы патчей Fallout Wiki |
| `fo76db/sources/falloutbuilds.py` | Календарь событий (`parse_calendar`) и Минерва (`parse_minerva`: распродажи и схемы, супер-распродажи раскрываются) с falloutbuilds.com |
| `fo76db/sources/fo76wiki.py` | Сезоны (`parse_seasons`), списки Daily Ops (`parse_dailyops`, запасной `DAILYOPS_FALLBACK`) с fallout.wiki; «как получить» со страницы предмета (`obtain`: fandom, затем fallout.wiki, через `api.php`; русская страница fandom — `_ru_page`) |
| `fo76db/sources/dates.py` | Английские даты без `strptime`: `english_date`, `nearest_year` (дата без года), `month_number`. `%b`/`%B` зависят от локали, а Qt при запуске окна выставляет её из окружения, и при русской локали «Nov 12» не разбиралось |
| `fo76db/sources/net.py` | `get()`: HTTP с коротким таймаутом подключения к каждому IP и запоминанием рабочего адреса |
| `fo76db/importers/catalog.py` | Каталог `items`, `recipes`, `lvli_refs`, граф списков добычи `lvli`/`lvli_edges`, места в мире `placements` (`parse_cell`) |
| `fo76db/importers/history.py` | `added_build` / `removed_build` по `tabular.IDs.csv` всех стабильных релизов |
| `fo76db/importers/inventory.py` | Импорт `itemsmod` (снимки, категории, сопоставление с каталогом, авто-отметки схем) и `LegendaryMods.ini`. `current_items_sql()` — последний снимок каждого персонажа, `item_key()` — ключ предмета `name\|stars\|legendary` |
| `fo76db/obtain.py` | «Как получить»: предки в графе LVLI (`ancestors`), категории по EditorID (`RULES`, `classify`, `sources`), места в мире (`world`), сводка `how_to_get` |
| `fo76db/autotags.py` | Автотеги: редкость, сезон добавления, откуда, состояние. `rebuild()` пересчитывает `item_auto_tags`, `ensure()` — если изменились каталог/история/события; `describe`/`ordered` — подписи и цвета |
| `fo76db/legendary.py` | Легендарные эффекты по звёздам: `slots()` разбирает строку эффектов, `names()` — описание → название EN/RU, `catalog()` — подсказки по звёздам |
| `fo76db/rolls.py` | Нужные роллы: `matcher()` (шаблон звезды), `grade()` (оценка по хотелкам), `graded_inventory()`, `save()`, уведомления — `baseline()` и `new_matches()` |
| `fo76db/plantransfer.py` | Схемы в инвентаре: `moves()` — изучить / передать (кому) / продать, `learners()` — персонажи с данными, кроме складов |
| `fo76db/events.py` | События на сегодня: `refresh()` из сети, сбросы дня и недели (`day_bounds`, `week_bounds`, `period`), Daily Ops, чек-лист, сводка `today()`, русские названия событий |
| `fo76db/optimize.py` | Оптимизатор веса: итоги по персонажам и советы (страница «Вес»); схемы — через `plantransfer`, «на скрип» — через `rolls` |
| `fo76db/iomconfig.py` | Чтение, проверка и запись конфига Invent-O-Matic, бэкапы и откат (страница «IOM») |
| `fo76db/tasks.py` | Фоновые задачи для веб-интерфейса: `catalog`, `history`, `events`, `import` в потоке, одна за раз; журнал последних 200 строк в памяти; `status()` — состояние и сводка данных |
| `fo76db/desktop.py` | Десктоп-версия: pywebview (Linux — Qt, Windows — WebView2), uvicorn в потоке на 127.0.0.1 (или уже запущенный сервер), `watch` в потоке; без консоли — журнал `data/app.log` |
| `fo76db/web/templates/base.html` | Каркас: список разделов `nav_groups` (вкладки → страницы), две раскладки по `layout` (`pipboy` — вкладки + строка состояния, `classic` — плоское меню), стиль — `data-theme`. Выбор из cookie `fo76_theme` / `fo76_layout` (`theme_of`, `layout_of` в `app.py`); клавиши Q/E/A/D и `/` — конец `static/app.js` |
| `fo76db/web/static/sw.js`, `static/icons/` | Service worker PWA (сначала сеть, 4 с, затем кэш) и иконки |
| `fo76db/watch.py` | Раз в 5 с проверяет mtime выгрузок и импортирует изменившиеся. Уведомления — раз в 10 мин, обновление событий — раз в 6 ч (после ошибки — через 15 мин) |
| `fo76db/notify.py` | `notify-send`: новый патч, события, Минерва, вишлист. Уже отправленное запоминается в `meta.notified` (для автособытий — по `ext_key`). `check_rolls()` — новые совпадения нужных роллов, вызывается и сразу после импорта инвентаря |
| `fo76db/gamepaths.py` | Автоопределение игры: `detect()` (Steam Win/Linux/Flatpak, Proton, Xbox, Bethesda.net), только чтение |
| `fo76db/mods.py` | Проверка модов по файлам: `check`, `status(refresh)`, `missing_for(страница)` — для предупреждения в `base.html` (`mod_warn`) и «Настройки → Моды» |
| `fo76db/maintenance.py` | `backup()` (API бэкапа SQLite, ротация только своих файлов), `health()`, `doctor()` — для `fo76db backup/doctor`, `/healthz`, `/api/doctor`, «Настройки → Диагностика» |
| `fo76db/updatecheck.py` | Проверка новой версии: `refresh()` (последний релиз GitHub, раз в 6 ч / 1 ч после сбоя, итог в `meta`: `update_latest`, `update_checked`, `update_error`, `update_dismissed`), `info()`, `dismiss()`; `parse()` — CalVer-кортежи. API `/api/update`, `/api/update/dismiss`, баннер — конец `static/app.js`, уведомление — `notify.check` |
| `fo76db/filepick.py` | Системное окно выбора папки/файла (zenity/kdialog, PowerShell, osascript) для `POST /api/pick` |
| `fo76db/applog.py` | Журнал: `setup(имя)` оборачивает stdout/stderr (`_Tee`) и дописывает строки в `data/app.log`; `tail()` для страницы настроек. Включается в `serve`, `watch`, `desktop` |
| `fo76db/web/app.py` | Приложение FastAPI: токен, CSRF, заголовки и CSP (nonce для инлайн-скриптов), вход, PWA-файлы, `/healthz`; подключает роутеры |
| `fo76db/web/common.py` | Общее для роутеров: `templates`, справочники подписей, `con()`, тема/раскладка, `page()`, `_local`/`_need_local` |
| `fo76db/web/routes/` | Страницы и JSON API по темам: `items` (каталог, карточка, теги, вишлист, поиски), `inventory` (главная, инвентарь, профили, история), `plans` (легендарные, схемы, роллы, оптимизация), `events` (события, Минерва, ежедневные задачи), `settings` (пути, сеть, моды, журнал, копия, диагностика, задачи, IOM) |
| `fo76db/web/static/app.js` | Общий фронт: API, выбор персонажа, «Изучено», колонки, экспорт, сохранённые поиски, параметры URL |
| `fo76db/web/templates/*.html` | Страницы; общий каркас — `base.html` |

## База данных (`data/fo76.sqlite`)

| Таблица | Содержимое |
|---|---|
| `meta` | Служебные значения: `catalog_release`, `history_first`, `notified`, `events_fetched`, `events_error`, `dailyops_vars`, `autotags_key`/`autotags_built`, флаги разовых правок (`fix_stash_weight`, `daily_tasks_seeded`) |
| `builds` | Версии игры (релизы dumps), название обновления, дата выхода |
| `items` | Каталог: FormID, тип, названия EN/RU, вес, цена, `stats` (JSON: крафт, разбор, выпадение…), статус, `added_build` |
| `recipes` | Крафт: схема → предмет, компоненты |
| `lvli_refs` | Списки добычи, в которых предмет встречается напрямую |
| `lvli`, `lvli_edges` | Все списки добычи и рёбра «предмет или список → список, куда он входит» (для «Как получить») |
| `placements` | Где стоит в мире: FormID предмета или списка, название ячейки, мир, количество |
| `wiki_obtain` | Кэш разделов «как получить» с вики: FormID, `wiki`, заголовок, `url`, HTML; русская страница — `ru_title`, `ru_url`, `ru_html`; `ru_checked`; время. Ничего не нашлось — `title` и `ru_title` NULL |
| `characters` | Аккаунт и имя персонажа, `info` (JSON из выгрузки) |
| `inv_snapshots` | Снимки выгрузок: время, файл, `digest`, `archived` |
| `inv_items` | Записи снимка: место (`player`/`stash`), название, категория, FormID, количество, вес, звёзды, эффекты, `learned`, `equipped`, `raw` (исходный JSON) |
| `known_recipes` | Изученные схемы: персонаж, FormID, `source` = `auto` или `manual` |
| `known_legendary_mods` | Легендарные моды по персонажам |
| `profiles`, `account_labels` | Подписи и цвета персонажей и аккаунтов; `profiles.mule` = 1 — персонаж-склад |
| `leg_wants` | Нужные роллы: название, `scope` (`any`/`weapon`/`armor`), шаблоны звёзд `s1`–`s4` (NULL — любой), `notify` |
| `leg_want_seen` | Уже показанные совпадения хотелки: `want_id`, ключ `character_id\|name\|stars\|legendary`. Пересоздаётся при правке хотелки |
| `tags`, `item_tags` | Теги и их привязка к ключу предмета `name\|stars\|legendary` |
| `item_auto_tags` | Автотеги: FormID и код `группа:значение`. Пересчитывается целиком (`autotags.ensure`) |
| `display_names` | Свои отображаемые имена по ключу предмета |
| `saved_searches` | Сохранённые поиски: страница, имя, строка запроса |
| `events` | События. `source`: NULL — вручную, `falloutbuilds`, `wiki` (сезоны), `dailyops`. `ext_key` — стабильный ключ автособытия, `data` — JSON (распродажа и место Минервы, номер сезона, параметры Daily Ops). Время — местное, `ГГГГ-ММ-ДДTЧЧ:ММ` |
| `minerva_plans` | Схемы распродаж Минервы: номер, `name_en`, `formid` (NULL — не нашлось в каталоге). Перезаписывается при обновлении |
| `daily_tasks`, `daily_done` | Чек-лист ежедневок: пункты (`reset` = `daily`/`weekly`, `per_char`) и отметки по персонажам за `period` (дата начала игрового дня или недели). Отметки старше 30 дней удаляются |
| `wishlist` | Вишлист |

### Изменение схемы

- **Новая таблица** добавляется в `SCHEMA` (`CREATE TABLE IF NOT EXISTS`).
- **Новая колонка** существующей таблицы добавляется в `MIGRATIONS` (`ALTER TABLE ADD COLUMN` при подключении).
- **Разовая правка уже сохранённых данных** выполняется в `_migrate()` под флагом в `meta`, чтобы сработать один раз. Перед ней делается копия базы:
  `sqlite3 data/fo76.sqlite ".backup data/fo76.sqlite.bak-<ГГГГММДД>-<что>"`. Копировать сам файл через `cp` нельзя: в WAL-режиме часть данных лежит в `-wal`.

## JSON API

Все ответы — JSON. Ошибки FastAPI приходят в виде `{"detail": …}`; `api()` в `app.js` показывает этот текст.

| Метод и путь | Назначение |
|---|---|
| `GET /api/items` | Весь каталог (кэшируется в памяти). Поле `plans` — FormID схем, которые учат предмет; `atags` — коды автотегов |
| `GET /api/autotags` | Все автотеги: `code, group, group_ru, label, color, used` по порядку групп |
| `GET /api/legendary/effects` | Подсказки для поиска по звёздам: `{1..4: [{en, ru, desc}]}` |
| `POST /api/wishlist` | `{formid, wish, note}` |
| `GET /api/inventory` | Последние снимки всех персонажей, с тегами, автотегами (`atags`), отображаемыми именами, `learned_by`, эффектами по звёздам (`slots: [{star, text, en, ru}]`, `leg_extra`), оценкой `roll: {grade, want_id, want, hits, need}` |
| `GET /api/rolls` | `{wants: [… , god, partial], items: [легендарки с slots и roll]}` |
| `POST /api/rolls`, `DELETE /api/rolls/{id}` | Создать/изменить хотелку (`{id?, name, scope, s1..s4, notify}`; 400 — нет названия или ни одной звезды), удалить |
| `GET /api/plans/moves` | Схемы в инвентаре: `{characters, learners, moves: [{id, holder, container, count, action, need, need_labels, known_labels}], actions}` |
| `POST /api/mule` | `{character_id, mule}` — отметить склад |
| `GET /api/home` | Итоги для главной |
| `GET /api/tasks` | `{tasks: {catalog|history|events|import: {status, started, finished, error, log, title}}, data: {items, builds, catalog_release, events_fetched, game_data, game_found, home}}` |
| `POST /api/tasks/{name}` | Запустить задачу; 409 — уже идёт другая, 404 — нет такой |
| `GET /manifest.webmanifest`, `GET /sw.js` | PWA: манифест и service worker с корня сайта (`__VERSION__` → версия) |
| `GET/POST /login` | Вход по токену (форма); `next` — только путь этого сайта |
| `GET /api/optimize?scrapbox&ammobox&heavy&limit` | Итоги веса и советы оптимизатора |
| `GET /api/known?character_id=` | `{formid: auto\|manual}` |
| `POST /api/known` | `{character_id, formid, known}`. Снятие удаляет только ручную отметку |
| `POST /api/known/bulk` | `{character_id, formids[], known}` |
| `GET /api/updates/plans?character_id=` | Изучено X из Y по обновлениям |
| `GET /api/plans`, `GET /api/legendary` | Матрицы схем и легендарных модов |
| `GET /api/snapshots?character_id&archived` | Снимки персонажа |
| `GET /api/diff?a&b` | Разница двух снимков: `added`, `removed`, `count`, `moved` |
| `POST /api/snapshots/archive`, `POST /api/snapshots/{id}/unarchive` | Архив снимков |
| `GET /openapi.json`, `/docs` | Схема OpenAPI (теги по первому сегменту пути, без HTML-страниц); файл `docs/openapi.json` — `fo76db openapi`; Bearer-токен и CORS (`cors_origins`) — `docs/api.md` |
| `GET /api/network`, `POST /api/network` | Режим доступа (`local`/`lan`) и токен; хранится в `data/network.json`, перекрывает `host`/`token` из `config.toml` (`config.saved_network`); только loopback; `app.state.bind_host` — на каком адресе сервер реально запущен |
| `GET /api/paths`, `POST /api/paths`, `GET /api/mods?refresh=`, `POST /api/pick` | Пути игры: текущие значения, источник, проверка, найденные установки; сохранение в `data/paths.json` (пусто — автоопределение); моды: есть ли файлы и где они лежат; окно выбора пути (только loopback) |
| `GET /healthz` | Без токена: `{ok, version, catalog_release}`, 503 если база не отвечает. Docker `HEALTHCHECK` |
| `GET /api/doctor`, `GET /api/backup`, `POST /api/backup` | Проверки окружения; скачать копию базы и сохранить её в `data/db-backups` (оба — только с этого компьютера) |
| `GET /api/log?lines=`, `GET /api/log/download`, `DELETE /api/log` | Журнал приложения (`data/app.log`): хвост, скачать, очистить |
| `GET/POST /api/profiles`, `POST /api/accounts` | Подписи и цвета (`POST /api/profiles` принимает и `mule`) |
| `GET/POST /api/tags`, `DELETE /api/tags/{id}`, `POST /api/tags/apply` | Теги |
| `POST /api/display_name` | `{key, name}`; пустое имя удаляет запись |
| `GET/POST /api/saved`, `DELETE /api/saved/{id}` | Сохранённые поиски |
| `GET /api/iom`, `POST /api/iom/validate`, `POST /api/iom/save`, `POST /api/iom/restore` (тело: `sha1`, необязательный `backup` — путь из списка `backups`) | Редактор IOM (см. [iom-editor.md](iom-editor.md)) |
| `GET/POST /api/events`, `DELETE /api/events/{id}` | События. Удаляются только ручные и Daily Ops |
| `POST /api/events/refresh` | Обновить календарь, Минерву, сезоны и списки Daily Ops: `{calendar, minerva_plans, seasons, errors}` |
| `GET /api/today?character_id` | Сводка: сбросы дня и недели, сезон, идущие и ближайшие события, Минерва (+ не изучено у персонажа), Daily Ops, списки Daily Ops |
| `GET /api/minerva?sale&character_id` | Схемы распродажи: `id`, названия, `known`, `wish` |
| `POST /api/dailyops` | `{mode, location, faction, mutations, note}` на текущий игровой день |
| `GET /api/daily`, `POST /api/daily/toggle`, `POST /api/daily/tasks`, `DELETE /api/daily/tasks/{id}` | Чек-лист ежедневок |
| `GET /api/item/{formid}/wiki?refresh` | Разделы «Locations»/«Vendors» со страницы fandom или fallout.wiki: `{wiki, title, url, html, ru: {title, url, html} | null, cached}`. 502 — ни одна вики не ответила |
| `GET /api/nukes` | Коды ракет (NukaCrypt, кэш) |

## Фронт: общие помощники (`app.js`)

| Помощник | Что делает |
|---|---|
| `tableOpts(id, opts)` | Общие опции таблиц: перетаскивание колонок и запоминание ширины, видимости и сортировки, если доступно `localStorage` (ключ с версией `TABLE_VIEW_VERSION`; «Сбросить вид» чистит его) |
| `loadAutoTags()`, `autoTagBadges(codes)`, `autoTagLabels(codes)`, `autoTagOptions(prefix)` | Автотеги: загрузка подписей и цветов, цветные метки, текст для поиска, `<optgroup>` по группам для фильтров |
| `starMatcher(q)`, `slotsHtml(slots, hits)`, `rollBadge(roll)`, `rollText(roll)` | Шаблон звезды с вариантами через `\|` (как `rolls.matcher`), эффекты по звёздам с отметкой совпавших, значок и текст оценки ролла |
| `addExport(table, toolbar, name)` | Кнопки CSV и JSON, заодно «☰ Колонки» |
| `addColumnPicker(table, toolbar)` | Только «☰ Колонки» |
| `addSavedSearches(toolbar, apply)` | «★ Сохранённые» |
| `readParams(ids)` / `writeParams(ids)` | Поля фильтров ↔ адресная строка; без параметров в адресе `readParams` берёт последние фильтры страницы из `localStorage` (`fo76.filters.<путь>`, без `q`) |
| `toast(msg, kind, ms)` | Всплывающее сообщение (`info`, `ok`, `warn`, `err`) вместо `alert`; ошибки с `role="alert"` |
| `uiConfirm(text, {ok, danger})`, `uiPrompt(text, def)`, `uiDialog({text, options, ...})` | Диалоги на `<dialog>` вместо `confirm`/`prompt` (`await`); `options` — выбор из списка. `alert`/`confirm`/`prompt` в коде не используются |
| `busy(btn, fn)`, `debounce(fn, ms)` | Блокировка кнопки на время действия; задержка фильтров при вводе (180 мс) |
| обёртка `Tabulator` | Высота `calc(100vh - N)` считается от положения таблицы и пересчитывается при изменении окна; `placeholder` по умолчанию; ошибка загрузки данных — сообщение вместо пустой таблицы; на узком экране `fitDataFill` |
| `currentChar()`, `loadKnown()`, `knownColumn()` | Персонаж из шапки и колонка «Изучено». Смена персонажа — событие `charchange` |

## Доступ по токену

Middleware `token_auth` в `web/app.py`. CSP: `script-src 'self'` и nonce на каждый инлайн-`<script>` (шаблоны берут `{{ csp_nonce }}`); `/docs` и `/redoc` — только запрет встраивания. Если в настройках задан `token` (`config.toml` или `FO76DB_TOKEN`), каждый запрос, кроме
локального, должен нести cookie `fo76db_token`. Локальным считается запрос с адреса 127.0.0.1 или ::1, у которого в `Host` указан
localhost или 127.0.0.1 и нет заголовков прокси (`X-Forwarded-For`, `Forwarded`, `X-Forwarded-Host`, `X-Real-IP`). Так через
`tailscale serve` и Caddy токен всё равно спрашивается, а подмена DNS не обходит проверку.

- Cookie выдают ссылка `?token=` (редирект без токена в адресе) и форма `/login`.
- Без токена: страницы перенаправляют на `/login`, API и запросы не-GET получают 401.
- Без проверки открыты `/static/`, `/manifest.webmanifest`, `/sw.js`, `/login` и `/favicon.ico`.
- Сравнение — `hmac.compare_digest`.

## Тесты и проверки

`pip install -e ".[dev]"`, затем `pytest` и `ruff check fo76db tests` (CI — `.github/workflows/test.yml`, Python 3.12–3.14).
`tests/conftest.py` задаёт `FO76DB_HOME` во временную папку до импорта `fo76db`, поэтому настоящие `data/` и `config.toml` не затрагиваются.
Покрыто: настройки и атомарная запись (`test_config.py`), загрузки (`test_dumps.py`), токен, cookie, «только локально», CSRF, лимит входа, заголовки (`test_security.py`); запись IOM — sha1, бэкап, inode, откат (`test_iomconfig.py`); схема и миграции (`test_db.py`). Ruff — только ошибки (F, E9, B), без стилевых правил.

## Запуск как фоновые процессы

```sh
.venv/bin/python -m fo76db serve --port 7676 > data/serve.log 2>&1 &
.venv/bin/python -u -m fo76db watch > data/watch.log 2>&1 &
```

После правки Python-кода оба процесса нужно перезапустить. Шаблоны и статика подхватываются при обновлении страницы.
