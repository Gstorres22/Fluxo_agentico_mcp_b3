"""Teste de fluxo: roda 2 turnos (com memória) no grafo, usando o BFA para os dados da B3.

Pré-requisitos:
  1. .env com OPENAI_API_KEY e BOLSAI_API_KEY (veja .env.example)
  2. BFA no ar em outro terminal:  uv run python -m bfa
"""
import logging
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.bfa_client import BFAClient
from agent.graph import build_graph

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def checar_bfa() -> bool:
    try:
        saude = BFAClient().health()
    except Exception as e:  # noqa: BLE001
        print(f"BFA offline ({type(e).__name__}). Suba o serviço em outro terminal com:\n  uv run python -m bfa")
        return False
    if not saude.get("mcp_ready"):
        print(f"BFA no ar, mas a sessão MCP não está pronta: {saude.get('last_error')}\n"
              "Confira a BOLSAI_API_KEY no .env e reinicie o BFA.")
        return False
    print(f"BFA ok: {saude['tools_count']} tools MCP disponíveis.")
    return True


def rodar_turno(app, pergunta: str, perfil: dict, config: dict) -> None:
    print(f"Pergunta: {pergunta}")
    for event in app.stream({"messages": [HumanMessage(content=pergunta)], "user_profile": perfil}, config):
        for node_name, state_update in event.items():
            print(f"\n[Nó Ativo: {node_name}]")
            for msg in state_update.get("messages", []):
                if isinstance(msg, AIMessage):
                    if msg.tool_calls:
                        print(f"-> Delegando ferramenta: {msg.tool_calls[0]['name']}")
                    else:
                        print(f"-> Resposta final do Lead Advisor:\n{msg.content}")
                elif isinstance(msg, ToolMessage):
                    print("-> Resposta de subagente recebida.")


def run_test():
    if not checar_bfa():
        sys.exit(1)

    app = build_graph()

    perfil_arrojado = {
        "Nome": "Gabriel",
        "Perfil de Risco": "Arrojado",
        "Objetivo": "Maximizar ganhos em renda variável no longo prazo",
        "Horizonte de Tempo": "10 anos",
    }
    perfil_conservador = {
        "Nome": "Gabriel",
        "Perfil de Risco": "Conservador",
        "Objetivo": "Preservar capital com retornos previsíveis",
        "Horizonte de Tempo": "10 anos",
    }
    config = {"configurable": {"thread_id": "gabriel_thread"}, "recursion_limit": 15}

    print("\n--- INICIANDO FLUXO DE TESTES (TURNO 1) ---")
    rodar_turno(
        app,
        "Vale a pena investir em ações da WEGE3 ou ITUB4 hoje comparado com a Selic atual? "
        "Me explique brevemente o risco e a comparação de múltiplos.",
        perfil_arrojado, config,
    )

    print("\n--- CONTINUANDO FLUXO DE TESTES (TURNO 2 - CONVERSACIONAL COM MEMÓRIA) ---")
    rodar_turno(app, "E se meu perfil mudasse para Conservador, o que recomendaria?", perfil_conservador, config)


if __name__ == "__main__":
    run_test()
