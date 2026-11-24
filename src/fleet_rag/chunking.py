"""Split documents into chunks that are good units of retrieval.

Rules:
  - work orders and DTC guides are short: keep whole (one chunk each)
  - SOPs: split on markdown headings, then size-guard (~400 tokens, ~12% overlap)
  - every chunk starts with a contextual header so it still makes sense on its own
"""

"""Split documents into chunks that are good units of retrieval.

Rules:
  - work orders and DTC guides are short: keep whole (one chunk each)
  - SOPs: split on markdown headings, pack small sections together up to ~400 tokens,
    cut any oversized section into overlapping windows
  - every chunk starts with a contextual header so it still makes sense on its own
"""
import re

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")   # the tokenizer OpenAI embedding models use

META_COLS = ("doc_id", "doc_type", "title", "vin", "unit_no", "model",
             "system_category", "dtc_codes", "doc_date", "source_ref")


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


def contextual_header(doc: dict) -> str:
    """e.g. '[Work order | GOT-028 | FM | cooling | 2026-06-02]'"""
    if doc["doc_type"] == "work_order":
        parts = ["Work order", doc["unit_no"], doc["model"], doc["system_category"], str(doc["doc_date"])]
    elif doc["doc_type"] == "sop":
        parts = ["SOP", doc["doc_id"], doc["title"]]
    else:
        parts = ["Fault code guide", doc["title"]]
    return "[" + " | ".join(p for p in parts if p) + "]"


def _windows(text: str, max_tokens: int, overlap_tokens: int) -> list:
    """Cut text into token windows that overlap, so a sentence on a boundary appears in both."""
    ids = _ENC.encode(text)
    step = max_tokens - overlap_tokens
    return [_ENC.decode(ids[i:i + max_tokens]) for i in range(0, max(len(ids) - overlap_tokens, 1), step)]


def split_markdown(text: str, max_tokens: int = 400, overlap_tokens: int = 50) -> list:
    """Split on '## ' headings, pack small sections together, window anything too big."""
    body = "\n".join(line for line in text.splitlines() if not line.startswith("# "))  # header carries the title
    sections = [s.strip() for s in re.split(r"\n(?=## )", body) if s.strip()]

    chunks, current = [], ""
    for sec in sections:
        if count_tokens(sec) > max_tokens:                         # one huge section -> windows
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_windows(sec, max_tokens, overlap_tokens))
        elif count_tokens(current + "\n\n" + sec) <= max_tokens:   # still fits -> keep packing
            current = (current + "\n\n" + sec).strip()
        else:                                                      # full -> close chunk, start new
            chunks.append(current)
            current = sec
    if current:
        chunks.append(current)
    return chunks


def chunk_documents(docs: list, max_tokens: int = 400, overlap_tokens: int = 50) -> list:
    """docs (list of dicts) -> chunks (list of dicts with chunk_id, chunk_text + metadata)."""
    chunks = []
    for doc in docs:
        if doc["doc_type"] == "sop":
            pieces = split_markdown(doc["text"], max_tokens, overlap_tokens)
        else:
            pieces = [doc["text"]]
        header = contextual_header(doc)
        for i, piece in enumerate(pieces):
            chunk_text = f"{header}\n{piece}"
            chunks.append({
                **{k: doc[k] for k in META_COLS},          # copy the metadata from the document
                "chunk_id": f"{doc['doc_id']}#{i}",        # e.g. SOP-01#0, SOP-01#1
                "chunk_index": i,
                "chunk_text": chunk_text,
                "n_tokens": count_tokens(chunk_text),
            })
    return chunks