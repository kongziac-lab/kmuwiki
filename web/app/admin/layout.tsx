import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      active="admin"
      eyebrow="관리자"
      title="KMU Wiki 운영 대시보드"
      lede="문서 적재 상태, 검토 큐, 로컬 인제스트 실행을 관리합니다."
    >
      {children}
    </AppShell>
  );
}
