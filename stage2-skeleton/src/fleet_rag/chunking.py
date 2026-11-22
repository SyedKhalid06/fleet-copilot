"""Split documents into chunks that are good units of retrieval.

Rules:
  - work orders and DTC guides are short: keep whole (one chunk each)
  - SOPs: split on markdown headings, then size-guard (~400 tokens, ~12% overlap)
  - every chunk starts with a contextual header so it still makes sense on its own
"""


def count_tokens(text: str) -> int:
    # TODO
    raise NotImplementedError


def contextual_header(doc: dict) -> str:
    """e.g. '[Work order | GOT-028 | FM | cooling | 2026-06-02]'"""
    # TODO
    raise NotImplementedError


def split_markdown(text: str, max_tokens: int = 400, overlap_tokens: int = 50) -> list:
    """Split on headings first, then by size."""
    # TODO
    raise NotImplementedError


def chunk_documents(docs: list) -> list:
    """docs (list of dicts) -> chunks (list of dicts with chunk_id, doc_id, chunk_text + metadata)."""
    # TODO
    raise NotImplementedError
