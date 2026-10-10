"""Dono único da sessão MCP (stdio) com o bolsai-mcp.

A sessão inteira (abrir, usar, fechar) vive dentro de UMA task supervisora.
Isso evita o erro "Attempted to exit cancel scope in a different task".
"""
import asyncio
import logging
import os
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bfa.config import Settings
from bfa.errors import ErrorCode

log = logging.getLogger("bfa.gateway")

EXPECTED_TOOLS = [
    "get_stock_quote", "get_fundamentals", "compare_stocks", "get_dividends",
    "search_companies", "get_price_history", "get_fii_details",
    "get_macro_indicator", "get_financial_statements", "screen_stocks",
]


class GatewayError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Gateway(Protocol):
    """Interface usada pelo service (facilita o FakeGateway nos testes)."""

    @property
    def ready(self) -> bool: ...

    @property
    def manifest(self) -> list[dict[str, Any]]: ...

    @property
    def missing_tools(self) -> list[str]: ...

    @property
    def last_error(self) -> str | None: ...

    async def call_tool(self, name: str, args: dict[str, Any]) -> str: ...


class MCPGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._session: ClientSession | None = None
        self._sem = asyncio.Semaphore(settings.MCP_MAX_CONCURRENCY)
        self._manifest: list[dict[str, Any]] = []
        self._missing: list[str] = list(EXPECTED_TOOLS)
        self._last_error: str | None = None

    # --- propriedades públicas ---
    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    @property
    def manifest(self) -> list[dict[str, Any]]:
        return self._manifest

    @property
    def missing_tools(self) -> list[str]:
        return self._missing

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # --- ciclo de vida ---
    async def start(self) -> None:
        if not self.settings.BOLSAI_API_KEY:
            self._last_error = "BOLSAI_API_KEY não definida; sessão MCP não iniciada."
            log.warning(self._last_error)
            return
        self._task = asyncio.create_task(self._supervisor(), name="mcp-supervisor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            except Exception:  # noqa: BLE001
                log.exception("Erro ao encerrar a sessão MCP")

    async def _supervisor(self) -> None:
        """Mantém a sessão viva; reconecta com backoff (1s, 2s, 4s... máx 30s)."""
        backoff = 1
        env = {**os.environ, "BOLSAI_API_KEY": self.settings.BOLSAI_API_KEY or ""}
        params = StdioServerParameters(
            command=self.settings.MCP_COMMAND, args=self.settings.MCP_ARGS, env=env
        )
        while not self._stop.is_set():
            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        await self._load_manifest(session)
                        self._session = session
                        self._last_error = None
                        self._ready.set()
                        backoff = 1
                        log.info("Sessão MCP pronta (%d tools).", len(self._manifest))
                        await self._stop.wait()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                # o anyio embrulha a causa real em ExceptionGroup; mostra a mais interna
                while isinstance(e, BaseExceptionGroup) and e.exceptions:
                    e = e.exceptions[0]
                self._last_error = f"{type(e).__name__}: {e}"
                log.warning("Sessão MCP caiu: %s", self._last_error)
            finally:
                self._ready.clear()
                self._session = None
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 30)

    async def _load_manifest(self, session: ClientSession) -> None:
        result = await session.list_tools()
        self._manifest = [
            {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in result.tools
        ]
        nomes = {t["name"] for t in self._manifest}
        self._missing = [n for n in EXPECTED_TOOLS if n not in nomes]
        if self._missing:
            log.warning("Tools ausentes no servidor MCP: %s", self._missing)

    # --- chamada de tools ---
    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        if self._task is None:  # sessão nunca iniciada (ex.: sem BOLSAI_API_KEY): falha rápido
            raise GatewayError(ErrorCode.upstream_unavailable, self._last_error or "Sessão MCP não iniciada.")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self.settings.MCP_READY_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise GatewayError(
                ErrorCode.upstream_unavailable,
                self._last_error or "Sessão MCP indisponível.",
            )
        session = self._session
        if session is None:
            raise GatewayError(ErrorCode.upstream_unavailable, "Sessão MCP indisponível.")
        async with self._sem:
            try:
                result = await asyncio.wait_for(
                    session.call_tool(name, args), timeout=self.settings.MCP_CALL_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                raise GatewayError(ErrorCode.timeout, f"Timeout chamando {name}.")
            except Exception as e:  # noqa: BLE001
                raise GatewayError(ErrorCode.upstream_unavailable, f"{type(e).__name__}: {e}")
        texto = "\n".join(
            c.text for c in result.content if getattr(c, "type", None) == "text"
        ).strip()
        if result.isError:
            raise GatewayError(ErrorCode.upstream_error, texto or "Erro desconhecido do MCP.")
        return texto or "Nenhum dado retornado."
