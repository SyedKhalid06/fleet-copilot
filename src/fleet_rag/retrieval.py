"""Hybrid retrieval: FAISS (semantic) + BM25 (keyword), fused with Reciprocal Rank Fusion.

    query ──▶ embed ──▶ FAISS top 40 ─┐
          └─▶ tokenize ─▶ BM25 top 40 ─┴─▶ RRF fuse ─▶ metadata filter ─▶ top k
"""


"""Hybrid retrieval: FAISS (semantic) + BM25 (keyword), fused with Reciprocal Rank Fusion.

    query ──▶ embed ──▶ FAISS ranking ─┐
          └─▶ tokenize ─▶ BM25 ranking ─┴─▶ RRF fuse ─▶ metadata filter ─▶ top k
"""
import json
import os
import re

import faiss
import numpy as np
from rank_bm25 import BM25Okapi


# ------------------------------------------------------------------ embeddings
def embed_texts(texts: list, client, model: str = "text-embedding-3-small", batch_size: int = 100):
    """OpenAI embeddings, batched, L2-normalised (so inner product = cosine similarity)."""
    vectors = []
    for i in range(0, len(texts), batch_size):
        resp = client.embeddings.create(model=model, input=texts[i:i + batch_size])
        vectors.extend(item.embedding for item in resp.data)
    arr = np.array(vectors, dtype="float32")
    faiss.normalize_L2(arr)            # every vector gets length 1
    return arr


# ------------------------------------------------------------------ keywords
_TOKEN = re.compile(r"[a-z0-9]+(?:[-/.][a-z0-9]+)*")   # keeps "wo-26-00325", "315/70r22.5" in one piece
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "it", "at", "by",
         "with", "was", "be", "this", "that", "what", "why", "how", "did", "does", "do"}


def tokenize(text: str) -> list:
    """Lowercase tokens for BM25, without common filler words."""
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


# ------------------------------------------------------------------ fusion
def reciprocal_rank_fusion(rankings: list, k: int = 60) -> dict:
    """rankings: list of ranked id lists -> {id: fused score}. score = sum(1 / (k + rank))."""
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


# ------------------------------------------------------------------ the index
class HybridIndex:
    """Holds the FAISS index, the BM25 index and the chunk metadata."""

    def __init__(self, chunks, embeddings):
        self.chunks = chunks
        self.embeddings = embeddings
        self.faiss = faiss.IndexFlatIP(embeddings.shape[1])   # exact inner-product search
        self.faiss.add(embeddings)
        self.bm25 = BM25Okapi([tokenize(c["chunk_text"]) for c in chunks])

    def save(self, folder: str):
        """Save the expensive part (embeddings) and the chunks; both indexes rebuild in seconds."""
        os.makedirs(folder, exist_ok=True)
        np.save(os.path.join(folder, "embeddings.npy"), self.embeddings)
        with open(os.path.join(folder, "chunks.json"), "w") as f:
            json.dump(self.chunks, f, default=str)

    @classmethod
    def load(cls, folder: str):
        with open(os.path.join(folder, "chunks.json")) as f:
            chunks = json.load(f)
        return cls(chunks, np.load(os.path.join(folder, "embeddings.npy")))

    def _allowed(self, i: int, filters: dict) -> bool:
        if not filters:
            return True
        c = self.chunks[i]
        for key, value in filters.items():
            if key == "dtc_code":
                if value not in (c.get("dtc_codes") or []):
                    return False
            elif c.get(key) != value:
                return False
        return True

    def search(self, query: str, client, k: int = 8, filters: dict = None, candidates: int = 40) -> list:
        """Top-k chunks. filters e.g. {'unit_no': 'GOT-028'} or {'doc_type': 'sop'} or {'dtc_code': 'SPN 110 FMI 16'}."""
        # 1. dense ranking (FAISS)
        q = embed_texts([query], client)
        _, ids = self.faiss.search(q, len(self.chunks))
        dense = [int(i) for i in ids[0] if i >= 0 and self._allowed(int(i), filters)][:candidates]

        # 2. keyword ranking (BM25)
        bm = self.bm25.get_scores(tokenize(query))
        sparse = [int(i) for i in np.argsort(-bm) if bm[i] > 0 and self._allowed(int(i), filters)][:candidates]

        # 3. fuse and keep the best k
        fused = reciprocal_rank_fusion([dense, sparse])
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        return [{**self.chunks[i],
                 "score": round(fused[i], 4),
                 "dense_rank": dense.index(i) + 1 if i in dense else None,
                 "bm25_rank": sparse.index(i) + 1 if i in sparse else None}
                for i in top]
