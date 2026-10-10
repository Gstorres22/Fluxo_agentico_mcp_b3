"""Grafo LangGraph: Lead Advisor -> (Market Analyst | Agente B3). Os dados da B3 vêm do BFA via HTTP."""
import logging
from typing import Annotated, Any, Dict, List, TypedDict

from langchain_core.messages import (
    BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent import config as cfg
from agent.bfa_client import current_request_id
from agent.tools import B3_TOOLS, search_financial_concept

log = logging.getLogger("agent.graph")


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_profile: Dict[str, Any]


@tool
def consult_market_analyst(query: str) -> str:
    """Delega uma tarefa ao Agente Pesquisador (Market Analyst)."""
    pass


@tool
def consult_b3_specialist(task: str) -> str:
    """Delega uma tarefa ao Especialista B3."""
    pass


ADVISOR_SYSTEM_PROMPT = (
    "Você é o Lead Advisor (Estrategista Financeiro) da Quantum Finance.\n"
    "Seu papel é receber as dúvidas do cliente, entender o perfil dele, planejar a busca de dados reais "
    "e delegar tarefas para seus subagentes usando as ferramentas:\n"
    "- 'consult_market_analyst' para dúvidas teóricas ou conceitos.\n"
    "- 'consult_b3_specialist' para dados de mercado, cotações e múltiplos da B3.\n\n"
    "Perfil do Cliente Atual:\n"
    "{user_profile}\n\n"
    "Diretrizes:\n"
    "1. Nunca tente chutar ou alucinar cotações e múltiplos. Sempre chame o consult_b3_specialist.\n"
    "2. Quando tiver todos os dados necessários reunidos, elabore um relatório final com a recomendação de alocação personalizada, "
    "justificando cada indicação de acordo com o perfil do cliente e os múltiplos da B3 de 2026 obtidos."
)

ANALYST_SYSTEM_PROMPT = (
    "Você é o Agente Pesquisador (Market Analyst). Sua tarefa é explicar de forma didática conceitos financeiros.\n"
    "Use a busca na internet para responder."
)

B3_SYSTEM_PROMPT = (
    "Você é o Agente de Dados B3. Sua tarefa é extrair múltiplos e cotações da B3.\n"
    "Regras:\n"
    "- Para dados de um ativo específico, prefira 'get_asset_snapshot' (cotação + fundamentos + dividendos em uma chamada).\n"
    "- Para perguntas sobre setores, use 'search_companies' (por setor) e 'screen_stocks' (com o filtro de setor) "
    "para encontrar empresas e depois consulte os dados dos melhores candidatos.\n"
    "- Para indicadores macro (Selic, IPCA, CDI, dólar) use 'get_macro_indicator'.\n"
    "- Se uma ferramenta devolver 'ERRO [...]', informe o erro com clareza; NUNCA invente números."
)


def _set_request_id(config: RunnableConfig | None) -> None:
    thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if thread_id:
        current_request_id.set(str(thread_id))


def lead_advisor_node(state: AgentState, config: RunnableConfig = None):
    _set_request_id(config)
    log.debug("Lead Advisor recebeu %d mensagens", len(state["messages"]))
    advisor_model = ChatOpenAI(model="gpt-4o", temperature=0.2).bind_tools(
        [consult_market_analyst, consult_b3_specialist]
    )
    profile_str = "\n".join([f"- {k}: {v}" for k, v in state["user_profile"].items()])
    sys_msg = SystemMessage(content=ADVISOR_SYSTEM_PROMPT.format(user_profile=profile_str))
    response = advisor_model.invoke([sys_msg] + state["messages"])
    return {"messages": [response]}


def subagents_executor_node(state: AgentState, config: RunnableConfig = None):
    _set_request_id(config)
    last_message = state["messages"][-1]
    new_messages = []

    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "consult_market_analyst":
            query = tool_call["args"]["query"]
            print(f"\n[Nó Ativo: subagents_executor -> Executando Market Analyst para a busca: '{query}']")

            analyst_model = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools([search_financial_concept])
            analyst_messages = [SystemMessage(content=ANALYST_SYSTEM_PROMPT), HumanMessage(content=query)]
            response = analyst_model.invoke(analyst_messages)

            while response.tool_calls:
                analyst_messages.append(response)
                for tc in response.tool_calls:
                    result = search_financial_concept.invoke(tc["args"])
                    analyst_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
                response = analyst_model.invoke(analyst_messages)

            tool_msg = ToolMessage(content=response.content, tool_call_id=tool_call["id"], name=tool_call["name"])
            new_messages.append(tool_msg)
            print("-> Resposta do Market Analyst obtida.")

        elif tool_call["name"] == "consult_b3_specialist":
            task = tool_call["args"]["task"]
            print(f"\n[Nó Ativo: subagents_executor -> Executando Agente B3 para a tarefa: '{task}']")

            b3_model = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(B3_TOOLS)
            b3_messages = [SystemMessage(content=B3_SYSTEM_PROMPT), HumanMessage(content=task)]
            response = b3_model.invoke(b3_messages)
            log.info("Agente B3 pediu %d tool calls", len(response.tool_calls))

            while response.tool_calls:
                b3_messages.append(response)
                for tc in response.tool_calls:
                    target_tool = next((t for t in B3_TOOLS if t.name == tc["name"]), None)
                    if target_tool is None:
                        result = f"ERRO [invalid_input]: ferramenta desconhecida '{tc['name']}'."
                    else:
                        log.info("Invocando tool %s %s", tc["name"], tc["args"])
                        try:
                            result = target_tool.invoke(tc["args"])
                        except Exception as e:  # noqa: BLE001 - argumentos inválidos do LLM etc.
                            result = f"ERRO [invalid_input]: {e}"
                    b3_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
                response = b3_model.invoke(b3_messages)

            tool_msg = ToolMessage(content=response.content, tool_call_id=tool_call["id"], name=tool_call["name"])
            new_messages.append(tool_msg)
            print("-> Resposta do Agente B3 obtida.")

    return {"messages": new_messages}


def route_after_advisor(state: AgentState):
    last_message = state["messages"][-1]
    if not last_message.tool_calls:
        return END
    return "subagents_executor"


def build_graph(checkpointer=None):
    """Monta e compila o grafo. Sem checkpointer informado, usa MemorySaver (memória da conversa)."""
    cfg.require_openai_key()
    workflow = StateGraph(AgentState)
    workflow.add_node("lead_advisor", lead_advisor_node)
    workflow.add_node("subagents_executor", subagents_executor_node)
    workflow.add_edge(START, "lead_advisor")
    workflow.add_conditional_edges(
        "lead_advisor",
        route_after_advisor,
        {"subagents_executor": "subagents_executor", END: END},
    )
    workflow.add_edge("subagents_executor", "lead_advisor")
    return workflow.compile(checkpointer=checkpointer or MemorySaver())
