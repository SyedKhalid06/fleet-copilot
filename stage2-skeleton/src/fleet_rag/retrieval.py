"""Hybrid retrieval: FAISS (semantic) + BM25 (keyword), fused with Reciprocal Rank Fusion.

    query ──▶ embed ──▶ FAISS top 40 ─┐
          └─▶ tokenize ─▶ BM25 top 40 ─┴─▶ RRF fuse ─▶ metadata filter ─▶ top k
"""


def embed_texts(texts: list, client, model: str = "text-embedding-3-small", batch_size: int = 100):
    """OpenAI embeddings, batched, L2-normalised (so inner product = cosine)."""
    # TODO
    raise NotImplementedError


def tokenize(text: str) -> list:
    """Lowercase tokens for BM25. Keep codes like 'spn', '110', 'wo-26-00325' intact."""
    # TODO
    raise NotImplementedError


class HybridIndex:
    """Holds the FAISS index, the BM25 index and the chunk metadata."""

    def __init__(self, chunks, embeddings):
        # TODO
        raise NotImplementedError

    def save(self, folder: str):
        # TODO
        raise NotImplementedError

    @classmethod
    def load(cls, folder: str):
        # TODO
        raise NotImplementedError

    def search(self, query: str, client, k: int = 8, filters: dict = None) -> list:
        """Return top-k chunks with scores. filters e.g. {'unit_no': 'GOT-028', 'doc_type': 'work_order'}."""
        # TODO
        raise NotImplementedError


def reciprocal_rank_fusion(rankings: list, k: int = 60) -> dict:
    """rankings: list of ranked id lists -> {id: fused score}. score = sum(1 / (k + rank))."""
    # TODO
    raise NotImplementedError
