"""Retriever tool: question -> entities -> filtered + expanded hybrid search -> context for the LLM."""
import re

import mlflow
from mlflow.entities import SpanType

UNIT = re.compile(r"\b(?:GOT|HAM|RTM|CHI)-\d{3}\b", re.I)        # e.g. GOT-028
CODE = re.compile(r"\bSPN\s*(\d+)\s*FMI\s*(\d+)\b", re.I)        # e.g. SPN 3719 FMI 16
SPN_ONLY = re.compile(r"\bSPN\s*(\d+)\b", re.I)                  # e.g. SPN 110


def extract_entities(question: str) -> dict:
    """Find trucks and fault codes mentioned in the question (exact, free, no LLM)."""
    return {
        "unit_no": sorted({m.group(0).upper() for m in UNIT.finditer(question)}),
        "dtc_codes": sorted({f"SPN {s} FMI {f}" for s, f in CODE.findall(question)}),
        "spns": sorted({int(s) for s in SPN_ONLY.findall(question)}),
    }


def expand_query(question: str, spns: list, spn_names: dict) -> str:
    """Add what each code means, so semantic search understands it."""
    meanings = [spn_names[s] for s in spns if s in spn_names]
    return f"{question} ({'; '.join(meanings)})" if meanings else question


def retrieve(question: str, index, client, spn_names: dict = None, k: int = 6) -> list:
    """Run code-filtered, truck-filtered and general searches; merge in that priority."""
    with mlflow.start_span(name="retrieve_tool", span_type=SpanType.TOOL) as span:
        ents = extract_entities(question)
        query = expand_query(question, ents["spns"], spn_names or {})
        span.set_inputs({"question": question, "entities": ents, "expanded_query": query})

        results, seen = [], set()

        def add(hits):
            for h in hits:
                if h["chunk_id"] not in seen:
                    seen.add(h["chunk_id"])
                    results.append(h)

        for code in ents["dtc_codes"]:                       # 1. documents containing this exact code
            add(index.search(query, client, k=k, filters={"dtc_code": code}))
        for unit in ents["unit_no"]:                         # 2. this truck's own history
            add(index.search(query, client, k=3, filters={"unit_no": unit}))
        add(index.search(query, client, k=k))                # 3. anything relevant

        results = results[:k + 2]
        span.set_outputs({"chunk_ids": [r["chunk_id"] for r in results]})
        return results


def format_context(results: list) -> str:
    """Turn retrieved chunks into one text block; [doc_id] tags are what the answer will cite."""
    return "\n\n".join(f"[{r['doc_id']}]\n{r['chunk_text']}" for r in results)