"""BFA (Backend For Agents): API HTTP que fala com o bolsai-mcp por uma sessão MCP única."""
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from bfa.cache import ToolCache
from bfa.config import Settings, get_settings
from bfa.errors import HTTP_STATUS
from bfa.mcp_gateway import Gateway, MCPGateway
from bfa.schemas import ScreenRequest, SnapshotResult, ToolResult
from bfa.service import BFAService

log = logging.getLogger("bfa.api")

# Mapa tool MCP -> rota do BFA (usado em /v1/tools)
ROTAS = {
    "get_stock_quote": "/v1/b3/quote/{ticker}",
    "get_fundamentals": "/v1/b3/fundamentals/{ticker}",
    "compare_stocks": "/v1/b3/compare",
    "get_dividends": "/v1/b3/dividends/{ticker}",
    "search_companies": "/v1/b3/companies",
    "get_price_history": "/v1/b3/history/{ticker}",
    "get_fii_details": "/v1/b3/fii/{ticker}",
    "get_macro_indicator": "/v1/macro/{indicator}",
    "get_financial_statements": "/v1/b3/financials/{ticker}",
    "screen_stocks": "/v1/b3/screen",
}


# --- dependências (sobrescreva get_gateway nos testes) ---
def get_gateway(request: Request) -> Gateway:
    return request.app.state.gateway


def get_service(request: Request, gateway: Gateway = Depends(get_gateway)) -> BFAService:
    return BFAService(gateway, request.app.state.cache, request.app.state.settings)


def verify_key(request: Request, x_bfa_key: str | None = Header(default=None)) -> None:
    esperado = request.app.state.settings.BFA_API_KEY
    if esperado and x_bfa_key != esperado:
        raise HTTPException(status_code=401, detail="X-BFA-Key ausente ou inválida.")


def responder(request: Request, result: ToolResult | SnapshotResult) -> JSONResponse:
    """Converte o envelope em resposta HTTP (status mapeado do ErrorCode) e loga."""
    rid = getattr(request.state, "request_id", "-")
    if isinstance(result, SnapshotResult):
        for nome, sec in result.sections.items():
            log.info("request_id=%s rota=%s tool=%s cached=%s latency_ms=%s ok=%s",
                     rid, request.url.path, sec.tool, sec.cached, sec.latency_ms, sec.ok)
        return JSONResponse(status_code=200, content=result.model_dump(mode="json"))
    status = 200 if result.ok else HTTP_STATUS[result.error.code]  # type: ignore[union-attr]
    log.info("request_id=%s rota=%s tool=%s cached=%s latency_ms=%s ok=%s",
             rid, request.url.path, result.tool, result.cached, result.latency_ms, result.ok)
    return JSONResponse(status_code=status, content=result.model_dump(mode="json"))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        gateway = MCPGateway(settings)
        app.state.gateway = gateway
        await gateway.start()  # sem BOLSAI_API_KEY apenas avisa; /health mostra não pronto
        try:
            yield
        finally:
            await gateway.stop()

    app = FastAPI(title="BFA - Backend For Agents (Quantum Finance)", lifespan=lifespan)
    app.state.settings = settings
    app.state.cache = ToolCache()

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/health")
    async def health(gw: Gateway = Depends(get_gateway)):
        pronto = gw.ready
        return {
            "status": "ok" if pronto else "degraded",
            "mcp_ready": pronto,
            "tools_count": len(gw.manifest),
            "missing_tools": gw.missing_tools,
            "last_error": gw.last_error,
        }

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(verify_key)])

    @v1.get("/tools")
    async def tools(gateway: Gateway = Depends(get_gateway)):
        return [{**t, "bfa_route": ROTAS.get(t["name"])} for t in gateway.manifest]

    @v1.get("/b3/quote/{ticker}")
    async def quote(ticker: str, request: Request, svc: BFAService = Depends(get_service)):
        return responder(request, await svc.quote(ticker))

    @v1.get("/b3/fundamentals/{ticker}")
    async def fundamentals(ticker: str, request: Request, reference_date: str | None = None,
                           svc: BFAService = Depends(get_service)):
        return responder(request, await svc.fundamentals(ticker, reference_date))

    @v1.get("/b3/compare")
    async def compare(request: Request, tickers: list[str] = Query(...), metrics: str | None = None,
                      svc: BFAService = Depends(get_service)):
        return responder(request, await svc.compare(tickers, metrics))

    @v1.get("/b3/dividends/{ticker}")
    async def dividends(ticker: str, request: Request, years: int = Query(3, ge=1, le=20),
                        svc: BFAService = Depends(get_service)):
        return responder(request, await svc.dividends(ticker, years))

    @v1.get("/b3/companies")
    async def companies(request: Request, query: str | None = None, sector: str | None = None,
                        svc: BFAService = Depends(get_service)):
        return responder(request, await svc.companies(query, sector))

    @v1.get("/b3/history/{ticker}")
    async def history(ticker: str, request: Request, start: str | None = None, end: str | None = None,
                      limit: int = Query(30, ge=1, le=5000), svc: BFAService = Depends(get_service)):
        return responder(request, await svc.history(ticker, start, end, limit))

    @v1.get("/b3/fii/{ticker}")
    async def fii(ticker: str, request: Request, svc: BFAService = Depends(get_service)):
        return responder(request, await svc.fii(ticker))

    @v1.get("/b3/financials/{ticker}")
    async def financials(ticker: str, request: Request, statement_type: str = "DRE",
                         report_type: str = "DFP", reference_date: str | None = None,
                         svc: BFAService = Depends(get_service)):
        return responder(request, await svc.financials(ticker, statement_type, report_type, reference_date))

    @v1.get("/macro/{indicator}")
    async def macro(indicator: str, request: Request, limit: int = Query(30, ge=1, le=500),
                    svc: BFAService = Depends(get_service)):
        return responder(request, await svc.macro(indicator, limit))

    @v1.post("/b3/screen")
    async def screen(body: ScreenRequest, request: Request, svc: BFAService = Depends(get_service)):
        return responder(request, await svc.screen(body))

    @v1.get("/b3/snapshot/{ticker}")
    async def snapshot(ticker: str, request: Request, svc: BFAService = Depends(get_service)):
        return responder(request, await svc.snapshot(ticker))

    app.include_router(v1)
    return app


app = create_app()
