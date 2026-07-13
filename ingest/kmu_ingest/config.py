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
    embed_provider: str = os.environ.get("KMU_EMBED_PROVIDER", "fake")  # fake|bge-m3|cohere
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
    max_chunks_per_doc: int = int(os.environ.get("KMU_MAX_CHUNKS_PER_DOC", "80"))

    # Supabase (service_role 키는 워커 전용; 클라이언트에 절대 노출 금지)
    supabase_url: str = os.environ.get("SUPABASE_URL", "")
    # SERVICE_ROLE_KEY 또는 새 secret 키(SUPABASE_SECRET_KEY) 둘 다 허용
    supabase_service_key: str = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                                 or os.environ.get("SUPABASE_SECRET_KEY", ""))
    # 검색/RAG 측(Phase 2): anon 키 + 사용자 JWT로 RLS 적용.
    supabase_anon_key: str = os.environ.get("SUPABASE_ANON_KEY", "")
    # LLM(답변 생성). 제공자 미지정 시 키 보유로 자동(anthropic 우선, 없으면 cohere).
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    cohere_api_key: str = os.environ.get("COHERE_API_KEY", "")
    # Nous Portal(OpenAI 호환 aggregator). 답변 생성 전용. 임베딩은 항상 Cohere(1024d) 유지.
    nous_api_key: str = os.environ.get("NOUS_API_KEY", "")
    nous_base_url: str = os.environ.get("KMU_NOUS_BASE_URL", "https://inference-api.nousresearch.com/v1")
    nous_model: str = os.environ.get("KMU_NOUS_MODEL", "Hermes-4-70B")
    # Google Gemini 직접 연결(google-genai). 답변 생성 전용. 임베딩은 항상 Cohere(1024d) 유지.
    gemini_api_key: str = (os.environ.get("GEMINI_API_KEY")
                           or os.environ.get("GOOGLE_API_KEY", ""))
    gemini_model: str = os.environ.get("KMU_GEMINI_MODEL", "gemini-2.5-pro")
    gemini_use_vertex: bool = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "0").lower() in ("1", "true", "yes")
    gemini_project: str = (os.environ.get("GOOGLE_CLOUD_PROJECT")
                           or os.environ.get("GOOGLE_GENAI_PROJECT", ""))
    gemini_location: str = (os.environ.get("GOOGLE_CLOUD_LOCATION")
                            or os.environ.get("GOOGLE_GENAI_LOCATION", "asia-northeast3"))
    llm_provider: str = os.environ.get("KMU_LLM_PROVIDER", "")  # "" = 자동
    llm_model: str = os.environ.get("KMU_LLM_MODEL", "claude-opus-4-8")
    cohere_chat_model: str = os.environ.get("KMU_COHERE_CHAT_MODEL", "command-r-plus-08-2024")
    # 웹 프록시 ↔ Python API 사이의 공유 시크릿. 설정된 경우 /search, /chat은 이 헤더가 필요하다.
    api_shared_secret: str = os.environ.get("KMU_API_SHARED_SECRET", "")
    # CORS 허용 출처(콤마 구분). 기본 "*"(개발 편의). 프로덕션은 실제 웹앱 도메인으로 좁힐 것.
    #   예: KMU_ALLOWED_ORIGINS="https://kmuwiki.example.com,https://www.example.com"
    allowed_origins: str = os.environ.get("KMU_ALLOWED_ORIGINS", "*")
    api_max_k: int = int(os.environ.get("KMU_API_MAX_K", "20"))
    api_default_k: int = int(os.environ.get("KMU_API_DEFAULT_K", "8"))
    audit_retention_days: int = int(os.environ.get("KMU_AUDIT_RETENTION_DAYS", "180"))
    rerank_provider: str = os.environ.get("KMU_RERANK_PROVIDER", "cohere")
    rerank_model: str = os.environ.get("KMU_RERANK_MODEL", "rerank-v3.5")
    rerank_max_candidates: int = int(os.environ.get("KMU_RERANK_MAX_CANDIDATES", "50"))

    def resolve_llm(self) -> tuple[str, str]:
        """(provider, model). 명시(KMU_LLM_PROVIDER) 우선. 자동은 anthropic 키 있으면 anthropic, 없으면 cohere.
        nous/gemini는 silent-switch 방지를 위해 KMU_LLM_PROVIDER 로 명시했을 때만 켜진다."""
        provider = self.llm_provider or ("anthropic" if self.anthropic_api_key else "cohere")
        model = {
            "anthropic": self.llm_model,
            "nous": self.nous_model,
            "gemini": self.gemini_model,
        }.get(provider, self.cohere_chat_model)
        return provider, model

    # 동작 모드
    dry_run: bool = os.environ.get("KMU_DRY_RUN", "0") == "1"  # DB 미적재, 콘솔 출력만


def load_settings() -> Settings:
    return Settings()
