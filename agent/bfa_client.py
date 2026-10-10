"""Cliente HTTP síncrono do BFA. Converte o envelope JSON em texto para o LLM."""
from contextvars import ContextVar
from typing import Any

import httpx

from agent import config

# Preenchido pelo grafo com o thread_id; vai no header X-Request-ID
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)


class BFAClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 60):
        self.base_url = (base_url or config.bfa_url()).rstrip("/")
        self.api_key = api_key if api_key is not None else config.bfa_api_key()
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        h = {}
        if self.api_key:
            h["X-BFA-Key"] = self.api_key
        rid = current_request_id.get()
        if rid:
            h["X-Request-ID"] = rid
        return h

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Faz a chamada (1 retry em ConnectError). Devolve sempre o JSON do envelope."""
        for tentativa in range(2):
            try:
                r = self._http.request(method, path, headers=self._headers(), **kwargs)
                break
            except httpx.ConnectError:
                if tentativa == 1:
                    return {"ok": False, "error": {"code": "upstream_unavailable",
                            "message": f"BFA offline em {self.base_url}. Suba com: uv run python -m bfa"}}
            except httpx.TimeoutException:
                return {"ok": False, "error": {"code": "timeout", "message": "Timeout ao chamar o BFA."}}
        try:
            return r.json()
        except ValueError:
            return {"ok": False, "error": {"code": "upstream_error",
                    "message": f"Resposta inválida do BFA (HTTP {r.status_code})."}}

    # --- saúde ---
    def health(self) -> dict[str, Any]:
        r = self._http.get("/health", timeout=5)
        r.raise_for_status()
        return r.json()

    # --- rotas (1:1 com o BFA) ---
    def quote(self, ticker: str):
        return self._request("GET", f"/v1/b3/quote/{ticker}")

    def fundamentals(self, ticker: str, reference_date: str | None = None):
        return self._request("GET", f"/v1/b3/fundamentals/{ticker}", params={"reference_date": reference_date})

    def compare(self, tickers: list[str], metrics: str | None = None):
        return self._request("GET", "/v1/b3/compare", params={"tickers": ",".join(tickers), "metrics": metrics})

    def dividends(self, ticker: str, years: int = 3):
        return self._request("GET", f"/v1/b3/dividends/{ticker}", params={"years": years})

    def companies(self, query: str | None = None, sector: str | None = None):
        return self._request("GET", "/v1/b3/companies", params={"query": query, "sector": sector})

    def history(self, ticker: str, start: str | None = None, end: str | None = None, limit: int = 30):
        return self._request("GET", f"/v1/b3/history/{ticker}",
                             params={"start": start, "end": end, "limit": limit})

    def fii(self, ticker: str):
        return self._request("GET", f"/v1/b3/fii/{ticker}")

    def financials(self, ticker: str, statement_type: str = "DRE", report_type: str = "DFP",
                   reference_date: str | None = None):
        return self._request("GET", f"/v1/b3/financials/{ticker}",
                             params={"statement_type": statement_type, "report_type": report_type,
                                     "reference_date": reference_date})

    def macro(self, indicator: str, limit: int = 30):
        return self._request("GET", f"/v1/macro/{indicator}", params={"limit": limit})

    def screen(self, body: dict[str, Any]):
        return self._request("POST", "/v1/b3/screen", json=body)

    def snapshot(self, ticker: str):
        return self._request("GET", f"/v1/b3/snapshot/{ticker}")

    # --- conversão para texto do LLM ---
    @staticmethod
    def as_llm_text(result: dict[str, Any]) -> str:
        """ok -> dado; erro -> 'ERRO [codigo]: mensagem' (para o LLM não alucinar)."""
        if "sections" in result:  # snapshot composto
            partes = [f"=== {result.get('ticker')} ({result.get('asset_type')}) ==="]
            for nome, sec in result["sections"].items():
                partes.append(f"--- {nome} ---\n{BFAClient.as_llm_text(sec)}")
            return "\n\n".join(partes)
        if result.get("ok"):
            return result.get("data") or "Nenhum dado retornado."
        erro = result.get("error")
        if erro:
            return f"ERRO [{erro.get('code')}]: {erro.get('message')}"
        # corpo de validação padrão do FastAPI (ex.: query fora do intervalo)
        return f"ERRO [invalid_input]: {result.get('detail', result)}"
