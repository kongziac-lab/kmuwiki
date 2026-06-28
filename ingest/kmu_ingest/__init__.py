"""KMU Wiki 인제스트 워커 (Phase 1).

전자결재 ZIP → 잠금탐지 → 파싱 → 마스킹 → 이그레스 게이트 → 임베딩 → Supabase.
마스터 플랜(plans/kmu-wiki-master-plan.md)의 불변식을 코드로 강제한다.
"""

__version__ = "0.1.0"
