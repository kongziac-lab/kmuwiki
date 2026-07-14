import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";

export default function WorkflowsLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      active="workflows"
      eyebrow="업무흐름도"
      title={<>저장된 <span className="gradient-text">업무흐름도</span></>}
      lede="업무 활용에서 생성한 흐름도를 별도 페이지로 저장하고 다시 확인합니다."
    >
      {children}
    </AppShell>
  );
}
