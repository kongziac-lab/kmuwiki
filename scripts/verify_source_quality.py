from dataclasses import dataclass

from kmu_ingest.config import load_settings
from kmu_ingest.embedding import CohereEmbedder
from kmu_query.retriever import Retriever, Source
from kmu_query.source_quality import refine_sources
from supabase import create_client


@dataclass(frozen=True)
class Case:
    name: str
    query: str
    must_include: tuple[str, ...] = ()
    must_exclude: tuple[str, ...] = ()
    required_hits: tuple[str, ...] = ()


CASES = (
    Case(
        name="visit-count",
        query="우리대 학교 내방한 인원",
        must_include=("내방",),
        must_exclude=("국외 출장", "국외출장", "출장 계획", "유학생 수", "예산상세산출"),
        required_hits=("주부산중국총영사", "장춘대학교 대표단 내방"),
    ),
    Case(
        name="travel",
        query="일본 소재 대학교와의 교류 및 유학생 유치 활성화 출장자는 누구인가",
        must_include=("출장",),
        must_exclude=("내방자 명단", "우리 대학교를 내방", "예산상세산출"),
    ),
    Case(
        name="visa",
        query="탄 밍란 교수 초청장과 비자 관련 내용",
        must_include=("초청",),
        must_exclude=("출장 계획", "예산상세산출", "예산요약"),
    ),
    Case(
        name="budget",
        query="출장 소요예산과 예산상세산출 내용",
        must_include=("예산",),
        must_exclude=("내방자 명단", "초청명단"),
    ),
)


def source_text(source: Source) -> str:
    return "\n".join(part for part in (
        source.filename or "",
        source.dept or "",
        source.doc_no or "",
        source.doc_date or "",
        source.content or "",
    ) if part)


def assert_case(case: Case, retriever: Retriever) -> None:
    raw = retriever.retrieve(case.query, 30)
    refined = refine_sources(case.query, raw, limit=8)

    print(f"\n[{case.name}] raw {len(raw)} refined {len(refined)}")
    for i, source in enumerate(refined, 1):
        print(f"{i}. {source.filename} | {source.dept} | {source.score:.4f}")

    if not refined:
        raise SystemExit(f"{case.name}: no refined sources")

    joined = "\n\n".join(source_text(source) for source in refined)
    for term in case.must_include:
        if term not in joined:
            raise SystemExit(f"{case.name}: missing required term {term!r}")
    for term in case.must_exclude:
        if term in joined:
            raise SystemExit(f"{case.name}: excluded term survived {term!r}")
    for term in case.required_hits:
        if term not in joined:
            raise SystemExit(f"{case.name}: missing expected source/evidence {term!r}")


def main() -> int:
    settings = load_settings()
    client = create_client(settings.supabase_url, settings.supabase_service_key)
    embedder = CohereEmbedder(settings.embed_model, settings.embed_version, api_key=settings.cohere_api_key)
    retriever = Retriever(client, embedder)
    for case in CASES:
        assert_case(case, retriever)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
