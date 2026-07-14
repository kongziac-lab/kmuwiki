import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";

export default function SearchLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      active="search"
      eyebrow="문서 검색"
      title={<>마스킹된 청크를 <span className="gradient-text">권한 범위 안에서</span> 검색</>}
      lede="전자결재 문서의 마스킹된 청크를 권한 범위 안에서 검색합니다."
    >
      {children}
    </AppShell>
  );
}
