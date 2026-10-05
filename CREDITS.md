# Благодарности и источники

FO76 DB стоит на чужой работе: данных, модов, идей и библиотек. Ниже всё, что использовалось при создании, со ссылками на оригиналы.
Спасибо авторам!

FO76 DB — неофициальная фанатская утилита, не связана с Bethesda Softworks, ZeniMax Media или Microsoft и не одобрена ими.
Fallout® и Fallout 76 — товарные знаки их правообладателей. Файлы игры в репозитории и сборках не распространяются:
утилита читает установленную у пользователя игру.

## Данные

| Источник | Автор | Что берём | Как |
|---|---|---|---|
| [fo76-dumps](https://github.com/fwdekker/fo76-dumps) | Florine W. Dekker ([fwdekker](https://github.com/fwdekker)) | Статы, крафт, разбор, списки добычи, места в мире, история появления предметов по ~140 версиям игры с 2019 года | Скачиваются релизы у пользователя |
| [Fallout Wiki (Fandom)](https://fallout.fandom.com/wiki/Fallout_76_patches), [русская](https://fallout.fandom.com/ru) | Сообщество Fallout Wiki, тексты под CC BY-SA | Названия и даты обновлений, текст «Как получить» | Запросы у пользователя, в карточке — ссылка на страницу |
| [fallout.wiki](https://fallout.wiki) (Independent Fallout Wiki) | Сообщество, тексты под CC BY-SA | Сезоны, списки Daily Ops, запасной источник «Как получить» | То же |
| [falloutbuilds.com](https://www.falloutbuilds.com/fo76/events/) | Fallout Builds | Календарь событий, расписание и схемы Минервы | Чтение страниц у пользователя |
| [NukaCrypt](https://nukacrypt.com) | NukaCrypt | Коды ракет на неделю | API у пользователя |
| [Nuka Knights](https://nukaknights.com/en/) | Nuka Knights | Только ссылки: Daily Ops и поиск по предмету | — |

## Моды, чьи выгрузки читает утилита

- **[Invent-O-Matic Stash (Unofficial)](https://www.nexusmods.com/fallout76/mods/2335)**: manson_ew2 (автор оригинального
  Invent-O-Matic) и MsZelia. Выгрузка инвентаря и тайника (Extract, `itemsmod.ini`) и правила, которые редактирует страница IOM.
- **[Improved Workbench](https://www.nexusmods.com/fallout76/mods/2576)**: MsZelia. Список изученных легендарных модов (`LegendaryMods.ini`).

## Идеи

- **[Inventory Viewer](https://github.com/ButterflyTsting/inventory-viewer)**: VaultButterfly. Отсюда идеи главной страницы, тегов,
  истории снимков и редактора правил IOM. У проекта нет лицензии, поэтому код не заимствован: в FO76 DB своя реализация.
- Форматы `SeventySix.esm` (записи, группы, сжатие) и `.ba2` (BTDX) — по открытым описаниям сообщества моддеров:
  [UESP](https://en.uesp.net/wiki/Skyrim_Mod:Mod_File_Format), [xEdit](https://github.com/TES5Edit/TES5Edit).

## Библиотеки и программы

| Компонент | Лицензия | Где используется |
|---|---|---|
| [Python](https://www.python.org/) | PSF | везде; входит в бинарник и exe |
| [FastAPI](https://github.com/fastapi/fastapi), [Starlette](https://github.com/Kludex/starlette), [Pydantic](https://github.com/pydantic/pydantic) | MIT, BSD-3-Clause, MIT | веб-сервер и API |
| [Uvicorn](https://github.com/Kludex/uvicorn) | BSD-3-Clause | веб-сервер |
| [Jinja2](https://github.com/pallets/jinja), [MarkupSafe](https://github.com/pallets/markupsafe), [Click](https://github.com/pallets/click) | BSD-3-Clause | шаблоны страниц, зависимость Uvicorn |
| [AnyIO](https://github.com/agronholm/anyio), [h11](https://github.com/python-hyper/h11), [idna](https://github.com/kjd/idna), typing-extensions, annotated-types, typing-inspection, annotated-doc, opentelemetry-api | MIT, BSD, PSF, Apache-2.0 | зависимости FastAPI и Uvicorn |
| [tzdata](https://github.com/python/tzdata) | Apache-2.0 | часовые пояса там, где нет системной базы |
| [Tabulator](https://github.com/olifolkerd/tabulator) | MIT, Oli Folkerd | все таблицы; лежит в `fo76db/web/static/` с лицензией `tabulator.LICENSE.txt` |
| [7-Zip](https://www.7-zip.org) | LGPL-2.1 + BSD-3-Clause + ограничение unRAR, Igor Pavlov | распаковка архивов fo76-dumps; входит в образ Docker и пакет Flatpak |
| [pywebview](https://github.com/r0x0r/pywebview) | BSD-3-Clause | окно десктоп-версии |
| [Qt](https://www.qt.io/) и [PySide6](https://doc.qt.io/qtforpython-6/) (Qt WebEngine, внутри — Chromium) | LGPL-3.0 | десктоп-версия для Linux, пакет Flatpak |
| [Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/), [pythonnet](https://github.com/pythonnet/pythonnet) | компонент Windows, MIT | десктоп-версия для Windows (WebView2 не входит в сборку, он есть в системе) |
| [QtPy](https://github.com/spyder-ide/qtpy), [bottle](https://github.com/bottlepy/bottle), proxy_tools | MIT | зависимости pywebview |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | GPL-2.0 с исключением для загрузчика | сборка бинарника и exe |
| [MkDocs](https://github.com/mkdocs/mkdocs), [Material for MkDocs](https://github.com/squidfunk/mkdocs-material) | BSD-2-Clause, MIT | сайт документации на GitHub Pages |
| [MIT Kerberos (krb5)](https://web.mit.edu/kerberos/) | MIT-подобная (NOTICE) | `libgssapi_krb5` для Qt Network в пакете Flatpak |
| [Flatpak](https://flatpak.org), [freedesktop runtime](https://gitlab.com/freedesktop-sdk/freedesktop-sdk) | LGPL-2.1, разные свободные | пакет Flatpak |

Полные тексты лицензий всего, что входит в бинарник и exe, лежат в `THIRD_PARTY_LICENSES-<система>.txt`, для десктоп-версий —
в `THIRD_PARTY_LICENSES-desktop-<система>.txt`. Эти файлы приложены к каждому релизу, собирает их `packaging/third_party.py`. В wheel, образе Docker и Flatpak лицензии пакетов лежат в их `dist-info`.

## Разработка

Код написан с помощью [Claude Code](https://claude.com/claude-code) (Anthropic), это видно по строкам `Co-Authored-By` в коммитах.

---

Что-то забыли или указали неверно? Откройте issue: исправим.
