"""Build the complete Fleet Copilot agent in one call (used by evaluation and serving)."""
from langchain_openai import ChatOpenAI
from openai import OpenAI

from fleet_rag.retrieval import HybridIndex

from . import graph as A
from . import sql_tool as S


def create_agent(spark, catalog: str, openai_key: str, model: str = "gpt-4o-mini", checkpointer=None):
    """Returns (agent, openai_client)."""
    client = OpenAI(api_key=openai_key)
    llm = ChatOpenAI(model=model, temperature=0, api_key=openai_key)
    tools = A.FleetTools(
        spark=spark,
        client=client,
        schema_context=S.get_schema_context(spark, catalog),
        index=HybridIndex.load(f"/Volumes/{catalog}/gold/rag_index/v1"),
        spn_names={r.spn: r.spn_name for r in spark.table("silver.spn_reference").collect()},
        sql_model=model,
    )
    return A.build_agent(llm, tools, checkpointer=checkpointer), client