export const metadata = {
  title: "KMU Wiki",
  description: "전자결재 문서 검색·RAG 챗봇",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0 }}>{children}</body>
    </html>
  );
}
