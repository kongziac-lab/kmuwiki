import "./globals.css";

export const metadata = {
  title: "KMU Wiki",
  description: "전자결재 문서 검색·RAG 챗봇",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <head>
        <link rel="preconnect" href="https://cdn.jsdelivr.net" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css"
        />
      </head>
      <body>
        <div className="bg-orbs" aria-hidden="true">
          <span className="orb a" />
          <span className="orb b" />
          <span className="orb c" />
        </div>
        {children}
      </body>
    </html>
  );
}
