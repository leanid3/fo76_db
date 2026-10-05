# FO76 DB в контейнере. Данные (база, кэш, config.toml) — в томе /data, папка Data игры — только чтение в /game/Data.
# Сборка: docker build -t fo76db .     Запуск: docker compose up -d   (см. compose.yaml и docs/packaging.md)
FROM python:3.14-slim AS build
WORKDIR /src
COPY pyproject.toml requirements.lock README.md LICENSE CREDITS.md ./
COPY fo76db ./fo76db
# зависимости — строго по requirements.lock (версии и sha256), само приложение — без зависимостей
RUN pip wheel --no-cache-dir --wheel-dir /wheels --require-hashes -r requirements.lock \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.14-slim
# 7zip — распаковка архивов fo76-dumps (команды catalog и history)
RUN apt-get update && apt-get install -y --no-install-recommends 7zip \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels /wheels/*.whl && rm -rf /wheels \
    && useradd --uid 1000 --create-home fo76 && mkdir -p /data && chown fo76 /data
USER fo76
ENV FO76DB_HOME=/data \
    FO76DB_GAME_DATA=/game/Data \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 7676
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7676/healthz', timeout=4)" || exit 1
ENTRYPOINT ["fo76db"]
CMD ["serve", "--host", "0.0.0.0"]
