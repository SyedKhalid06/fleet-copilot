"""Fleet Copilot agent (LangGraph).

Step A: shared state + router node.
"""
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from .retriever_tool import extract_entities


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
        }

    return router


# ------------------------------------------------------------------ graph (step A: router only)
def build_router_only_graph(llm):
    g = StateGraph(State)
    g.add_node("router", make_router(llm))
    g.add_edge(START, "router")
    g.add_edge("router", END)
    return g.compile()