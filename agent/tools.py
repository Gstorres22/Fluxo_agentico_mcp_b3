"""Tools LangChain do Agente B3. Todas chamam o BFA por HTTP (nenhuma fala MCP direto)."""
import logging
from typing import Literal, Optional

from langchain_core.tools import tool

from agent.bfa_client import BFAClient

log = logging.getLogger("agent.tools")

_bfa: BFAClient | None = None
_web_search = None


def get_bfa() -> BFAClient:
    """Cliente BFA único (criado no primeiro uso)."""
    global _bfa
    if _bfa is None:
        _bfa = BFAClient()
    return _bfa


def _txt(result) -> str:
    return BFAClient.as_llm_text(result)


@tool
def search_financial_concept(query: str) -> str:
    """Busca na internet informações conceituais sobre produtos e regulamentos financeiros."""
    global _web_search
    try:
        if _web_search is None:
            from langchain_community.tools import DuckDuckGoSearchRun
            _web_search = DuckDuckGoSearchRun()
        log.info("DuckDuckGo: %r", query)
        return _web_search.run(query)
    except Exception as e:  # noqa: BLE001
        log.warning("Erro no DuckDuckGo: %s", e)
        return f"Erro na busca: {e}"


@tool
def get_stock_quote(ticker: str) -> str:
    """Cotação atual de uma ação ou FII da B3 (variação do dia, faixa de 52 semanas, retorno no ano). Ex.: PETR4, HGLG11."""
    return _txt(get_bfa().quote(ticker))


@tool
def get_fundamentals(ticker: str, reference_date: Optional[str] = None) -> str:
    """Múltiplos fundamentalistas de uma ação (P/L, P/VP, EV/EBITDA, ROE, margens, dívida...).
    reference_date (YYYY-MM-DD) é opcional e pede um retrato histórico."""
    return _txt(get_bfa().fundamentals(ticker, reference_date))


@tool
def compare_stocks(tickers: list[str], metrics: Optional[str] = None) -> str:
    """Compara de 2 a 5 ações da B3 lado a lado.
    metrics (opcional, separadas por vírgula): pl, pvp, ev_ebitda, roe, roa, roic, net_margin,
    gross_margin, ebitda_margin, dividend_yield, close_price, lpa, vpa, debt_equity, p_sr."""
    return _txt(get_bfa().compare(tickers, metrics))


@tool
def get_dividends(ticker: str, years: int = 3) -> str:
    """Histórico de dividendos de uma ação ou FII (yield, resumo anual, pagamentos). years: 1 a 20."""
    return _txt(get_bfa().dividends(ticker, years))


@tool
def search_companies(query: Optional[str] = None, sector: Optional[str] = None) -> str:
    """Busca empresas listadas por nome (query, ex.: 'Petrobras') e/ou setor (ex.: 'Bancos',
    'Petróleo e Gás', 'Energia Elétrica')."""
    return _txt(get_bfa().companies(query, sector))


@tool
def get_price_history(ticker: str, start: Optional[str] = None, end: Optional[str] = None,
                      limit: int = 30) -> str:
    """Histórico de preços OHLCV ajustado. start/end no formato YYYY-MM-DD; limit até 5000 (padrão 30)."""
    return _txt(get_bfa().history(ticker, start, end, limit))


@tool
def get_fii_details(ticker: str) -> str:
    """Detalhes de um Fundo Imobiliário (FII): P/VP, dividend yield, valor patrimonial e distribuições. Ex.: HGLG11."""
    return _txt(get_bfa().fii(ticker))


@tool
def get_macro_indicator(indicator: Literal["selic", "selic_target", "ipca", "cdi", "usd_brl"],
                        limit: int = 30) -> str:
    """Indicador macroeconômico brasileiro: selic, selic_target (meta Selic), ipca, cdi ou usd_brl (dólar)."""
    return _txt(get_bfa().macro(indicator, limit))


@tool
def get_financial_statements(ticker: str, statement_type: Optional[str] = "DRE",
                             report_type: str = "DFP", reference_date: Optional[str] = None) -> str:
    """Demonstrações financeiras da CVM. statement_type: DRE, BPA, BPP, DFC_MI ou DVA.
    report_type: DFP (anual) ou ITR (trimestral). reference_date: YYYY-MM-DD (padrão: mais recente)."""
    return _txt(get_bfa().financials(ticker, statement_type or "DRE", report_type, reference_date))


@tool
def screen_stocks(metric: Literal["pl", "pvp", "ev_ebitda", "roe", "roa", "roic", "net_margin",
                                  "gross_margin", "ebitda_margin", "dividend_yield", "debt_equity"],
                  operator: Literal["gt", "lt", "between"], value: float,
                  value_upper: Optional[float] = None, sector: Optional[str] = None,
                  limit: int = 20) -> str:
    """Filtra ações por um múltiplo. operator: gt (maior que), lt (menor que) ou between (exige value_upper).
    Use 'sector' (ex.: 'Bancos') para reduzir a varredura. Ex.: metric=roe, operator=gt, value=15."""
    body = {"metric": metric, "operator": operator, "value": value, "value_upper": value_upper,
            "sector": sector, "limit": limit}
    return _txt(get_bfa().screen({k: v for k, v in body.items() if v is not None}))


@tool
def get_asset_snapshot(ticker: str) -> str:
    """Retrato completo de um ativo em UMA chamada: ação (cotação + fundamentos + dividendos)
    ou FII, ticker terminado em 11 (cotação + detalhes do FII + dividendos). Prefira esta tool."""
    return _txt(get_bfa().snapshot(ticker))


B3_TOOLS = [
    get_asset_snapshot,
    get_stock_quote,
    get_fundamentals,
    compare_stocks,
    get_dividends,
    search_companies,
    get_price_history,
    get_fii_details,
    get_macro_indicator,
    get_financial_statements,
    screen_stocks,
]
