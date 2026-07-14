import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";

export default function InsightsLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      active="insights"
      eyebrow="업무 활용"
      title={<>문서 묶음에서 <span className="gradient-text">업무 흐름과 초안</span> 만들기</>}
      lede="권한 범위 안의 문서를 기반으로 분류, 일정, 보고서, 반복업무 초안을 생성합니다."
    >
      {children}
    </AppShell>
  );
}
