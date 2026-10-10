"""Cache TTL simples. Chave = (tool, argumentos ordenados). Erros não são cacheados."""
import time
from typing import Any

from cachetools import TTLCache


class ToolCache:
    def __init__(self, maxsize: int = 1024):
        # TTL por entrada: guardamos (expira_em, valor) num TTLCache com TTL máximo
        self._store: TTLCache = TTLCache(maxsize=maxsize, ttl=24 * 60 * 60)

    @staticmethod
    def key(tool: str, args: dict[str, Any]) -> tuple:
        return (tool, tuple(sorted((k, str(v)) for k, v in args.items() if v is not None)))

    def get(self, key: tuple) -> str | None:
        item = self._store.get(key)
        if item is None:
            return None
        expira_em, valor = item
        if time.monotonic() > expira_em:
            self._store.pop(key, None)
            return None
        return valor

    def set(self, key: tuple, value: str, ttl: int) -> None:
        self._store[key] = (time.monotonic() + ttl, value)
