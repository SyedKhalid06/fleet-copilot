"""Fleet Copilot agent (LangGraph).

Step A: shared state + router node.
"""
import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from . import sql_tool
from .retriever_tool import extract_entities, format_context, retrieve


# ------------------------------------------------------------------ state
class State(TypedDict, total=False):
    """The shared notebook every node reads from and writes to."""
    messages: Annotated[list, add_messages]   # chat history: new messages are APPENDED, not replaced
    question: str                             # standalone version of the latest question
    route: str                                # sql | docs | both | clarify | out_of_scope
    route_reason: str
    entities: dict                            # {"unit_no": [...], "dtc_codes": [...], "spns": [...]}
    sql_result: dict                          # filled in step B
    docs: list                                # filled in step B
    attempts: int                             # retry counter (step C)
    answer: str
    citations: list


# ------------------------------------------------------------------ router
class RouteDecision(BaseModel):
    route: Literal["sql", "docs", "both", "clarify", "out_of_scope"] = Field(
        description="Which tools are needed to answer the latest question.")
    standalone_question: str = Field(
        description="The latest question rewritten so it makes sense on its own, using the chat history "
                    "(for example, fill in the truck unit number from earlier messages).")
    reason: str = Field(description="One short sentence explaining the choice.")


ROUTER_PROMPT = """You route questions for Fleet Copilot, an assistant for a truck fleet's operations and workshop teams.

Routes:
- sql: needs numbers or facts from fleet data - status, rankings, counts, fuel use, costs, trends, lists of trucks or faults.
- docs: needs written knowledge - what a fault code means, procedures (SOPs), what the driver or workshop should do,
  what technicians found in past repairs.
- both: about a specific truck or situation AND needs an explanation or guidance - e.g. "why is RTM-021 using more fuel?",
  "what's wrong with GOT-028 and what should we check?".
- clarify: cannot be answered even with the chat history, because it is too vague (e.g. "is it fixed?" with no truck mentioned).
- out_of_scope: not about the fleet (weather, news, general chat).

Always rewrite the latest question as a standalone question, using the chat history to fill in missing details
such as the truck unit number. Unit numbers look like GOT-028, HAM-014, RTM-021, CHI-007."""


def make_router(llm):
    """Build the router node. The LLM is passed in, so the same code works with any model."""
    router_llm = llm.with_structured_output(RouteDecision)

    def router(state: State) -> dict:
        decision = router_llm.invoke([SystemMessage(ROUTER_PROMPT), *state["messages"]])
        return {
            "question": decision.standalone_question,
            "route": decision.route,
            "route_reason": decision.reason,
            "entities": extract_entities(decision.standalone_question),
            "attempts": 0,
            "sql_result": None,      # clear evidence from the previous turn
            "docs": [],
        }

    return router


# ------------------------------------------------------------------ graph (step A: router only)
def build_router_only_graph(llm):
    g = StateGraph(State)
    g.add_node("router", make_router(llm))
    g.add_edge(START, "router")
    g.add_edge("router", END)
    return g.compile()

# ------------------------------------------------------------------ tools the nodes need
@dataclass
class FleetTools:
    """Everything the tool nodes need, built once in the notebook and passed in."""
    spark: object
    client: object            # OpenAI client: SQL generation + embeddings
    schema_context: str
    index: object             # HybridIndex
    spn_names: dict
    sql_model: str = "gpt-4o-mini"


# ------------------------------------------------------------------ tool nodes
def make_sql_node(tools: FleetTools):
    def sql_node(state: State) -> dict:
        result = sql_tool.ask_sql(state["question"], tools.spark, tools.client,
                                  tools.schema_context, model=tools.sql_model)
        return {"sql_result": result}
    return sql_node


def make_docs_node(tools: FleetTools):
    def docs_node(state: State) -> dict:
        hits = retrieve(state["question"], tools.index, tools.client, tools.spn_names, k=6)
        return {"docs": hits}
    return docs_node


# ------------------------------------------------------------------ answer
ANSWER_PROMPT = """You are Fleet Copilot, an assistant for a truck fleet's operations and workshop teams.
Answer the question using ONLY the evidence provided.

Citations:
- Numbers and facts from the SQL result: cite [SQL].
- Explanations, procedures and past repairs from documents: cite the document tag, e.g. [SOP-01] or [WO-26-00325].
- Put the citation right after the sentence that uses that evidence.

Rules:
- If the evidence does not answer the question (or part of it), say what is missing. Never guess.
- If the SQL result has no rows, say that no matching records were found.
- Be concise and practical: short paragraphs or bullet points for ops managers and technicians.
- Use units: L/100 km, km, °C. Unit numbers look like GOT-028."""

_CITE = re.compile(r"\[([A-Za-z0-9#\-]+)\]")


def _sql_evidence(result) -> str:
    if not result:
        return "(SQL not used)"
    if not result.get("ok"):
        return f"SQL tool could not answer: {result.get('error')}"
    rows = result["rows"][:50]
    note = " (truncated)" if result.get("truncated") else ""
    return (f"Query:\n{result['sql']}\n"
            f"Rows: {result['row_count']}{note}\n{json.dumps(rows, default=str, indent=1)}")


def make_answer_node(llm):
    def answer_node(state: State) -> dict:
        evidence = (f"Question: {state['question']}\n\n"
                    f"=== SQL RESULT ===\n{_sql_evidence(state.get('sql_result'))}\n\n"
                    f"=== DOCUMENTS ===\n{format_context(state.get('docs') or []) or '(no documents used)'}")
        reply = llm.invoke([SystemMessage(ANSWER_PROMPT), HumanMessage(evidence)])
        text = reply.content
        return {"answer": text,
                "citations": sorted(set(_CITE.findall(text))),
                "messages": [AIMessage(text)]}
    return answer_node


# ------------------------------------------------------------------ non-tool replies
def clarify_node(state: State) -> dict:
    text = ("Could you tell me which truck (unit number such as GOT-028) or which fault code you mean? "
            "Then I can look it up.")
    return {"answer": text, "citations": [], "messages": [AIMessage(text)]}


def out_of_scope_node(state: State) -> dict:
    text = ("I can only help with this fleet: truck status, fuel use, fault codes, repairs and maintenance "
            "procedures.")
    return {"answer": text, "citations": [], "messages": [AIMessage(text)]}


# ------------------------------------------------------------------ routing decisions (plain Python)
def route_after_router(state: State) -> str:
    return {"sql": "sql", "both": "sql", "docs": "docs",
            "clarify": "clarify", "out_of_scope": "out_of_scope"}[state["route"]]


def route_after_sql(state: State) -> str:
    return "docs" if state["route"] == "both" else "answer"


# ------------------------------------------------------------------ the agent (step B)
def build_agent(llm, tools: FleetTools, checkpointer=None):
    g = StateGraph(State)
    g.add_node("router", make_router(llm))
    g.add_node("sql", make_sql_node(tools))
    g.add_node("docs", make_docs_node(tools))
    g.add_node("answer", make_answer_node(llm))
    g.add_node("clarify", clarify_node)
    g.add_node("out_of_scope", out_of_scope_node)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_after_router, ["sql", "docs", "clarify", "out_of_scope"])
    g.add_conditional_edges("sql", route_after_sql, ["docs", "answer"])
    g.add_edge("docs", "answer")
    for end_node in ("answer", "clarify", "out_of_scope"):
        g.add_edge(end_node, END)
    return g.compile(checkpointer=checkpointer)