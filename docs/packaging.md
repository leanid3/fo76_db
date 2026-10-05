# Сборка и варианты установки

| Вариант | Для кого | Где взять |
|---|---|---|
| Из исходников | разработка, этот компьютер | `git clone` + `.venv` (см. `README.md`) |
| Пакет Python (wheel) | любая система с Python ≥ 3.12 | `pip install fo76db-*.whl` → команда `fo76db` |
| Бинарник Linux | Linux x86_64 без Python | один файл `fo76db-linux-x86_64` |
| exe Windows | Windows x86_64 без Python | один файл `fo76db-windows-x86_64.exe` |
| Десктоп Windows | окно без браузера (Edge WebView2) | один файл `fo76db-desktop-windows-x86_64.exe` |
| Десктоп Linux | окно без браузера (Qt WebEngine) | архив `fo76db-desktop-linux-x86_64.tar.gz` |
| PWA | приложение из браузера, телефон | установка со страницы, см. [pwa.md](pwa.md) |
| Flatpak | любой Linux: пункт меню, окно на Qt, песочница | `flatpak install --user --bundle fo76db-linux-x86_64.flatpak` |
| Arch / CachyOS | нативный пакет, окно на системном Qt, без своей копии Chromium | `cd packaging/arch && makepkg -si`, см. [Arch Linux](#arch-linux) |
| Docker | сервер, NAS, изоляция | `docker compose up -d` или образ `ghcr.io/<владелец>/fo76db` |
| Codespaces | разработка в браузере, без установки | кнопка «Code → Codespaces» на GitHub |

Есть сайт с описанием, загрузками и документацией: [leanid3.github.io/fo76_db](https://leanid3.github.io/fo76_db/) (GitHub Pages).

Готовые файлы собирает GitHub Actions (`.github/workflows/build.yml`), см. ниже.

## Где лежат данные

Папка с `config.toml` и `data/` (база, кэш fo76-dumps) выбирается так (`db._home()`):

1. переменная `FO76DB_HOME`, если задана (в Docker — `/data`);
2. запуск из исходников (рядом с пакетом лежит `pyproject.toml`) — корень репозитория, как раньше;
3. всё остальное (бинарник, exe, установленный wheel, Flatpak) — папка пользователя: `~/.local/share/fo76db` (Linux, учитывается
   `XDG_DATA_HOME`; во Flatpak это `~/.var/app/io.github.leanid3.fo76db/data/fo76db`), `%LOCALAPPDATA%\fo76db` (Windows).
   До 2026-10-04 установленный wheel хранил базу внутри `site-packages`.

`fo76db --version` показывает выбранную папку.

## Папка игры

Настройка `game_data` в `config.toml` — папка `Data` игры: оттуда читаются `SeventySix.esm`, `SeventySix - Localization.ba2`,
а пути выгрузок `inventory` и `legendary_mods` по умолчанию строятся от неё (`{game_data}/itemsmod.ini`). По умолчанию:

- Linux: первая существующая из `/games/SteamCommon/Fallout76/Data`, `~/.local/share/Steam/steamapps/common/Fallout76/Data`,
  `~/.steam/steam/steamapps/common/Fallout76/Data`, Steam из Flatpak (`~/.var/app/com.valvesoftware.Steam/...`);
- Windows: `C:/Program Files (x86)/Steam/steamapps/common/Fallout76/Data`.

Переменная `FO76DB_GAME_DATA` перекрывает `config.toml` (в Docker — `/game/Data`).

## Внешние программы

- **7-Zip** нужен командам `catalog` и `history` (архивы fo76-dumps). Ищется `7z`, `7zz`, `7za` в `PATH`, на Windows — ещё
  `C:\Program Files\7-Zip\7z.exe`. В образ Docker входит. Веб-интерфейсу и импорту инвентаря не нужен.
- **notify-send** — уведомления на Linux. Если его нет, используется `gdbus` (так во Flatpak). Нет ни того, ни другого (Windows, Docker) —
  уведомления только печатаются в журнал `watch`.

## Первый запуск

База пустая, её надо наполнить один раз (сеть, несколько минут; `history` в первый раз — дольше):

```sh
fo76db catalog      # каталог: игра + последний релиз fo76-dumps
fo76db history      # «добавлено в обновлении» по всем релизам
fo76db events       # события, Минерва, сезоны
fo76db serve --open # веб-интерфейс, http://127.0.0.1:7676
fo76db watch        # автоимпорт выгрузок (отдельным процессом)
```

**exe/бинарник двойным кликом** без аргументов запускает `serve --open`: сервер и браузер. Окно консоли — это журнал сервера,
закрытие окна останавливает сервер. Если сервер уже запущен (повторный двойной клик, пункт меню Flatpak), `serve` не падает на занятом
порту, а только открывает страницу.

## Бинарник и exe (PyInstaller)

```sh
python -m pip install ".[build]"
pyinstaller --noconfirm --clean packaging/fo76db.spec   # → dist/fo76db (или dist/fo76db.exe на Windows)
```

- `packaging/fo76db.spec` кладёт в файл `fo76db/web/static` и `templates`, все модули `fo76db` и `uvicorn` и `tzdata`.
- PyInstaller не собирает под другую систему: exe собирается на Windows (это делает Actions), бинарник Linux — на Linux.
  Бинарник Linux собирается на ubuntu-22.04, чтобы запускаться на дистрибутивах со старым glibc.
- Один файл распаковывается во временную папку при каждом запуске — старт 1–2 с.
- **Кодировка.** Exe запускается в UTF-8 mode (`X utf8_mode=1` в spec), а `cli.main()` переключает stdout/stderr на UTF-8.
  Без этого на Windows вывод в pipe или файл идёт в cp1252, и кириллица падает с `UnicodeEncodeError`.
- Windows SmartScreen может предупредить о неподписанном exe («Подробнее → Выполнить в любом случае»).
- **Лицензии.** В файл входят Python и библиотеки; их лицензии собирает `packaging/third_party.py` в `THIRD_PARTY_LICENSES-<система>.txt`,
  файл прикладывается к релизу (см. [CREDITS.md](../CREDITS.md)).

## Десктоп-версия

Тот же веб-интерфейс в собственном окне ([pywebview](https://pywebview.flowrl.com/)): без браузера, вкладок и адресной строки.
Сервер работает внутри программы на `127.0.0.1` и останавливается вместе с окном. Если FO76 DB уже запущен (`serve`, Docker),
окно открывается на нём.

| | Linux | Windows |
|---|---|---|
| Движок | Qt WebEngine (PySide6, Chromium внутри) | Microsoft Edge WebView2 — встроен в Windows 10/11 |
| Сборка | папка, архив `fo76db-desktop-linux-x86_64.tar.gz` (~200 МБ, в распакованном виде ~500 МБ: это Chromium) | один файл `fo76db-desktop-windows-x86_64.exe` |
| Запуск | `./fo76db-desktop/fo76db-desktop`, ярлык в меню — `./fo76db-desktop/install-linux.sh` | двойной клик |

- **Из исходников:** `pip install -e ".[desktop]"`, затем `fo76db desktop`. На Linux это поставит PySide6 (~600 МБ).
  `--no-watch` — без слежения за выгрузками.
- **Слежение за выгрузками** (`watch`) по умолчанию работает внутри десктоп-версии. Отключение: `desktop_watch = false` в `config.toml`.
- **Первое наполнение базы** — кнопки блока «Данные» на главной (каталог, история, события, импорт), командная строка не нужна.
- **Журнал** без консоли пишется в `data/app.log` (папка данных — как у бинарника). Журнал виден и в «Настройки → Журнал приложения»; `FO76DB_DESKTOP_LOG` больше не нужна
  (её ставят ярлыки Flatpak и Arch).
- **Хранилище окна** (localStorage: колонки, сохранённые поиски) — `data/webview/`.
- **Ссылки** с `target=_blank` (вики и др.) открываются в системном браузере; загрузки (экспорт CSV/JSON) разрешены.
- Тот же файл с аргументами работает как обычный `fo76db`: `fo76db-desktop catalog`. У exe Windows консоли нет, вывода не видно.
- **Сборка:** `pip install ".[desktop,build]" && pyinstaller --noconfirm --clean packaging/fo76db-desktop.spec`.
  Spec на Linux выбрасывает из Qt неиспользуемое (QML, 3D, PDF, переводы кроме ru/en, тему GTK).
  Системные библиотеки (`libstdc++`, `libgbm`, `libdrm`, GL/EGL, X11/xcb, glib/GTK, NSS, fontconfig и др., список `HOST_LIBS`)
  в сборку не кладутся — берутся из системы. Иначе библиотеки машины сборки (Ubuntu 22.04) конфликтуют с драйвером на свежих дистрибутивах.
- **Linux: окно падает с `SIGABRT`**, в выводе `GLIBCXX_… not found (required by …/libSPIRV-Tools.so)`, `QRhiGles2: Failed to create context`,
  `GLOzone not found` — сборка до 2026-10-04 со старым `libstdc++` внутри: системный Mesa не загружается, нет OpenGL. Скачайте новую сборку
  или удалите из старой системные библиотеки:
  `cd fo76db-desktop/_internal && rm -f libstdc++.so.6 libgcc_s.so.1 libgbm.so.1 libdrm.so.2 libexpat.so.1 libz.so.1`.
- **Лицензии:** Qt и PySide6 — LGPL-3.0. На Linux библиотеки Qt лежат отдельными файлами в папке, их можно заменить (требование LGPL).
  Тексты лицензий — `THIRD_PARTY_LICENSES-desktop-<система>.txt` в релизе.
- Окно во Flatpak и в пакете Arch — та же команда `desktop`: проверено на Wayland с Mesa.
- Проверено локально на Linux: сборка, загрузка страниц в окне Qt (без экрана, `QT_QPA_PLATFORM=offscreen`, и на Wayland с Mesa), свой сервер и его остановка
  при закрытии окна, работа поверх уже запущенного сервера. Windows-версию собирает и проверяет только Actions:
  `--version` и код выхода, окно WebView2 там не открывается.

## Flatpak

Подходит для любого дистрибутива: среду выполнения (freedesktop 25.08) пакет везёт с собой, системные библиотеки не нужны.
Пункт меню открывает окно на Qt (десктоп-версия), как `fo76db-desktop-linux`, но Qt и Chromium внутри пакета: он весит ~137 МБ,
на диске ~540 МБ. Во Flathub не публикуется: зависимости Python скачиваются при сборке, а Flathub требует сборку без сети.

```sh
unzip fo76db-linux-x86_64.flatpak-x86_64.zip                # только для артефакта Actions (он скачивается в zip); из релиза — сразу .flatpak
flatpak install --user --bundle fo76db-linux-x86_64.flatpak  # из папки с файлом; среду freedesktop 25.08 подтянет из flathub
flatpak run io.github.leanid3.fo76db                 # то же, что пункт меню «FO76 DB»: окно на Qt
flatpak run io.github.leanid3.fo76db serve --open    # вместо окна — сервер и браузер
flatpak run io.github.leanid3.fo76db catalog         # любые команды fo76db: catalog, history, events, watch, import ...
```

- **Пакет** (`packaging/flatpak/`): манифест `io.github.leanid3.fo76db.yml` (среда `org.freedesktop.Platform` 25.08, 7-Zip, fo76db через pip),
  ярлык, metainfo, иконка, скрипт `fo76db-launch` (без аргументов — `desktop`), `trim-qt.sh` (чистка PySide6 от ненужного: QML, 3D, PDF и др.).
  Из pip ставится `.[desktop]` (pywebview, QtPy, PySide6); `krb5` собирается из исходников, потому что `libQt6Network` требует
  `libgssapi_krb5`, а в среде freedesktop её нет.
- **Ярлык открывает окно без терминала.** Закрыли окно — сервер остановлен. Если FO76 DB уже запущен (`serve`), окно открывается на нём.
  Журнал запуска из меню: `~/.var/app/io.github.leanid3.fo76db/data/fo76db/data/app.log`. Принудительно остановить:
  `flatpak kill io.github.leanid3.fo76db`.
- **Песочница Chromium выключена** (`QTWEBENGINE_DISABLE_SANDBOX=1`): собственная песочница Chromium не работает внутри песочницы
  Flatpak, изоляцию даёт сам Flatpak. Окно получает Wayland/X11 и GPU (`--device=dri`).
- **«не является корректным именем» / «не найдено удаленных ссылок»** при установке: flatpak не нашёл файл (не та папка, файл ещё в zip,
  лишний символ в имени) и стал искать приложение во Flathub. С `--bundle` ошибка прямая — «файл не найден».
- **«Не удается загрузить зависимый файл https://flathub.org/repo/flathub.flatpakrepo … Timeout»**: flathub.org недоступен из вашей сети.
  Если среда `org.freedesktop.Platform//25.08` уже стоит (`flatpak list --runtime`) или Flathub подключён, ставьте без этого шага:
  `flatpak install --user --no-deps --bundle fo76db-linux-x86_64.flatpak`. Иначе сначала
  `flatpak install --user flathub org.freedesktop.Platform//25.08`. Пакеты, собранные после 2026-10-04, ссылаются на `dl.flathub.org`.
- **Данные**: `~/.var/app/io.github.leanid3.fo76db/data/fo76db` (база, кэш, `config.toml`).
- **Доступ к файлам** — только чтение папки игры в обычных местах Steam (`~/.local/share/Steam/...` и Steam из Flatpak). Другие пути
  открываются вручную:
  ```sh
  flatpak override --user --filesystem=/games:ro io.github.leanid3.fo76db                       # игра и выгрузки мультиклиента
  flatpak override --user --filesystem=/games/fallout76configs io.github.leanid3.fo76db          # редактор IOM (запись и бэкапы)
  ```
  Путь к игре вне этих мест задаётся `game_data` в `config.toml` или `flatpak override --user --env=FO76DB_GAME_DATA=<путь> ...`.
- **Сборка локально** (нужны `org.flatpak.Builder` и `org.freedesktop.Sdk//25.08` из flathub):
  ```sh
  flatpak run org.flatpak.Builder --user --force-clean --install-deps-from=flathub --repo=build/flatpak-repo \
      build/flatpak packaging/flatpak/io.github.leanid3.fo76db.yml
  flatpak build-bundle build/flatpak-repo fo76db-linux-x86_64.flatpak io.github.leanid3.fo76db
  ```
  Если сборщик пишет `Sdk ... not installed`, хотя среда стоит: песочница `org.flatpak.Builder` смотрит не в `~/.local/share/flatpak`.
  Запускайте с `--env=FLATPAK_USER_DIR=$HOME/.local/share/flatpak` и без `--install-deps-from`.
- 7-Zip и krb5 в пакете собраны из исходников/официальных архивов, версии и sha256 зашиты в манифест. При обновлении поменять оба.

## Arch Linux

Нативный пакет для Arch, CachyOS, Manjaro: Python-код и ярлык, а Qt, WebEngine и Python-библиотеки берутся из репозиториев системы.
Поэтому он занимает ~2 МБ, а окно использует тот же Qt, что и остальной рабочий стол. PKGBUILD собирает пакет из рабочей копии репозитория
(без сети, без `.git`, базы и окружения):

```sh
git clone git@github.com:leanid3/fo76_db.git && cd fo76_db/packaging/arch
makepkg -si          # соберёт fo76db-<версия>-1-any.pkg.tar.zst и установит; зависимости подтянет pacman
fo76db desktop       # или пункт меню «FO76 DB»; fo76db serve --open — в браузере
```

- **Зависимости**: `python-fastapi`, `uvicorn`, `python-jinja`, `python-tzdata`, `7zip`, `python-pywebview`, `python-qtpy`, `pyside6`,
  `qt6-webengine`, `qt6-webchannel`. В Arch `qt6-webengine` у `pyside6` необязательная зависимость, поэтому она указана явно.
- **Версия** берётся из `fo76db/__init__.py` (`pkgver()`), повторная сборка после обновления: `git pull && makepkg -si`.
- **Данные**: `~/.local/share/fo76db` (как у всех установленных сборок), журнал окна из меню — `data/app.log` там же.
- **Файлы пакета**: `/usr/bin/fo76db`, модуль в `site-packages/fo76db`, ярлык, иконки, metainfo, `LICENSE` и `CREDITS.md` в `/usr/share/licenses/fo76db`.
- Публиковать в AUR необязательно: PKGBUILD собирает локальную копию. Для AUR понадобится `source=()` с архивом релиза и контрольные суммы.
- Проверено: сборка пакета (`makepkg`), состав и зависимости, запуск установленного кода с данными в `XDG_DATA_HOME`, окно Qt.
  Установка пакета через `pacman` в проверку не входила (нужен root).

## Docker

```sh
docker compose up -d                        # web (http://127.0.0.1:7676) и watch
docker compose run --rm web catalog         # первое наполнение базы
docker compose run --rm web history
```

- **Образ** (`Dockerfile`): Python 3.14 slim, 7zip, пользователь с UID 1000, `ENTRYPOINT fo76db`, по умолчанию `serve --host 0.0.0.0`.
- **Тома** (`compose.yaml`; пути меняются через `.env`: `FO76DB_DATA`, `FO76_GAME_DATA`):
  - `./data-docker` → `/data` — база, кэш, `config.toml`;
  - папка `Data` игры → `/game/Data` только для чтения;
- **Порт** опубликован только на `127.0.0.1`: в утилите нет авторизации.
- **Редактор IOM** в Docker пишет только в смонтированный файл: чтобы он работал, смонтируйте конфиг Invent-O-Matic на запись и
  укажите `iom_config` и `backup_root` в `/data/config.toml`. По умолчанию он недоступен (файла нет).
- Существующую базу можно перенести: `sqlite3 data/fo76.sqlite ".backup data-docker/data/fo76.sqlite"`.
- **Готовый образ вместо сборки:**
  - из registry: `docker pull ghcr.io/leanid3/fo76db:latest` (или `:<версия>`), в `.env` — `FO76DB_IMAGE=ghcr.io/leanid3/fo76db:latest`,
    затем `docker compose up -d --no-build`. Пакет приватного репозитория тоже приватный: сначала
    `docker login ghcr.io` (логин GitHub и токен с правом `read:packages`);
  - файлом, без registry: `fo76db-docker-image.tar.gz` из релиза или артефактов запуска →
    `gunzip -c fo76db-docker-image.tar.gz | docker load` (образ `fo76db:latest`).

## Сайт (GitHub Pages)

Сайт [leanid3.github.io/fo76_db](https://leanid3.github.io/fo76_db/) состоит из двух частей (workflow `.github/workflows/pages.yml`):

- **Лендинг** — `packaging/pages/site/` (`index.html`, `img/`, иконки): описание, возможности, скриншоты, таблица загрузок, быстрый старт. Один HTML-файл без сборщика и внешних ресурсов; версия и размеры файлов подтягиваются из GitHub API (`releases/latest`), без сети остаются прямые ссылки на `releases/latest/download/<файл>`. Скриншоты — только общие данные игры (каталог, карточка, обновления), без персонажей; обновлять: headless-Chromium по запущенному `serve`.
- **Документация** — в `/docs/`: `README.md`, `docs/`, `CHANGELOG.md`, `CREDITS.md`, `LICENSE` через MkDocs + тема Material.

Правила:

- **Только описание и документация.** Pages — статический хостинг: запустить там fo76db нельзя (нужны сервер Python, база и файлы игры).
- **Включить один раз:** Settings → Pages → Source: «GitHub Actions».
- Сайт пересобирается при push в `main`, если менялись документы, лендинг или `mkdocs.yml`, и вручную (Run workflow).
- `packaging/pages/prepare.py` собирает страницы документации в `build/pages-src`: README становится главной (с блоком «Скачать»), относительные ссылки ведут на страницы сайта или на файлы в репозитории. `mkdocs build --strict` кладёт их в `build/site/docs`, затем лендинг копируется в корень `build/site`.
- Локально: `pip install "mkdocs<2" mkdocs-material && python packaging/pages/prepare.py && mkdocs build && cp -r packaging/pages/site/. build/site/`, затем `python -m http.server -d build/site`. MkDocs держим на 1.x: 2.0 несовместим с темой Material.

## Codespaces

`.devcontainer/devcontainer.json` — среда разработки в браузере (GitHub → Code → Codespaces → Create) или в VS Code Dev Containers:
Python 3.14, 7-Zip, sqlite3, `.venv` с `pip install -e ".[build]"`, порт 7676 открывается в браузере.

- **Это среда разработки, а не демо с данными.** Файлов игры там нет, поэтому `catalog` не сработает. Чтобы наполнить каталог, загрузите
  в папку `game-data/` (она в `.gitignore`) `SeventySix.esm` и `SeventySix - Localization.ba2` — около 1 ГБ.
  Без них работают `events`, веб-интерфейс, сборка (`pyinstaller`, `python -m build`) и сайт документации.
- Запуск: `.venv/bin/python -m fo76db serve`. Codespaces перенаправляет порт сам, ссылка появится во всплывающем окне.
- Codespaces для личных аккаунтов бесплатен в пределах месячной квоты GitHub; работает и с приватным репозиторием.

## GitHub Actions (`.github/workflows/build.yml`)

| Задача | Что делает |
|---|---|
| `wheel` | `python -m build` → wheel и sdist, проверка установки |
| `binary` | PyInstaller на ubuntu-22.04 и windows-latest; проверка: `--version`, запуск `serve`, `/home` и `/static/app.js` отвечают; `THIRD_PARTY_LICENSES-<система>.txt` |
| `desktop` | Десктоп-версия: ubuntu-22.04 → `fo76db-desktop-linux-x86_64.tar.gz`, windows-latest → `fo76db-desktop-windows-x86_64.exe`; лицензии `THIRD_PARTY_LICENSES-desktop-<система>.txt` |
| `flatpak` | Контейнер flathub-infra (freedesktop 25.08). Не запускается на pull request. Файл `fo76db-linux-x86_64.flatpak` собирается только на теге `v*` и вручную (сжатие ≈4 мин); на push в `main` — проверочная сборка без файла. Кэш по манифесту: krb5 и 7-Zip не пересобираются (холодная сборка ≈9 мин, с кэшем ≈3 мин, с файлом +4 мин) |
| `docker` | Сборка образа; на `master`/`main` и тегах `v*` — публикация в `ghcr.io/<владелец>/fo76db` (теги: версия и `latest` на `v*`, имя ветки, `sha-…`). Тот же образ файлом — артефакт `fo76db-docker-image.tar.gz`. Команды `docker pull` — в сводке запуска |
| `release` | На теге `v*`: GitHub Release с wheel, бинарником, exe, десктоп-версиями, Flatpak, образом Docker файлом, лицензиями сторонних компонентов, `LICENSE` и `CREDITS.md`. Скачиваются только артефакты `fo76db-*` |

- Запуск: push в `master`/`main`, pull request, тег `v*`, вручную (Run workflow).
- **Выпуск версии:** поднять `__version__` в `fo76db/__init__.py`, запись в `CHANGELOG.md`, затем `git tag v<версия> && git push --tags`.
- Репозиторий: `github.com/leanid3/fo76_db` (remote `origin`). Для публикации образа токен `GITHUB_TOKEN` получает права `packages: write`
  внутри workflow, отдельные секреты не нужны.

## Фиксация зависимостей

`requirements.lock` — версии и sha256 всех зависимостей для всех платформ; Docker-образ ставит из него (`pip wheel --require-hashes`), затем собирает само приложение без зависимостей. Обновить: `uv pip compile pyproject.toml --universal --generate-hashes -o requirements.lock` и пересобрать образ. Обновления сам не подтягивает — делайте это осознанно (dependabot не обновляет этот файл).
