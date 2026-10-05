# FO76 DB

Локальная база Fallout 76: каталог предметов с историей обновлений, инвентарь всех персонажей, легендарные моды,
схемы и события. Веб-интерфейс на `http://127.0.0.1:7676`.

Игру и пресеты утилита только читает (исключение — редактор правил IOM, только по подтверждению). Всё своё хранит в `data/`.

Начните с [инструкции пользователя](docs/manual.md); устройство — [карта приложения](docs/app-map.md). Подробная документация — в [`docs/`](docs/README.md) и на сайте [leanid3.github.io/fo76_db](https://leanid3.github.io/fo76_db/),
изменения — в [`CHANGELOG.md`](CHANGELOG.md). Готовые сборки — в [релизах](https://github.com/leanid3/fo76_db/releases/latest).

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/leanid3/fo76_db)

## Требования

- **Fallout 76** (Steam), установленный на этом компьютере. Из `Data/` читаются `SeventySix.esm` и `SeventySix - Localization.ba2`.
  Без игры каталог не собрать.
- **Моды для выгрузок** (по желанию, для инвентаря): [Invent-O-Matic Stash (Unofficial)](https://www.nexusmods.com/fallout76/mods/2335)
  с включённым Extract — инвентарь и тайник; [Improved Workbench](https://www.nexusmods.com/fallout76/mods/2576) — легендарные моды.
- **Интернет** для первого наполнения: релизы [fo76-dumps](https://github.com/fwdekker/fo76-dumps) (история — ~1 ГБ один раз), вики, события.
- **Система:** Windows 10/11 или Linux x86_64. Для запуска из исходников — Python ≥ 3.12 и 7-Zip (`7z`, `7zz` или `7za`).
  В готовые сборки Python уже входит, 7-Zip входит в Docker и Flatpak.

## Быстрый старт

Готовые файлы лежат в [последнем релизе](https://github.com/leanid3/fo76_db/releases/latest). Выберите вариант, запустите его,
откройте главную и в блоке **«Данные»** нажмите «Каталог», затем «История» и «События». Это первое наполнение базы,
командная строка для него не нужна. Подробности по каждому варианту — в [docs/packaging.md](docs/packaging.md).

| Вариант | Для кого | Как запустить |
|---|---|---|
| **Десктоп Windows** | окно без браузера | `fo76db-desktop-windows-x86_64.exe`, двойной клик |
| **Десктоп Linux** (Qt) | окно без браузера | `tar xzf fo76db-desktop-linux-x86_64.tar.gz && ./fo76db-desktop/fo76db-desktop`; ярлык в меню — `./fo76db-desktop/install-linux.sh` |
| **exe Windows** | в браузере, есть консоль | `fo76db-windows-x86_64.exe`, двойной клик: сервер и браузер; команды — `fo76db-windows-x86_64.exe catalog` |
| **Бинарник Linux** | в браузере, один файл | `chmod +x fo76db-linux-x86_64 && ./fo76db-linux-x86_64` (без аргументов — сервер и браузер) |
| **Flatpak** (любой Linux) | пункт меню, окно на Qt, песочница | `flatpak install --user --bundle fo76db-linux-x86_64.flatpak` (артефакт Actions сначала распаковать из zip), затем «FO76 DB» в меню или `flatpak run io.github.leanid3.fo76db` |
| **Arch / CachyOS** | нативный пакет, окно на системном Qt | `git clone ... && cd fo76_db/packaging/arch && makepkg -si`, затем «FO76 DB» в меню или `fo76db desktop` |
| **PWA** | приложение из браузера, телефон | при запущенном сервере: Chrome/Edge → «Установить FO76 DB»; телефон — через HTTPS и токен, [docs/pwa.md](docs/pwa.md) |
| **Docker** | сервер, NAS | `docker compose up -d` → `http://127.0.0.1:7676`; образ — `ghcr.io/leanid3/fo76db` |
| **Пакет Python** | есть Python | `pip install ./fo76db-<версия>-py3-none-any.whl`, затем `fo76db serve --open` (десктоп — `pip install "./fo76db-<версия>-py3-none-any.whl[desktop]"` и `fo76db desktop`) |
| **Из исходников** | разработка | ниже, «Установка из исходников» |
| **Codespaces** | разработка в браузере | кнопка «Open in GitHub Codespaces» выше. Файлов игры там нет, см. [docs/packaging.md](docs/packaging.md#codespaces) |

Где хранятся данные: из исходников — в папке репозитория, у всех сборок — `~/.local/share/fo76db` (Linux) или
`%LOCALAPPDATA%\fo76db` (Windows). Путь виден в блоке «Данные» на главной и в `fo76db --version`. Игра ищется автоматически (Steam, Proton, Xbox / Microsoft Store, Bethesda.net); если не нашлась — укажите папку в «Настройки → Пути игры»
или `game_data` в `config.toml` (образец — [config.toml.example](config.toml.example)).

## Установка из исходников

```sh
git clone https://github.com/leanid3/fo76_db.git ~/src/fo76db && cd ~/src/fo76db
python3 -m venv .venv
.venv/bin/pip install -e .            # десктоп-версия: .venv/bin/pip install -e ".[desktop]"
cp config.toml.example config.toml   # по желанию
```

## Команды

| Команда | Что делает |
|---|---|
| `.venv/bin/python -m fo76db catalog` | Каталог: список предметов, EditorID и названия EN/RU из установленной игры; вес, цена, эффекты, крафт, разбор, списки добычи и места в мире из последнего релиза fo76-dumps. ~1 мин |
| `.venv/bin/python -m fo76db history` | «Добавлено в обновлении» для всех предметов по ~140 стабильным версиям с 2019 года. Первый запуск ~15 мин и ~1 ГБ трафика, затем только новые версии |
| `.venv/bin/python -m fo76db history --relabel` | Только обновить названия обновлений по таблице патчей Fallout Wiki |
| `.venv/bin/python -m fo76db import` | Импорт инвентаря (`itemsmod.json`) и легендарных модов (`LegendaryMods.ini`) |
| `.venv/bin/python -m fo76db events` | Обновить календарь событий, Минерву и сезоны (falloutbuilds.com, fallout.wiki) |
| `.venv/bin/python -m fo76db watch` | Автоимпорт при изменении этих файлов, уведомления (`notify-send`) раз в 10 минут, обновление событий раз в 6 часов |
| `.venv/bin/python -m fo76db notify` | Разовая проверка уведомлений |
| `.venv/bin/python -m fo76db serve --watch` | Веб-интерфейс и слежение за выгрузками в одном процессе (то же — `serve_watch = true` в `config.toml`) |
| `.venv/bin/python -m fo76db backup [--out ПАПКА] [--keep N]` | Копия базы (теги, вишлист, роллы, чек-лист, история инвентаря) в `data/db-backups`, хранятся 10 последних |
| `.venv/bin/python -m fo76db doctor` | Проверка окружения: игра, моды, 7-Zip, база, доступ из сети; код выхода 1 при проблемах |
| `.venv/bin/python -m fo76db serve` | Веб-интерфейс (`--open` — открыть браузер; если уже запущен — только открыть страницу) |
| `.venv/bin/python -m fo76db openapi` | Выгрузить схему OpenAPI в `docs/openapi.json` (`-o файл`, `-o -` — в stdout); для своего фронтенда — [docs/api.md](docs/api.md) |
| `.venv/bin/python -m fo76db desktop` | Веб-интерфейс в отдельном окне и слежение за выгрузками (нужен `pip install -e ".[desktop]"`) |

После патча игры: `catalog`, затем `history`.

Без токена GitHub даёт 60 запросов API в час. Список релизов кэшируется на час. Если лимит мешает, задайте `GITHUB_TOKEN`.

## Страницы

Подробно — в [docs/user-guide.md](docs/user-guide.md).

| Страница | Что там |
|---|---|
| Главная | Карточки персонажей и итоги по категориям |
| Каталог | Все предметы игры: поиск RU/EN, фильтры, «добавлено в обновлении», «изучено» |
| Обновления | Что появилось в каждом обновлении, сколько схем изучено |
| Инвентарь | «Где лежит?» по всем персонажам, теги, свои имена, поиск по легендарным звёздам |
| Роллы | Нужные роллы легендарок: оценка «год-ролл / частично / на скрип», уведомления о новых совпадениях |
| Вес | Оптимизатор инвентаря и тайника: куда уходит вес и что убрать |
| Схемы | Изученные схемы по персонажам, массовая отметка; «Передать и продать» — кому отдать схемы из инвентаря |
| Легендарные моды | Матрица модов по персонажам |
| События | Сегодня (сбросы, сезон, идущие события), Daily Ops, чек-лист ежедневок, Минерва со схемами, календарь, уведомления |
| История | Снимки выгрузок и сравнение двух снимков |
| IOM | Редактор правил Invent-O-Matic ([docs/iom-editor.md](docs/iom-editor.md)) |
| ⚙ | Подписи и цвета персонажей, теги |

## Разработка

`pip install -e ".[dev]"`; `pytest`; `ruff check fo76db tests`. Подробности — `docs/architecture.md`.

## Данные

Список предметов и названия EN/RU берутся из установленной игры, статы и история — из [fwdekker/fo76-dumps](https://github.com/fwdekker/fo76-dumps),
названия обновлений — из Fallout Wiki. Инвентарь даёт Invent-O-Matic Stash (Extract), легендарные моды — Improved Workbench.
Источники, правила импорта и ограничения — в [docs/data.md](docs/data.md).

Идеи главной страницы, тегов, истории снимков и редактора правил IOM взяты из [Inventory Viewer](https://github.com/ButterflyTsting/inventory-viewer)
(VaultButterfly, Windows). У него нет лицензии, поэтому код не заимствован: здесь своя реализация.

## Благодарности

Все источники данных, моды, идеи и библиотеки со ссылками на оригиналы — в [CREDITS.md](CREDITS.md). Спасибо их авторам!

FO76 DB — неофициальная фанатская утилита, не связана с Bethesda Softworks. Файлы игры не распространяются: утилита читает установленную игру.

## Лицензия

Copyright © 2026 leanid3. [GNU AGPL v3 или новее](LICENSE) (`AGPL-3.0-or-later`) — открытая лицензия (OSI, FSF). Кратко (юридическую силу имеет английский текст):

- **можно** — пользоваться для любых целей, изучать, изменять, дорабатывать, распространять копии и изменённые версии, брать код
  в свои проекты;
- **нужно** — изменённые версии и проекты, в которые вошёл код, распространять тоже под AGPL, с исходным кодом и сохранением
  копирайтов. Это касается и случая, когда изменённую версию запускают как веб-сервис для других людей: им нужно дать
  ссылку на исходный код (в интерфейсе она есть — внизу страницы);
- **нельзя** — закрыть код производной версии.
