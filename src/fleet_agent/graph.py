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

_CODE_TEXT = re.compile(r"SPN \d+ FMI \d+")
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
    search_query: str          # query used for document search (rewritten on retry)
    relevant: bool             # grader's verdict on the documents
    grade_note: str            # what the grader said was missing
    invalid_citations: list    # citations the checker could not verify


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
such as the truck unit number. Unit numbers look like GOT-028, HAM-014, RTM-021, CHI-007.
Rules for rewriting and routing:
- Keep EVERY part of the question when rewriting. Never drop, change or add what is being asked.
- If the question names a truck (unit number) or a fault code, never choose clarify."""


def make_router(llm):
    """Build the router node. The LLM is passed in, so the same code works with any model."""
    router_llm = llm.with_structured_output(RouteDecision)

    def router(state: State) -> dict:
        decision = router_llm.invoke([SystemMessage(ROUTER_PROMPT), *state["messages"]])
        entities = extract_entities(decision.standalone_question)
        route = decision.route
        # guardrail: a named truck or fault code is never "too vague"
        if route == "clarify" and (entities["unit_no"] or entities["dtc_codes"]):
            route = "both"
        return {
            "question": decision.standalone_question,
            "route": route,
            "route_reason": decision.reason,
            "entities": entities,
            "attempts": 0,
            "sql_result": None,
            "docs": [],
            "search_query": None,
            "relevant": None,
            "grade_note": "",
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
        query = state.get("search_query") or state["question"]
        sql = state.get("sql_result") or {}
        if sql.get("ok"):
            # fault codes the SQL step discovered (e.g. GOT-028's open codes) steer the search
            codes = sorted(set(_CODE_TEXT.findall(json.dumps(sql.get("rows", [])))))
            if codes:
                query += " | fault codes: " + ", ".join(codes)
        hits = retrieve(query, tools.index, tools.client, tools.spn_names, k=6)
        return {"docs": hits}
    return docs_node


# ------------------------------------------------------------------ grade + retry
class Grade(BaseModel):
    relevant: bool = Field(description="True if the documents contain what is needed to answer the question.")
    missing: str = Field(description="If not relevant: what information is missing, in a few words. Otherwise empty.")


GRADE_PROMPT = """You check whether retrieved documents are enough to answer a question about a truck fleet.
Answer relevant=true if the documents contain the needed information (procedures, fault code meanings,
repair history). Partial but useful evidence counts as relevant.
If not, say briefly what is missing."""

REWRITE_PROMPT = """Rewrite a search query for a truck fleet knowledge base (SOPs, fault code guides, workshop
work orders). Use words a technician would write: component names, symptoms, fault codes.
Keep any unit number or fault code from the original. Return only the new query."""

MAX_RETRIES = 2


def make_grade_node(llm):
    grader = llm.with_structured_output(Grade)

    def grade_node(state: State) -> dict:
        docs = state.get("docs") or []
        if not docs:
            return {"relevant": False, "grade_note": "no documents found"}
        g = grader.invoke([SystemMessage(GRADE_PROMPT),
                           HumanMessage(f"Question: {state['question']}\n\nDocuments:\n{format_context(docs)}")])
        return {"relevant": g.relevant, "grade_note": g.missing}
    return grade_node


def make_rewrite_node(llm):
    def rewrite_node(state: State) -> dict:
        prompt = (f"Question: {state['question']}\n"
                  f"Previous search query: {state.get('search_query') or state['question']}\n"
                  f"What was missing: {state.get('grade_note')}")
        new_query = llm.invoke([SystemMessage(REWRITE_PROMPT), HumanMessage(prompt)]).content.strip()
        return {"search_query": new_query, "attempts": state.get("attempts", 0) + 1}
    return rewrite_node


def route_after_grade(state: State) -> str:
    if state.get("relevant"):
        return "answer"
    return "rewrite" if state.get("attempts", 0) < MAX_RETRIES else "answer"   # the brake on the loop

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
- Use units: L/100 km, km, °C. Unit numbers look like GOT-028.
- Every sentence that states a fact needs a citation, and the citation must be the source that contains that fact.
- Ignore documents that are not relevant to the question (for example, a tyre job when asked about cooling).
- When a repair (work order) appears in the evidence, compare its date with the data: say whether the problem
  was fixed and whether the numbers improved afterwards."""

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
        if state.get("relevant") is False:
            evidence += (f"\n\n=== NOTE ===\nThe document search may be incomplete "
                         f"({state.get('grade_note')}). Say what is missing instead of guessing.")
        reply = llm.invoke([SystemMessage(ANSWER_PROMPT), HumanMessage(evidence)])
        return {"answer": reply.content}          # the citation check finalises it
    return answer_node

# ------------------------------------------------------------------ citation check (no LLM)
def check_citations_node(state: State) -> dict:
    """Every [tag] must be something this run actually retrieved."""
    text = state["answer"]
    allowed = {d["doc_id"] for d in state.get("docs") or []}
    if (state.get("sql_result") or {}).get("ok"):
        allowed.add("SQL")
    cited = set(_CITE.findall(text))
    invalid = sorted(cited - allowed)
    if invalid:
        text += f"\n\n⚠️ Could not verify these sources: {', '.join(invalid)}."
    elif not cited:
        text += "\n\n⚠️ No sources were cited for this answer."
    return {"answer": text, "citations": sorted(cited & allowed),
            "invalid_citations": invalid, "messages": [AIMessage(text)]}


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
    g.add_node("grade", make_grade_node(llm))
    g.add_node("rewrite", make_rewrite_node(llm))
    g.add_node("answer", make_answer_node(llm))
    g.add_node("check_citations", check_citations_node)
    g.add_node("clarify", clarify_node)
    g.add_node("out_of_scope", out_of_scope_node)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_after_router, ["sql", "docs", "clarify", "out_of_scope"])
    g.add_conditional_edges("sql", route_after_sql, ["docs", "answer"])
    g.add_edge("docs", "grade")
    g.add_conditional_edges("grade", route_after_grade, ["answer", "rewrite"])
    g.add_edge("rewrite", "docs")                      # the loop
    g.add_edge("answer", "check_citations")
    for end_node in ("check_citations", "clarify", "out_of_scope"):
        g.add_edge(end_node, END)
    return g.compile(checkpointer=checkpointer)