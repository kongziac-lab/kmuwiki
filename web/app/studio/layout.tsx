import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";

export default function StudioLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      active="studio"
      eyebrow="업무 활용 · 스튜디오"
      title={<>검색 자료로 <span className="gradient-text">요약·마인드맵·슬라이드·인포그래픽</span></>}
      lede="검색된 근거 문서만으로 NotebookLM식 산출물을 만듭니다. 요약은 운영 LLM(마스킹 경계 유지), 나머지는 결정론적으로 생성되어 환각이 없습니다."
    >
      {children}
    </AppShell>
  );
}
