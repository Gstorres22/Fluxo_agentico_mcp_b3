# Relatório de Erros e Correções (Consultor Financeiro AI)

Este documento lista os erros encontrados durante o desenvolvimento e execução inicial do fluxo LangGraph integrado ao MCP da B3 e como foram solucionados.

## 1. `ModuleNotFoundError: No module named 'pywintypes'`
**Erro:** O Python não conseguia encontrar o módulo `pywintypes` utilizado na conexão MCP com stdio no Windows, mesmo com a biblioteca `pywin32` instalada.
**Causa:** Este é um erro comum em ambientes virtuais (`.venv`) no Windows onde as DLLs do `pywin32` não são carregadas corretamente sem o script de pós-instalação ou quando a instalação falha em registrar os caminhos globais.
**Correção:** Forçamos a reinstalação e atualização dos pacotes no ambiente virtual e ajustamos os imports necessários para garantir que o MCP Client pudesse rodar corretamente sob o Windows.

## 2. Erro de BadRequest da OpenAI (HTTP 400)
**Erro:** `openai.BadRequestError: Error code: 400 - {'error': {'message': "Invalid parameter: messages with role 'tool' must be a response to a preceeding message with 'tool_calls'.", 'type': 'invalid_request_error', 'param': 'messages', 'code': None}}`
**Causa:** No LangGraph, quando o modelo de linguagem principal (`lead_advisor`) aciona ferramentas paralelamente (ou delega para subagentes), o histórico de mensagens devolvido à OpenAI deve **exatamente** corresponder na ordem: uma `AIMessage` contendo `tool_calls` seguida obrigatoriamente por `ToolMessage`s para cada `tool_call_id`. Se a estrutura do nó falhasse em alinhar esses IDs ou substituísse parte do histórico, a API da OpenAI rejeitava a requisição.
**Correção:**
1. Modificamos o objeto `State` (AgentState) para utilizar o `reducer` `add_messages` (`Annotated[list[AnyMessage], add_messages]`). Isso assegurou que as mensagens não fossem simplesmente sobrescritas ao transitar entre nós, mas sim adicionadas ao histórico.
2. Refatoramos os nós de subagentes paralelos em um único nó chamado `subagents_executor_node`. Este nó extrai as ferramentas solicitadas pelo `lead_advisor`, executa os subagentes sequencialmente para garantir a integridade dos resultados, e retorna as `ToolMessage` correspondentes a cada solicitação efetuada, mantendo o histórico consistente.

## 3. Bibliotecas Ausentes (`duckduckgo-search` e referências)
**Erro:** Falha de importação no Market Analyst ao tentar realizar pesquisas web.
**Causa:** As dependências do `duckduckgo-search` (necessárias pela LangChain para pesquisa) não estavam presentes.
**Correção:** Instalação das bibliotecas `duckduckgo-search` e `langchain-community` no ambiente virtual (`.venv`).

## 4. `NameError: name 'HumanMessage' is not defined`
**Erro:** Variáveis de mensagem do LangChain não reconhecidas.
**Causa:** Esquecimento de importar explicitamente os objetos de mensagem usados para inicializar os testes do LangGraph.
**Correção:** Adição dos imports: `from langchain_core.messages import HumanMessage, AIMessage, ToolMessage`.

## 5. Tools do agente não batiam com o servidor MCP real
**Erro:** O agente chamava tools/argumentos inexistentes (`get_macro_data`, `get_fii_data`, `screen_stocks(roe_min, pl_max)`, `compare_stocks(tickers: list)`).
**Causa:** As assinaturas foram escritas sem conferir o `bolsai_mcp/server.py` (v0.1.1): o nome real é `get_macro_indicator` (com `usd_brl`), `get_fii_details`, `compare_stocks(tickers: str "A,B")` e `screen_stocks(metric, operator, value, ...)`.
**Correção:** O BFA chama exatamente os nomes/argumentos do MCP, valida o manifesto na conexão e as tools do agente (`agent/tools.py`) foram reescritas com as assinaturas corretas (incluindo `search_companies`, `get_price_history` e `get_financial_statements`).

## 6. `RuntimeError: Attempted to exit cancel scope in a different task`
**Erro:** Falha ao encerrar a sessão MCP.
**Causa:** O contexto `stdio_client` era aberto (`__aenter__`) e fechado (`__aexit__`) manualmente em tasks diferentes.
**Correção:** No BFA, `MCPGateway` abre, usa e fecha a sessão dentro de UMA task supervisora (`async with`), com reconexão automática.

## 7. Erros do MCP chegavam ao LLM como se fossem dados
**Erro:** Respostas como "Not found:", "Invalid API key" ou "Rate limit exceeded" eram tratadas como resultado válido; `result.isError` era ignorado e só o primeiro `content` era lido.
**Correção:** O BFA classifica esses textos em códigos tipados (`not_found`, `rate_limited`...), devolve um envelope `ToolResult` com status HTTP adequado, não cacheia erros, junta todos os `content` de texto e o cliente do agente entrega ao LLM `ERRO [codigo]: mensagem`.

## 8. `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` (servidor bolsai-mcp)
**Erro:** o `uvx bolsai-mcp` passou a falhar logo na inicialização; o BFA ficava em `degraded`.
**Causa:** o `uvx` instala a versão mais nova do SDK `mcp` (2.x), onde `FastMCP` foi renomeado para `MCPServer`. O `bolsai-mcp` 0.1.1 ainda importa `FastMCP` e não restringe a versão.
**Correção:** o BFA sobe o servidor com `uvx --with "mcp<2" bolsai-mcp==0.1.1` (`bfa/config.py`, `MCP_ARGS`) e o projeto fixa `mcp>=1.27,<2` no `pyproject.toml`.

## 9. Respostas vazias do MCP eram cacheadas
**Erro:** com chave inválida, `compare_stocks` devolvia "No data found for any of the tickers." e essa resposta ficava 6h no cache.
**Causa:** o `bolsai-mcp` engole os erros por ticker no `compare_stocks` e responde como "sem dados".
**Correção:** respostas vazias ("No data found", "No companies found", "No stocks found") continuam `ok=true`, mas não são cacheadas (`bfa/errors.py`, `is_empty_result`).

## Estado Atual
O fluxo foi refatorado: os agentes (`agent/`) falam apenas HTTP com o BFA (`bfa/`), que mantém a única sessão MCP com o Bolsai. Veja o `README.md` para a arquitetura e como rodar. A validação com chaves reais (OpenAI/Bolsai) ainda precisa ser feita.
