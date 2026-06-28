"""KMU Wiki 검색·RAG 코어 (Phase 2).

문서 임베딩과 '동일한' 임베더(kmu_ingest.embedding)를 재사용해 쿼리를 임베딩한다
(불변식 6: 모델 핀 — 쿼리/문서 벡터 공간 일치). Supabase RLS로 권한을 강제하고,
검색된 마스킹 청크만 근거로 Claude가 인용과 함께 답한다.
"""
