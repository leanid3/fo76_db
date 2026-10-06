"""SQLite: схема и подключение."""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
from pathlib import Path


def _home() -> Path:
    """Папка с config.toml и data/.

    FO76DB_HOME, если задана (Docker: /data). Запуск из исходников (рядом лежит pyproject.toml) — корень репозитория.
    Иначе (бинарник, exe, wheel, Flatpak) — папка пользователя: ~/.local/share/fo76db (во Flatpak —
    ~/.var/app/<id>/data/fo76db), %LOCALAPPDATA%\\fo76db."""
    if env := os.environ.get("FO76DB_HOME"):
        return Path(env).expanduser()
    src = Path(__file__).resolve().parent.parent
    if not getattr(sys, "frozen", False) and (src / "pyproject.toml").is_file():
        return src
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "fo76db"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "fo76db"


ROOT = _home()
DATA = ROOT / "data"
DB_PATH = DATA / "fo76.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- Версии игры (релизы fo76-dumps)
CREATE TABLE IF NOT EXISTS builds (
    tag         TEXT PRIMARY KEY,      -- v4.6.0-v1.7.26.22
    version     TEXT NOT NULL,         -- 1.7.26.22
    vkey        TEXT NOT NULL,         -- ключ сортировки версии
    date        TEXT,
    is_pts      INTEGER NOT NULL,
    update_name TEXT,
    released    TEXT,                  -- дата выхода патча по вики
    processed   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
    formid       INTEGER PRIMARY KEY,
    sig          TEXT NOT NULL,        -- WEAP, ARMO, ALCH, BOOK ...
    edid         TEXT,
    name_en      TEXT,
    name_ru      TEXT,
    kind         TEXT NOT NULL,        -- weapon, armor, apparel, consumable, plan, recipe, ...
    subkind      TEXT,
    weight       REAL,
    value        INTEGER,
    keywords     TEXT,                 -- через пробел
    stats        TEXT,                 -- JSON
    status       TEXT NOT NULL,        -- ok | unused
    added_build  TEXT REFERENCES builds(tag),
    removed_build TEXT REFERENCES builds(tag)
);
CREATE INDEX IF NOT EXISTS items_kind ON items(kind);
CREATE INDEX IF NOT EXISTS items_name_en ON items(name_en COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS items_name_ru ON items(name_ru COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS recipes (
    cobj        INTEGER PRIMARY KEY,
    edid        TEXT,
    product     INTEGER,               -- formid результата
    plan        INTEGER,               -- formid схемы/рецепта (BOOK) или требуемого предмета
    components  TEXT                   -- JSON [{formid, name, count}]
);
CREATE INDEX IF NOT EXISTS recipes_product ON recipes(product);
CREATE INDEX IF NOT EXISTS recipes_plan ON recipes(plan);

-- Где встречается в списках добычи (LVLI)
CREATE TABLE IF NOT EXISTS lvli_refs (
    formid INTEGER NOT NULL,
    lvli   TEXT NOT NULL,
    PRIMARY KEY (formid, lvli)
) WITHOUT ROWID;

-- Граф списков добычи для «Как получить»: все списки и рёбра «предмет/список → список, в который он входит»
CREATE TABLE IF NOT EXISTS lvli (
    formid INTEGER PRIMARY KEY,
    edid   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lvli_edges (
    child  INTEGER NOT NULL,
    parent INTEGER NOT NULL,
    PRIMARY KEY (child, parent)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS lvli_edges_parent ON lvli_edges(parent);

-- Где предмет или список добычи стоит в мире (*_LOC.csv из fo76-dumps), по ячейкам
CREATE TABLE IF NOT EXISTS placements (
    formid INTEGER NOT NULL,
    cell   TEXT NOT NULL,               -- понятное название ячейки
    world  TEXT,                        -- мир (Appalachia и т.п.), NULL — интерьер
    n      INTEGER NOT NULL,
    PRIMARY KEY (formid, cell)
) WITHOUT ROWID;

-- Кэш раздела «Locations» со страниц fallout.wiki
CREATE TABLE IF NOT EXISTS wiki_obtain (
    key     TEXT PRIMARY KEY,           -- formid предмета
    title   TEXT,                       -- NULL — страница не нашлась
    html    TEXT,
    fetched TEXT NOT NULL
);

-- Инвентарь
CREATE TABLE IF NOT EXISTS characters (
    id       INTEGER PRIMARY KEY,
    account  TEXT NOT NULL,
    name     TEXT NOT NULL,
    info     TEXT,                     -- JSON CharacterInfoData/AccountInfoData
    UNIQUE (account, name)
);

CREATE TABLE IF NOT EXISTS inv_snapshots (
    id           INTEGER PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    taken_at     TEXT NOT NULL,
    source       TEXT NOT NULL,
    digest       TEXT NOT NULL,
    UNIQUE (character_id, digest)
);

CREATE TABLE IF NOT EXISTS inv_items (
    snapshot_id INTEGER NOT NULL REFERENCES inv_snapshots(id) ON DELETE CASCADE,
    container   TEXT NOT NULL,         -- player | stash
    name        TEXT NOT NULL,
    category    TEXT,                  -- itemCategory / filterFlag в человекочитаемом виде
    formid      INTEGER,               -- сопоставление с items, если найдено
    count       INTEGER NOT NULL,
    weight      REAL,
    value       INTEGER,
    level       INTEGER,
    stars       INTEGER NOT NULL DEFAULT 0,
    legendary   TEXT,                  -- эффекты через ' / '
    learned     INTEGER,               -- isLearnedRecipe для схем
    equipped    INTEGER NOT NULL DEFAULT 0,
    raw         TEXT
);
CREATE INDEX IF NOT EXISTS inv_items_snap ON inv_items(snapshot_id);
CREATE INDEX IF NOT EXISTS inv_items_formid ON inv_items(formid);

CREATE TABLE IF NOT EXISTS known_legendary_mods (
    character_id INTEGER NOT NULL REFERENCES characters(id),
    name         TEXT NOT NULL,
    stars        INTEGER,
    count        INTEGER,
    learned      INTEGER NOT NULL DEFAULT 0,
    description  TEXT,                 -- JSON {weapons, armor, all}
    name_local   TEXT,                 -- название в клиенте персонажа, если отличается от английского
    taken_at     TEXT,                 -- время изменения файла LegendaryMods.ini
    PRIMARY KEY (character_id, name, stars)
);

CREATE TABLE IF NOT EXISTS known_recipes (
    character_id INTEGER NOT NULL REFERENCES characters(id),
    formid       INTEGER NOT NULL,
    source       TEXT NOT NULL,        -- auto | manual
    PRIMARY KEY (character_id, formid)
);
CREATE INDEX IF NOT EXISTS known_recipes_formid ON known_recipes(formid);  -- «кто выучил» по предмету, а не по персонажу

-- Профили, теги, отображаемые имена (идеи Inventory Viewer)
CREATE TABLE IF NOT EXISTS profiles (
    character_id INTEGER PRIMARY KEY REFERENCES characters(id),
    label        TEXT,                 -- понятное имя персонажа
    color        TEXT                  -- #rrggbb
);
CREATE TABLE IF NOT EXISTS account_labels (
    account TEXT PRIMARY KEY,
    label   TEXT,
    color   TEXT
);
CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    color TEXT,
    icon  TEXT
);
-- Ключ предмета: name|stars|legendary — не зависит от снимка, тег переживает новые выгрузки
CREATE TABLE IF NOT EXISTS item_tags (
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    key    TEXT NOT NULL,
    PRIMARY KEY (tag_id, key)
) WITHOUT ROWID;
-- Автотеги по каталогу (fo76db/autotags.py): пересчитываются целиком
CREATE TABLE IF NOT EXISTS item_auto_tags (
    formid INTEGER NOT NULL,
    tag    TEXT NOT NULL,
    PRIMARY KEY (formid, tag)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS item_auto_tags_tag ON item_auto_tags(tag);
CREATE TABLE IF NOT EXISTS display_names (
    key  TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_searches (
    id     INTEGER PRIMARY KEY,
    page   TEXT NOT NULL,              -- путь страницы: /, /inventory, /plans
    name   TEXT NOT NULL,
    params TEXT NOT NULL,              -- строка запроса без '?'
    UNIQUE (page, name)
);

-- События
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,          -- season | seasonal_event | minerva | dailyops | doublexp | other
    title      TEXT NOT NULL,
    start      TEXT NOT NULL,
    end        TEXT,
    source_url TEXT,
    note       TEXT
);
CREATE INDEX IF NOT EXISTS events_start ON events(start);

-- Схемы распродаж Минервы (falloutbuilds.com), перезаписываются при обновлении событий
CREATE TABLE IF NOT EXISTS minerva_plans (
    sale    INTEGER NOT NULL,
    name_en TEXT NOT NULL,
    formid  INTEGER,                   -- NULL: не нашлось в каталоге
    PRIMARY KEY (sale, name_en)
);

-- Чек-лист ежедневок: пункты и отметки за период (дата последнего сброса дня или недели)
CREATE TABLE IF NOT EXISTS daily_tasks (
    id       INTEGER PRIMARY KEY,
    title    TEXT NOT NULL,
    reset    TEXT NOT NULL DEFAULT 'daily',   -- daily | weekly
    per_char INTEGER NOT NULL DEFAULT 1,      -- 0: одна отметка на всех
    sort     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS daily_done (
    task_id      INTEGER NOT NULL REFERENCES daily_tasks(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL,            -- 0 для пунктов без персонажа
    period       TEXT NOT NULL,
    done_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (task_id, character_id, period)
);

-- Нужные роллы легендарок (fo76db/rolls.py): шаблоны эффектов по звёздам и уже показанные совпадения
CREATE TABLE IF NOT EXISTS leg_wants (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    scope   TEXT NOT NULL DEFAULT 'any',      -- any | weapon | armor
    s1 TEXT, s2 TEXT, s3 TEXT, s4 TEXT,       -- шаблон эффекта звезды; NULL — любой
    notify  INTEGER NOT NULL DEFAULT 1,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS leg_want_seen (
    want_id INTEGER NOT NULL REFERENCES leg_wants(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,                    -- character_id|ключ предмета
    PRIMARY KEY (want_id, key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS wishlist (
    formid INTEGER PRIMARY KEY,
    note   TEXT,
    added  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Steam: новости игры (patch = 1 — Update Notes) и замеры онлайна (копятся с первого запуска watch)
CREATE TABLE IF NOT EXISTS steam_news (
    gid       TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    date      TEXT NOT NULL,           -- местное время ГГГГ-ММ-ДДTЧЧ:ММ
    url       TEXT,
    feedlabel TEXT,
    patch     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS steam_news_date ON steam_news(date);
CREATE TABLE IF NOT EXISTS steam_achievements (
    sort     INTEGER PRIMARY KEY,      -- позиция в выдаче Steam (по убыванию процента)
    api_name TEXT,                     -- ACHIEVEMENT_N; NULL — сопоставить с API не удалось
    title    TEXT NOT NULL,
    descr    TEXT,
    percent  REAL NOT NULL             -- процент игроков, получивших достижение
);
CREATE TABLE IF NOT EXISTS online_samples (
    ts      TEXT PRIMARY KEY,          -- местное время ГГГГ-ММ-ДДTЧЧ:ММ:СС
    players INTEGER NOT NULL
) WITHOUT ROWID;
"""


_ready: set[Path] = set()  # базы, схему которых этот процесс уже проверил
_init_lock = threading.Lock()


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Соединение с базой. Схема и миграции проверяются один раз на процесс (раньше — на каждый запрос веб-интерфейса).
    Ожидание блокировки — до 30 с: serve, watch и фоновые задачи пишут в одну базу."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 30000")
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA synchronous = NORMAL")  # безопасно в WAL, заметно быстрее записи
    if path not in _ready or not path.exists():
        with _init_lock:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(SCHEMA)
            _migrate(con)
            _ready.add(path)
    return con


# Колонки, добавленные после первой версии схемы: (таблица, колонка, определение)
MIGRATIONS = (
    ("builds", "released", "TEXT"),
    ("known_legendary_mods", "taken_at", "TEXT"),
    ("inv_snapshots", "archived", "INTEGER NOT NULL DEFAULT 0"),
    ("events", "source", "TEXT"),    # NULL — внесено вручную; falloutbuilds | wiki | dailyops
    ("events", "ext_key", "TEXT"),   # стабильный ключ автособытия (для уведомлений)
    ("events", "data", "TEXT"),      # JSON: распродажа Минервы, параметры Daily Ops
    ("wiki_obtain", "url", "TEXT"),
    ("wiki_obtain", "wiki", "TEXT"),  # fallout.fandom.com | fallout.wiki
    ("wiki_obtain", "ru_title", "TEXT"),  # русская страница fandom
    ("wiki_obtain", "ru_url", "TEXT"),
    ("wiki_obtain", "ru_html", "TEXT"),
    ("wiki_obtain", "ru_checked", "INTEGER"),  # 1 — русскую страницу уже искали (старые записи без неё перечитываются)
    ("profiles", "mule", "INTEGER NOT NULL DEFAULT 0"),  # 1 — персонаж-склад: схемы ему не предлагаются
)


def _migrate(con: sqlite3.Connection) -> None:
    for table, column, decl in MIGRATIONS:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e):  # параллельный процесс (serve + watch) успел раньше
                    raise
    # Вес в тайнике: раньше писался вес с учётом перков, игра же считает тайник по weightInStash
    if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'meta'").fetchone() and not get_meta(con, "fix_stash_weight"):
        con.execute("UPDATE inv_items SET weight = json_extract(raw, '$.weightInStash')"
                    " WHERE container = 'stash' AND json_extract(raw, '$.weightInStash') IS NOT NULL")
        set_meta(con, "fix_stash_weight", "1")
        con.commit()
    if not con.execute("SELECT 1 FROM daily_tasks LIMIT 1").fetchone() and not get_meta(con, "daily_tasks_seeded"):
        con.executemany("INSERT INTO daily_tasks(title, reset, per_char, sort) VALUES (?, ?, ?, ?)", DEFAULT_DAILY_TASKS)
        set_meta(con, "daily_tasks_seeded", "1")
        con.commit()


# Начальный чек-лист: (название, сброс, по персонажам, порядок)
DEFAULT_DAILY_TASKS = [
    ("Ежедневные испытания (S.C.O.R.E.)", "daily", 1, 10),
    ("Daily Ops", "daily", 1, 20),
    ("Легендарки → скрип (автомат обмена)", "daily", 1, 30),
    ("Казначейские билеты → золото", "daily", 1, 40),
    ("Продать торговцам (1400 крышек)", "daily", 1, 50),
    ("Ежедневные квесты Фонда и Кратера", "daily", 1, 60),
    ("Еженедельные испытания (S.C.O.R.E.)", "weekly", 1, 100),
]


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def get_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None
