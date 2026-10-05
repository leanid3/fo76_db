"""HTTP-запросы с быстрым перебором адресов.

У некоторых сайтов (fallout.wiki) несколько IP-адресов, и часть из них отсюда не отвечает. Обычный urllib подключается
к адресам по очереди с полным таймаутом на каждый, и запрос висит 15–30 секунд. Здесь на подключение к одному адресу
даётся `CONNECT_TIMEOUT`, а адрес, который ответил, запоминается и в следующий раз пробуется первым.
"""
from __future__ import annotations

import http.client
import socket
import urllib.request

CONNECT_TIMEOUT = 3.0
_good: dict[tuple[str, int], str] = {}


def _connect(address: tuple[str, int], timeout, source_address=None, **_):
    host, port = address
    ips = list(dict.fromkeys(ai[4][0] for ai in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    if (ip := _good.get(address)) in ips:
        ips.remove(ip)
        ips.insert(0, ip)
    err: OSError | None = None
    for ip in ips:
        try:
            sock = socket.create_connection((ip, port), CONNECT_TIMEOUT, source_address)
        except OSError as e:
            err = e
            continue
        sock.settimeout(timeout)
        _good[address] = ip
        return sock
    raise err or OSError(f"нет адресов для {host}")


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


_opener = urllib.request.build_opener(_HTTPSHandler)


def get(url: str, headers: dict | None = None, timeout: float = 30) -> str:
    with _opener.open(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")
