"""설정 (환경변수 기반). 비밀값은 코드/저장소에 두지 않는다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

EMBED_DIM = 1024  # 불변식 3: 시스템 전역 고정


def _load_dotenv() -> None:
    """ingest/.env(우선) 및 저장소 루트 .env 를 환경에 로드. python-dotenv 없으면 무시."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parent.parent  # .../ingest
    for cand in (root / ".env", root.parent / ".env"):
        if cand.exists():
            load_dotenv(cand, override=False)


_load_dotenv()


@dataclass
class Settings:
    # 입력
    zip_dir: str = os.environ.get("KMU_ZIP_DIR", "./zips")

    # 임베딩 (불변식 6: 모델 핀)
    embed_provider: str = os.environ.get("KMU_EMBED_PROVIDER", "fake")  # fake|bge-m3|openai
    embed_model: str = os.environ.get("KMU_EMBED_MODEL", "fake-deterministic")
    embed_version: str = os.environ.get("KMU_EMBED_VERSION", "v1")

    # OCR
    ocr_backend: str = os.environ.get("KMU_OCR_BACKEND", "easyocr")  # easyocr|paddle|none

    # 마스킹 정책 (§7.A). 빈 값=내부결재문 기본(성명·전화·주소 보존), "all"=전체, 또는 콤마목록.
    mask_labels: str = os.environ.get("KMU_MASK_LABELS", "")
    # NER (성명/주소 마스킹을 켠 정책에서만 사용)
    enable_ner: bool = os.environ.get("KMU_ENABLE_NER", "1") == "1"
    ner_model: str = os.environ.get("KMU_NER_MODEL", "Leo97/KoELECTRA-small-v3-modu-ner")

    # 청킹
    chunk_chars: int = int(os.environ.get("KMU_CHUNK_CHARS", "1200"))
    chunk_overlap: int = int(os.environ.get("KMU_CHUNK_OVERLAP", "200"))

    # Supabase (service_role 키는 워커 전용; 클라이언트에 절대 노출 금지)
    supabase_url: str = os.environ.get("SUPABASE_URL", "")
    # SERVICE_ROLE_KEY 또는 새 secret 키(SUPABASE_SECRET_KEY) 둘 다 허용
    supabase_service_key: str = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                                 or os.environ.get("SUPABASE_SECRET_KEY", ""))
    # 검색/RAG 측(Phase 2): anon 키 + 사용자 JWT로 RLS 적용. LLM은 Claude.
    supabase_anon_key: str = os.environ.get("SUPABASE_ANON_KEY", "")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    llm_model: str = os.environ.get("KMU_LLM_MODEL", "claude-opus-4-8")

    # 동작 모드
    dry_run: bool = os.environ.get("KMU_DRY_RUN", "0") == "1"  # DB 미적재, 콘솔 출력만


def load_settings() -> Settings:
    return Settings()
