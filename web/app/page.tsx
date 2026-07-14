import { ChatClient } from "@/app/ChatClient";
import { AppShell } from "@/components/AppShell";

export default function Home() {
  return (
    <AppShell
      active="chat"
      eyebrow="AI 문서 비서"
      title={<>전자결재 문서에<br /><span className="gradient-text">바로 질문하세요.</span></>}
      lede="권한 범위 안의 문서만 검색해, 근거와 출처를 함께 답합니다."
    >
      <ChatClient />
    </AppShell>
  );
}
