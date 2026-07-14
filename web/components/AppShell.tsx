import Link from "next/link";
import type { ReactNode } from "react";

type ActivePage = "chat" | "search" | "insights" | "studio" | "reports" | "workflows" | "admin";

const NAV_ITEMS: Array<{ key: ActivePage; href: string; label: string }> = [
  { key: "chat", href: "/", label: "챗봇" },
  { key: "search", href: "/search", label: "문서 검색" },
  { key: "insights", href: "/insights", label: "업무 활용" },
  { key: "studio", href: "/studio", label: "스튜디오" },
  { key: "reports", href: "/reports", label: "보고서 생성" },
  { key: "workflows", href: "/workflows", label: "업무흐름도" },
  { key: "admin", href: "/admin", label: "관리자" },
];

export function AppShell({
  active,
  eyebrow,
  title,
  lede,
  children,
}: {
  active: ActivePage;
  eyebrow: string;
  title: ReactNode;
  lede: string;
  children: ReactNode;
}) {
  return (
    <main className="page app-shell">
      <div className="topnav">
        <Link className="brand" href="/">KMU Wiki</Link>
        <nav>
          {NAV_ITEMS.map((item) => (
            <Link key={item.key} className={`navlink${active === item.key ? " active" : ""}`} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      <p className="lede">{lede}</p>
      {children}
    </main>
  );
}
