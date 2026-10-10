"""Testes da API do BFA com um FakeGateway (sem rede, sem MCP real)."""
import pytest
from fastapi.testclient import TestClient

from bfa.api import create_app, get_gateway
from bfa.config import Settings
from bfa.errors import ErrorCode
from bfa.mcp_gateway import EXPECTED_TOOLS, GatewayError


class FakeGateway:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.respostas: dict[str, str] = {}
        self.falhas: dict[str, GatewayError] = {}
        self.ready = True
        self.manifest = [{"name": n, "description": "", "inputSchema": {}} for n in EXPECTED_TOOLS]
        self.missing_tools: list[str] = []
        self.last_error = None

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if name in self.falhas:
            raise self.falhas[name]
        return self.respostas.get(name, f"dados de {name}")


@pytest.fixture
def gw():
    return FakeGateway()


def make_client(gw, **settings_kwargs):
    app = create_app(Settings(BOLSAI_API_KEY=None, BFA_API_KEY=settings_kwargs.get("key")))
    app.dependency_overrides[get_gateway] = lambda: gw
    return TestClient(app)


@pytest.fixture
def client(gw):
    return make_client(gw)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["mcp_ready"] is True
    assert r.json()["tools_count"] == 10


def test_ticker_invalido_422(client, gw):
    r = client.get("/v1/b3/quote/XX")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"
    assert gw.calls == []


def test_ticker_normalizado(client, gw):
    r = client.get("/v1/b3/quote/ petr4 ")
    assert r.status_code == 200
    assert gw.calls[0] == ("get_stock_quote", {"ticker": "PETR4"})


def test_alias_usdbrl(client, gw):
    r = client.get("/v1/macro/usdbrl")
    assert r.status_code == 200
    assert gw.calls[0] == ("get_macro_indicator", {"indicator": "usd_brl", "limit": 30})


def test_macro_invalido(client):
    r = client.get("/v1/macro/bitcoin")
    assert r.status_code == 422


def test_cache_hit(client, gw):
    a = client.get("/v1/b3/quote/PETR4").json()
    b = client.get("/v1/b3/quote/PETR4").json()
    assert a["cached"] is False
    assert b["cached"] is True
    assert len(gw.calls) == 1


def test_not_found_404_e_nao_cacheado(client, gw):
    gw.respostas["get_stock_quote"] = "Not found: ticker ABCD3"
    r = client.get("/v1/b3/quote/ABCD3")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    client.get("/v1/b3/quote/ABCD3")
    assert len(gw.calls) == 2  # erro não foi cacheado


def test_rate_limit_429(client, gw):
    gw.respostas["get_stock_quote"] = "Rate limit exceeded. Upgrade to Pro at https://usebolsai.com"
    assert client.get("/v1/b3/quote/PETR4").status_code == 429


def test_timeout_504(client, gw):
    gw.falhas["get_stock_quote"] = GatewayError(ErrorCode.timeout, "demorou")
    assert client.get("/v1/b3/quote/PETR4").status_code == 504


def test_sem_dados_nao_e_erro(client, gw):
    gw.respostas["search_companies"] = "No companies found."
    r = client.get("/v1/b3/companies", params={"query": "zzz"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_compare_csv_e_lista(client, gw):
    client.get("/v1/b3/compare", params={"tickers": "wege3,itub4"})
    assert gw.calls[-1] == ("compare_stocks", {"tickers": "WEGE3,ITUB4"})
    client.get("/v1/b3/compare?tickers=PETR4&tickers=VALE3&metrics=pl,roe")
    assert gw.calls[-1] == ("compare_stocks", {"tickers": "PETR4,VALE3", "metrics": "pl,roe"})


def test_compare_quantidade_invalida(client):
    assert client.get("/v1/b3/compare", params={"tickers": "PETR4"}).status_code == 422
    assert client.get("/v1/b3/compare", params={"tickers": "A1,B1"}).status_code == 422


def test_screen(client, gw):
    r = client.post("/v1/b3/screen", json={"metric": "roe", "operator": "gt", "value": 15})
    assert r.status_code == 200
    assert gw.calls[-1][0] == "screen_stocks"
    assert gw.calls[-1][1]["metric"] == "roe"


def test_screen_between_sem_upper(client):
    r = client.post("/v1/b3/screen", json={"metric": "pl", "operator": "between", "value": 5})
    assert r.status_code == 422


def test_screen_metrica_invalida(client):
    r = client.post("/v1/b3/screen", json={"metric": "xyz", "operator": "gt", "value": 1})
    assert r.status_code == 422


def test_snapshot_acao(client, gw):
    r = client.get("/v1/b3/snapshot/WEGE3")
    assert r.status_code == 200
    body = r.json()
    assert body["asset_type"] == "stock"
    assert set(body["sections"]) == {"quote", "fundamentals", "dividends"}


def test_snapshot_fii_falha_parcial(client, gw):
    gw.respostas["get_fii_details"] = "Not found: HGLG11"
    r = client.get("/v1/b3/snapshot/HGLG11")
    assert r.status_code == 200
    body = r.json()
    assert body["asset_type"] == "fii"
    assert body["sections"]["fii"]["ok"] is False
    assert body["sections"]["quote"]["ok"] is True


def test_auth_opcional(gw):
    c = make_client(gw, key="segredo")
    assert c.get("/v1/b3/quote/PETR4").status_code == 401
    assert c.get("/v1/b3/quote/PETR4", headers={"X-BFA-Key": "errada"}).status_code == 401
    assert c.get("/v1/b3/quote/PETR4", headers={"X-BFA-Key": "segredo"}).status_code == 200
    assert c.get("/health").status_code == 200  # health é aberto


def test_request_id(client):
    r = client.get("/v1/b3/quote/PETR4", headers={"X-Request-ID": "abc"})
    assert r.headers["X-Request-ID"] == "abc"
    assert "X-Request-ID" in client.get("/health").headers


def test_tools_manifest(client):
    r = client.get("/v1/tools")
    assert r.status_code == 200
    assert {t["name"]: t["bfa_route"] for t in r.json()}["get_macro_indicator"] == "/v1/macro/{indicator}"


def test_resposta_vazia_nao_e_cacheada(client, gw):
    gw.respostas["compare_stocks"] = "No data found for any of the tickers."
    a = client.get("/v1/b3/compare", params={"tickers": "WEGE3,ITUB4"}).json()
    b = client.get("/v1/b3/compare", params={"tickers": "WEGE3,ITUB4"}).json()
    assert a["ok"] is True and b["cached"] is False
