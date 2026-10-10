"""Funções de domínio: normalizam argumentos, usam cache, chamam o gateway e montam o envelope."""
import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any

from bfa.cache import ToolCache
from bfa.config import Settings
from bfa.errors import ErrorCode, classify_mcp_text, is_empty_result
from bfa.mcp_gateway import Gateway, GatewayError
from bfa.schemas import ErrorInfo, ScreenRequest, SnapshotResult, ToolResult

TICKER_RE = re.compile(r"^[A-Z]{4}\d{1,2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MACRO_VALIDOS = ["selic", "selic_target", "ipca", "cdi", "usd_brl"]
MACRO_ALIASES = {
    "usdbrl": "usd_brl", "usd": "usd_brl", "dolar": "usd_brl", "dólar": "usd_brl",
    "dollar": "usd_brl", "selic meta": "selic_target", "selic_meta": "selic_target",
    "meta selic": "selic_target",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _erro(tool: str, code: ErrorCode, msg: str, t0: float | None = None) -> ToolResult:
    ms = int((time.perf_counter() - t0) * 1000) if t0 else 0
    return ToolResult(ok=False, tool=tool, error=ErrorInfo(code=code, message=msg),
                      latency_ms=ms, fetched_at=_now())


def normalize_ticker(ticker: str) -> str | None:
    t = ticker.strip().upper()
    return t if TICKER_RE.match(t) else None


def normalize_macro(indicator: str) -> str:
    i = indicator.strip().lower()
    return MACRO_ALIASES.get(i, i)


def parse_tickers(raw: list[str]) -> list[str] | None:
    """Aceita ['A,B'] ou ['A','B']; devolve lista normalizada ou None se inválida."""
    itens = [p for r in raw for p in r.split(",") if p.strip()]
    tickers = [normalize_ticker(p) for p in itens]
    if any(t is None for t in tickers):
        return None
    return tickers  # type: ignore[return-value]


class BFAService:
    def __init__(self, gateway: Gateway, cache: ToolCache, settings: Settings):
        self.gateway = gateway
        self.cache = cache
        self.settings = settings

    async def call(self, tool: str, args: dict[str, Any], ttl: int) -> ToolResult:
        """Chama uma tool do MCP com cache. Nunca levanta exceção: devolve ToolResult."""
        args = {k: v for k, v in args.items() if v is not None}
        key = self.cache.key(tool, args)
        t0 = time.perf_counter()
        hit = self.cache.get(key)
        if hit is not None:
            return ToolResult(ok=True, tool=tool, data=hit, cached=True,
                              latency_ms=int((time.perf_counter() - t0) * 1000),
                              fetched_at=_now())
        try:
            texto = await self.gateway.call_tool(tool, args)
        except GatewayError as e:
            return _erro(tool, e.code, e.message, t0)
        code = classify_mcp_text(texto)
        if code is not None:
            return _erro(tool, code, texto, t0)  # erros não são cacheados
        if not is_empty_result(texto):
            self.cache.set(key, texto, ttl)
        return ToolResult(ok=True, tool=tool, data=texto,
                          latency_ms=int((time.perf_counter() - t0) * 1000), fetched_at=_now())

    # --- rotas simples ---
    async def quote(self, ticker: str) -> ToolResult:
        t = normalize_ticker(ticker)
        if not t:
            return _erro("get_stock_quote", ErrorCode.invalid_input, f"Ticker inválido: {ticker!r}")
        return await self.call("get_stock_quote", {"ticker": t}, self.settings.TTL_QUOTE)

    async def fundamentals(self, ticker: str, reference_date: str | None) -> ToolResult:
        t = normalize_ticker(ticker)
        if not t:
            return _erro("get_fundamentals", ErrorCode.invalid_input, f"Ticker inválido: {ticker!r}")
        if reference_date and not DATE_RE.match(reference_date):
            return _erro("get_fundamentals", ErrorCode.invalid_input, "reference_date deve ser YYYY-MM-DD.")
        return await self.call("get_fundamentals", {"ticker": t, "reference_date": reference_date},
                               self.settings.TTL_FUNDAMENTALS)

    async def compare(self, tickers: list[str], metrics: str | None) -> ToolResult:
        lista = parse_tickers(tickers)
        if lista is None:
            return _erro("compare_stocks", ErrorCode.invalid_input, "Um ou mais tickers são inválidos.")
        if not 2 <= len(lista) <= 5:
            return _erro("compare_stocks", ErrorCode.invalid_input, "Informe de 2 a 5 tickers.")
        return await self.call("compare_stocks", {"tickers": ",".join(lista), "metrics": metrics},
                               self.settings.TTL_FUNDAMENTALS)

    async def dividends(self, ticker: str, years: int) -> ToolResult:
        t = normalize_ticker(ticker)
        if not t:
            return _erro("get_dividends", ErrorCode.invalid_input, f"Ticker inválido: {ticker!r}")
        return await self.call("get_dividends", {"ticker": t, "years": years},
                               self.settings.TTL_FUNDAMENTALS)

    async def companies(self, query: str | None, sector: str | None) -> ToolResult:
        return await self.call("search_companies", {"query": query, "sector": sector},
                               self.settings.TTL_COMPANIES)

    async def history(self, ticker: str, start: str | None, end: str | None, limit: int) -> ToolResult:
        t = normalize_ticker(ticker)
        if not t:
            return _erro("get_price_history", ErrorCode.invalid_input, f"Ticker inválido: {ticker!r}")
        for d in (start, end):
            if d and not DATE_RE.match(d):
                return _erro("get_price_history", ErrorCode.invalid_input, "Datas devem ser YYYY-MM-DD.")
        return await self.call("get_price_history",
                               {"ticker": t, "start": start, "end": end, "limit": limit},
                               self.settings.TTL_HISTORY)

    async def fii(self, ticker: str) -> ToolResult:
        t = normalize_ticker(ticker)
        if not t:
            return _erro("get_fii_details", ErrorCode.invalid_input, f"Ticker inválido: {ticker!r}")
        return await self.call("get_fii_details", {"ticker": t}, self.settings.TTL_FUNDAMENTALS)

    async def financials(self, ticker: str, statement_type: str, report_type: str,
                         reference_date: str | None) -> ToolResult:
        t = normalize_ticker(ticker)
        if not t:
            return _erro("get_financial_statements", ErrorCode.invalid_input, f"Ticker inválido: {ticker!r}")
        if reference_date and not DATE_RE.match(reference_date):
            return _erro("get_financial_statements", ErrorCode.invalid_input, "reference_date deve ser YYYY-MM-DD.")
        return await self.call("get_financial_statements",
                               {"ticker": t, "statement_type": statement_type,
                                "report_type": report_type, "reference_date": reference_date},
                               self.settings.TTL_FUNDAMENTALS)

    async def macro(self, indicator: str, limit: int) -> ToolResult:
        ind = normalize_macro(indicator)
        if ind not in MACRO_VALIDOS:
            return _erro("get_macro_indicator", ErrorCode.invalid_input,
                         f"Indicador inválido. Use um de: {', '.join(MACRO_VALIDOS)}")
        return await self.call("get_macro_indicator", {"indicator": ind, "limit": limit},
                               self.settings.TTL_MACRO)

    async def screen(self, req: ScreenRequest) -> ToolResult:
        if req.operator == "between" and req.value_upper is None:
            return _erro("screen_stocks", ErrorCode.invalid_input,
                         "Operador 'between' exige value_upper.")
        args = {"metric": req.metric.value, "operator": req.operator, "value": req.value,
                "value_upper": req.value_upper, "sector": req.sector, "limit": req.limit}
        return await self.call("screen_stocks", args, self.settings.TTL_SCREEN)

    # --- composto ---
    async def snapshot(self, ticker: str) -> SnapshotResult | ToolResult:
        t = normalize_ticker(ticker)
        if not t:
            return _erro("snapshot", ErrorCode.invalid_input, f"Ticker inválido: {ticker!r}")
        if t.endswith("11"):
            tipo, nomes = "fii", ["quote", "fii", "dividends"]
            coros = [self.quote(t), self.fii(t), self.dividends(t, 3)]
        else:
            tipo, nomes = "stock", ["quote", "fundamentals", "dividends"]
            coros = [self.quote(t), self.fundamentals(t, None), self.dividends(t, 3)]
        resultados = await asyncio.gather(*coros)  # falha parcial permitida (cada um é ToolResult)
        return SnapshotResult(ticker=t, asset_type=tipo, sections=dict(zip(nomes, resultados)))
