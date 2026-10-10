# Fluxo Agêntico MCP B3 - Consultor Financeiro Quantum Finance

Consultor financeiro com agentes LangGraph (Lead Advisor + Market Analyst + Agente B3) que usa dados reais da B3
através de um **BFA (Backend For Agents)**: um serviço HTTP (FastAPI) que é o único dono da sessão MCP do `bolsai-mcp`.

## Arquitetura

```
Notebook / test_flow.py --> agent/ (LangGraph) --HTTP/JSON--> bfa/ (FastAPI) --MCP stdio--> uvx bolsai-mcp --> api.usebolsai.com
                             tools = BFAClient (httpx)         cache TTL, validação, semáforo,
                                                               erros tipados, snapshot composto
```

- `bfa/`: gateway MCP (sessão persistente, reconexão com backoff), cache TTL, validação/normalização
  (ticker, aliases macro como `usdbrl`), erros tipados mapeados para HTTP (404/422/429/502/504) e rota composta `snapshot`.
- `agent/`: cliente HTTP do BFA, tools LangChain com as assinaturas reais do MCP e o grafo LangGraph.
- `tests/`: testes do BFA com `FakeGateway` (sem rede).

## Como rodar

```bash
uv venv --python 3.12
uv sync
cp .env.example .env        # preencha OPENAI_API_KEY e BOLSAI_API_KEY

# Terminal 1: BFA
uv run python -m bfa        # http://127.0.0.1:8000  (veja /health e /docs)

# Terminal 2: agente
uv run python test_flow.py  # ou abra consultor_financeiro.ipynb com o kernel do .venv
```

Testes: `uv run pytest -q`

## Rotas do BFA

| Rota | Tool MCP |
|---|---|
| `GET /health` | status da sessão MCP |
| `GET /v1/tools` | manifesto do MCP |
| `GET /v1/b3/quote/{ticker}` | get_stock_quote |
| `GET /v1/b3/fundamentals/{ticker}` | get_fundamentals |
| `GET /v1/b3/compare?tickers=PETR4,VALE3` | compare_stocks |
| `GET /v1/b3/dividends/{ticker}?years=3` | get_dividends |
| `GET /v1/b3/companies?query=&sector=` | search_companies |
| `GET /v1/b3/history/{ticker}` | get_price_history |
| `GET /v1/b3/fii/{ticker}` | get_fii_details |
| `GET /v1/b3/financials/{ticker}` | get_financial_statements |
| `GET /v1/macro/{indicator}` | get_macro_indicator |
| `POST /v1/b3/screen` | screen_stocks |
| `GET /v1/b3/snapshot/{ticker}` | composto (cotação + fundamentos/FII + dividendos) |

Se `BFA_API_KEY` estiver definida, as rotas `/v1` exigem o header `X-BFA-Key`.
