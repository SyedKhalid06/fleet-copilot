# Stage 2: documents and retrieval (FAISS + BM25)

Work through these in order. Each box is one sitting.

- [ ] 1. Store the OpenAI key as a Databricks secret (scope `fleet`, key `openai_api_key`)
- [ ] 2. Write 2-3 SOPs in `documents/sops/` (fill the headings)
- [ ] 3. `src/fleet_rag/documents.py` -> `work_order_documents`
- [ ] 4. `documents.py` -> `sop_documents`, `dtc_guide_documents`
- [ ] 5. Notebook 05: run it, check `gold.documents`
- [ ] 6. `src/fleet_rag/chunking.py`
- [ ] 7. Notebook 06 steps 1-5: chunk and save `gold.document_chunks`
- [ ] 8. `src/fleet_rag/retrieval.py` -> `embed_texts`, `tokenize`, `reciprocal_rank_fusion`
- [ ] 9. `retrieval.py` -> `HybridIndex` (build, save, load, search)
- [ ] 10. Notebook 06 steps 6-9: build indexes, test hybrid search
- [ ] 11. Remaining SOPs

Folders added in this stage:
- notebooks/05_build_documents.py, notebooks/06_chunk_and_index.py
- src/fleet_rag/ (documents.py, chunking.py, retrieval.py)
- documents/sops/ (8 SOP outlines)
- requirements-rag.txt
