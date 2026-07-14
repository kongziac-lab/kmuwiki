import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";

export default function ReportsLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      active="reports"
      eyebrow="업무 활용 · 보고서 생성"
      title={<>Wiki DB에서 <span className="gradient-text">공문서형 보고서</span> 만들기</>}
      lede="Wiki 문서를 근거로 보고서 초안을 만들고, Korean Gov Doc·HWPX 변환 규칙에 맞춰 제출용 문서로 정리합니다."
    >
      {children}
    </AppShell>
  );
}
