"""Evaluate the agent on the golden questions with MLflow.

dataset -> predict_fn (runs the agent) -> scorers (LLM judge + code checks) -> MLflow evaluation run
"""
import json
import uuid

from langchain_core.messages import HumanMessage
from mlflow.entities import Feedback
from mlflow.genai.scorers import scorer


# ------------------------------------------------------------------ dataset
def load_eval_set(spark, limit: int = None) -> list:
    """Golden questions in MLflow's format: {"inputs": {...}, "expectations": {...}}."""
    rows = spark.table("eval.golden_questions").orderBy("question_id").collect()
    data = [{
        "inputs": {"question": r.question},
        "expectations": {
            "question_id": r.question_id,
            "root_cause": r.expected_root_cause,
            "resolution": r.expected_resolution,
            "work_orders": list(r.evidence.work_orders or []),
        },
    } for r in rows]
    return data[:limit] if limit else data


# ------------------------------------------------------------------ predict function
def make_predict_fn(agent):
    """MLflow calls this once per question. Each question gets a fresh conversation."""
    def predict(question: str) -> dict:
        config = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 25}
        out = agent.invoke({"messages": [HumanMessage(question)]}, config)
        return {
            "answer": out.get("answer", ""),
            "route": out.get("route"),
            "citations": out.get("citations") or [],
            "invalid_citations": out.get("invalid_citations") or [],
            "doc_ids": [d["doc_id"] for d in out.get("docs") or []],
            "retries": out.get("attempts", 0),
        }
    return predict


# ------------------------------------------------------------------ scorers
JUDGE_PROMPT = """You grade answers from a truck fleet maintenance assistant.

Question: {question}
Expected root cause: {root_cause}
Expected resolution: {resolution}

Assistant's answer:
{answer}

Does the answer identify the expected root cause, and describe the resolution correctly?
Different wording is fine. "partial" = right area but missing or wrong on an important detail.
Reply as JSON: {{"score": "yes" | "partial" | "no", "rationale": "<one sentence>"}}"""

_POINTS = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def make_scorers(client, judge_model: str = "gpt-4o-mini") -> list:

    @scorer
    def root_cause_correct(inputs, outputs, expectations):
        prompt = JUDGE_PROMPT.format(question=inputs["question"], root_cause=expectations["root_cause"],
                                     resolution=expectations["resolution"], answer=outputs["answer"])
        resp = client.chat.completions.create(model=judge_model, temperature=0,
                                              response_format={"type": "json_object"},
                                              messages=[{"role": "user", "content": prompt}])
        verdict = json.loads(resp.choices[0].message.content)
        return Feedback(value=_POINTS.get(verdict.get("score"), 0.0), rationale=verdict.get("rationale"))

    @scorer
    def evidence_retrieved(outputs, expectations):
        expected = set(expectations["work_orders"])
        if not expected:
            return Feedback(value=1.0, rationale="no work orders expected (fault not yet repaired)")
        found = expected & set(outputs["doc_ids"])
        return Feedback(value=len(found) / len(expected), rationale=f"found {sorted(found)} of {sorted(expected)}")

    @scorer
    def evidence_cited(outputs, expectations):
        expected = set(expectations["work_orders"])
        if not expected:
            return Feedback(value=1.0, rationale="no work orders expected (fault not yet repaired)")
        cited = expected & set(outputs["citations"])
        return Feedback(value=len(cited) / len(expected), rationale=f"cited {sorted(cited)} of {sorted(expected)}")

    @scorer
    def citations_valid(outputs):
        return len(outputs["invalid_citations"]) == 0

    @scorer
    def answered(outputs):
        return outputs["route"] not in ("clarify", "out_of_scope")

    return [root_cause_correct, evidence_retrieved, evidence_cited, citations_valid, answered]
