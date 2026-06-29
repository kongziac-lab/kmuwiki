"use client";

import { useEffect, useMemo, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";

type Classification = {
  document_id: string;
  task_category: string;
  document_type: string;
  year?: number | null;
  label: string;
};

type CalendarDraft = {
  status: string;
  date: string;
  title: string;
  source_document_id: string;
  source_label: string;
};

type InsightsResponse = {
  classifications: Classification[];
  workflow_mermaid: string;
  calendar_drafts: CalendarDraft[];
  report_draft: string;
};

type RecurringWork = {
  template_title: string;
  years: number[];
  document_ids: string[];
  task_category: string;
};

type UpdateReport = {
  summary: string;
  new_documents: string[];
  classifications: Classification[];
  recurring_work: RecurringWork[];
};

type DocumentDraft = {
  status: string;
  title: string;
  body: string;
  source_document_id: string;
  source_label: string;
};

type HermesResponse = {
  update_report: UpdateReport;
  recurring_work: RecurringWork[];
  drafts: DocumentDraft[];
};

type CombinedResult = {
  query: string;
  targetYear: number;
  insights: InsightsResponse;
  hermes: HermesResponse;
};

type TimelineItem = {
  when: string;
  title: string;
  detail: string;
};

export default function InsightsPage() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((value) => {
      setEmail(value);
      setReady(true);
    });
  }, []);

  if (!ready) return <Shell><p className="muted">로딩...</p></Shell>;
  return <Shell>{email ? <Workspace email={email} onLogout={() => setEmail(null)} /> : <Login onLogin={setEmail} />}</Shell>;
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="page" style={{ maxWidth: 1120 }}>
      <div className="topnav">
        <span className="brand">KMU Wiki</span>
        <nav>
          <a className="navlink" href="/">챗봇</a>
          <a className="navlink" href="/search">문서 검색</a>
          <a className="navlink active" href="/insights">업무 활용</a>
          <a className="navlink" href="/admin">관리자</a>
        </nav>
      </div>
      <span className="eyebrow">업무 활용</span>
      <h1>문서 묶음에서 <span className="gradient-text">업무 흐름과 초안</span> 만들기</h1>
      <p className="lede">권한 범위 안의 문서를 기반으로 분류, 일정, 보고서, 반복업무 초안을 생성합니다.</p>
      {children}
    </main>
  );
}

function Login({ onLogin }: { onLogin: (email: string) => void }) {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await signIn(email.trim(), pw);
      onLogin(email.trim());
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "로그인 실패");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="glass" style={{ display: "grid", gap: 12, maxWidth: 380 }}>
      <h2>로그인</h2>
      <input className="input" value={email} onChange={(e) => setEmail(e.target.value)}
        placeholder="이메일" autoComplete="username" />
      <input className="input" value={pw} onChange={(e) => setPw(e.target.value)}
        placeholder="비밀번호" type="password" autoComplete="current-password" />
      <button className="btn btn-primary" disabled={busy}>{busy ? "확인 중..." : "로그인"}</button>
      {err && <p className="error">{err}</p>}
    </form>
  );
}

function Workspace({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [query, setQuery] = useState("파견교환학생");
  const [targetYear, setTargetYear] = useState(String(new Date().getFullYear() + 1));
  const [result, setResult] = useState<CombinedResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function logout() {
    await signOut();
    onLogout();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || busy) return;

    setBusy(true);
    setErr("");
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("로그인 세션이 없습니다.");

      const parsedYear = Number(targetYear);
      const normalizedYear = Number.isInteger(parsedYear) && parsedYear > 2000 ? parsedYear : new Date().getFullYear() + 1;
      const body = { query: trimmed, k: 12, target_year: normalizedYear };
      const [insights, hermes] = await Promise.all([
        postJson<InsightsResponse>("/api/insights", token, body),
        postJson<HermesResponse>("/api/hermes", token, body),
      ]);
      setResult({ query: trimmed, targetYear: normalizedYear, insights, hermes });
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "업무 활용 생성 실패");
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div style={accountRow}>
        <span className="pill">{email}</span>
        <button className="btn btn-ghost" style={compactButton} onClick={logout}>로그아웃</button>
      </div>

      <form onSubmit={submit} className="glass" style={queryPanel}>
        <div style={queryGrid}>
          <label style={fieldLabel}>
            업무
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="예) 2026 파견교환학생" />
          </label>
          <label style={yearField}>
            대상 연도
            <input className="input" value={targetYear} onChange={(e) => setTargetYear(e.target.value)}
              inputMode="numeric" placeholder="2027" />
          </label>
          <button className="btn btn-primary" disabled={busy} style={{ alignSelf: "end", whiteSpace: "nowrap" }}>
            {busy ? "생성 중..." : "생성"}
          </button>
        </div>
      </form>

      {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}
      {result && <ResultView result={result} />}
    </section>
  );
}

function ResultView({ result }: { result: CombinedResult }) {
  const timeline = useMemo(() => parseTimeline(result.insights.workflow_mermaid), [result.insights.workflow_mermaid]);
  const classifications = result.insights.classifications ?? [];
  const calendarDrafts = result.insights.calendar_drafts ?? [];
  const recurring = result.hermes.recurring_work ?? [];
  const drafts = result.hermes.drafts ?? [];
  const newDocuments = result.hermes.update_report?.new_documents ?? [];

  return (
    <div style={results}>
      <div style={summaryStrip}>
        <Metric label="분류" value={classifications.length} />
        <Metric label="일정 초안" value={calendarDrafts.length} />
        <Metric label="신규 문서" value={newDocuments.length} />
        <Metric label={`${result.targetYear} 초안`} value={drafts.length} />
      </div>

      <section className="glass" style={widePanel}>
        <PanelHeader title="업데이트 보고" meta={result.query} />
        <p style={{ margin: 0, color: "var(--text)" }}>{result.hermes.update_report?.summary ?? "요약 없음"}</p>
        {newDocuments.length > 0 && (
          <div style={chipRow}>
            {newDocuments.slice(0, 8).map((id) => <span key={id} style={chip}>{shortId(id)}</span>)}
          </div>
        )}
      </section>

      <section className="glass" style={widePanel}>
        <PanelHeader title="업무흐름도" meta={`${timeline.length}단계`} />
        {timeline.length > 0 ? <Timeline items={timeline} /> : <pre style={codeBox}>{result.insights.workflow_mermaid}</pre>}
        <details style={{ marginTop: 14 }}>
          <summary style={detailsSummary}>Mermaid 원문</summary>
          <pre style={codeBox}>{result.insights.workflow_mermaid}</pre>
        </details>
      </section>

      <div style={twoColumn}>
        <section className="glass" style={panel}>
          <PanelHeader title="업무 분류" meta={`${classifications.length}건`} />
          <div style={tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>분류</th>
                  <th>유형</th>
                  <th>연도</th>
                  <th>문서</th>
                </tr>
              </thead>
              <tbody>
                {classifications.map((row) => (
                  <tr key={row.document_id}>
                    <td>{row.task_category}</td>
                    <td>{row.document_type}</td>
                    <td>{row.year ?? "-"}</td>
                    <td>{row.label}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="glass" style={panel}>
          <PanelHeader title="연간일정 초안" meta={`${calendarDrafts.length}건`} />
          <div style={listStack}>
            {calendarDrafts.length === 0 && <Empty>일정 후보가 없습니다.</Empty>}
            {calendarDrafts.map((draft) => (
              <article key={`${draft.date}-${draft.source_document_id}`} style={itemBox}>
                <div style={itemTop}>
                  <strong>{draft.date}</strong>
                  <span className="pill">{draft.status}</span>
                </div>
                <p style={itemTitle}>{draft.title}</p>
                <p style={itemMeta}>{draft.source_label}</p>
              </article>
            ))}
          </div>
        </section>
      </div>

      <div style={twoColumn}>
        <section className="glass" style={panel}>
          <PanelHeader title="반복업무" meta={`${recurring.length}건`} />
          <div style={listStack}>
            {recurring.length === 0 && <Empty>반복 패턴이 없습니다.</Empty>}
            {recurring.map((pattern) => (
              <article key={`${pattern.template_title}-${pattern.years.join("-")}`} style={itemBox}>
                <div style={itemTop}>
                  <strong>{pattern.template_title}</strong>
                  <span style={chip}>{pattern.task_category}</span>
                </div>
                <p style={itemMeta}>{pattern.years.join(", ")} · {pattern.document_ids.length}개 문서</p>
              </article>
            ))}
          </div>
        </section>

        <section className="glass" style={panel}>
          <PanelHeader title={`${result.targetYear} 문서 초안`} meta={`${drafts.length}건`} />
          <div style={listStack}>
            {drafts.length === 0 && <Empty>차년도 초안 후보가 없습니다.</Empty>}
            {drafts.map((draft) => (
              <article key={`${draft.source_document_id}-${draft.title}`} style={itemBox}>
                <div style={itemTop}>
                  <strong>{draft.title}</strong>
                  <span className="pill">{draft.status}</span>
                </div>
                <p style={itemMeta}>{draft.source_label}</p>
                <pre style={draftBody}>{clip(draft.body, 900)}</pre>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="glass" style={widePanel}>
        <PanelHeader title="보고서 초안" meta="Markdown" />
        <pre style={reportBox}>{result.insights.report_draft}</pre>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div style={metricBox}>
      <span style={metricLabel}>{label}</span>
      <strong style={metricValue}>{value.toLocaleString("ko-KR")}</strong>
    </div>
  );
}

function PanelHeader({ title, meta }: { title: string; meta?: string }) {
  return (
    <div style={panelHeader}>
      <h2 style={{ margin: 0 }}>{title}</h2>
      {meta && <span style={panelMeta}>{meta}</span>}
    </div>
  );
}

function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol style={timelineList}>
      {items.map((item, index) => (
        <li key={`${item.when}-${item.title}-${index}`} style={timelineItem}>
          <span style={timelineDot} />
          <div>
            <div style={itemTop}>
              <strong>{item.when}</strong>
              <span style={chip}>{index + 1}</span>
            </div>
            <p style={itemTitle}>{item.title}</p>
            <p style={itemMeta}>{item.detail}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p style={{ margin: 0, color: "var(--muted)", fontSize: 14 }}>{children}</p>;
}

async function postJson<T>(url: string, token: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${url} ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function parseTimeline(workflow_mermaid: string): TimelineItem[] {
  return workflow_mermaid
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !["timeline"].includes(line) && !line.startsWith("title "))
    .map((line) => {
      const [when = "", title = "", ...rest] = line.split(" : ");
      return { when, title, detail: rest.join(" : ") };
    })
    .filter((item) => item.when && item.title);
}

function clip(text: string, limit: number): string {
  const normalized = text.trim();
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

function shortId(id: string): string {
  return id.length > 10 ? id.slice(0, 10) : id;
}

const accountRow: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  alignItems: "center",
  gap: 10,
  marginBottom: 14,
};

const compactButton: CSSProperties = {
  padding: "6px 14px",
  fontSize: 13,
};

const queryPanel: CSSProperties = {
  padding: 16,
};

const queryGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 12,
  alignItems: "end",
};

const fieldLabel: CSSProperties = {
  display: "grid",
  gap: 6,
  color: "var(--muted)",
  fontSize: 13,
  fontWeight: 600,
};

const yearField: CSSProperties = {
  ...fieldLabel,
  minWidth: 0,
};

const results: CSSProperties = {
  display: "grid",
  gap: 18,
  marginTop: 18,
};

const summaryStrip: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 12,
};

const metricBox: CSSProperties = {
  border: "1px solid var(--hair)",
  borderRadius: 18,
  background: "rgba(255,255,255,0.055)",
  padding: 16,
};

const metricLabel: CSSProperties = {
  display: "block",
  color: "var(--muted)",
  fontSize: 12,
  marginBottom: 4,
};

const metricValue: CSSProperties = {
  color: "var(--text)",
  fontSize: 28,
  lineHeight: 1,
};

const widePanel: CSSProperties = {
  padding: 22,
};

const panel: CSSProperties = {
  padding: 22,
  minWidth: 0,
};

const panelHeader: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 12,
  marginBottom: 14,
};

const panelMeta: CSSProperties = {
  color: "var(--muted)",
  fontSize: 12,
};

const chipRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
  marginTop: 12,
};

const chip: CSSProperties = {
  display: "inline-block",
  padding: "3px 9px",
  borderRadius: 999,
  background: "rgba(122,162,255,0.12)",
  border: "1px solid rgba(122,162,255,0.22)",
  color: "var(--blue-bright)",
  fontSize: 12,
  whiteSpace: "nowrap",
};

const twoColumn: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 18,
};

const tableWrap: CSSProperties = {
  overflowX: "auto",
};

const listStack: CSSProperties = {
  display: "grid",
  gap: 10,
};

const itemBox: CSSProperties = {
  border: "1px solid var(--hair-soft)",
  borderRadius: 14,
  background: "rgba(0,0,0,0.14)",
  padding: 14,
};

const itemTop: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 10,
};

const itemTitle: CSSProperties = {
  margin: "6px 0 0",
  color: "var(--text)",
  fontWeight: 600,
};

const itemMeta: CSSProperties = {
  margin: "5px 0 0",
  color: "var(--muted)",
  fontSize: 13,
  lineHeight: 1.5,
};

const timelineList: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 10,
};

const timelineItem: CSSProperties = {
  position: "relative",
  display: "grid",
  gridTemplateColumns: "18px 1fr",
  gap: 12,
  padding: "12px 0",
  borderTop: "1px solid var(--hair-soft)",
};

const timelineDot: CSSProperties = {
  width: 10,
  height: 10,
  borderRadius: 999,
  background: "var(--blue-bright)",
  marginTop: 8,
  boxShadow: "0 0 0 5px rgba(122,162,255,0.12)",
};

const detailsSummary: CSSProperties = {
  cursor: "pointer",
  color: "var(--muted)",
  fontSize: 13,
};

const codeBox: CSSProperties = {
  whiteSpace: "pre-wrap",
  overflowX: "auto",
  margin: 0,
  background: "rgba(0,0,0,0.25)",
  border: "1px solid var(--hair-soft)",
  borderRadius: 14,
  padding: 14,
  color: "var(--muted)",
  lineHeight: 1.5,
};

const reportBox: CSSProperties = {
  ...codeBox,
  color: "var(--text)",
  maxHeight: 460,
};

const draftBody: CSSProperties = {
  ...codeBox,
  marginTop: 10,
  fontSize: 13,
  maxHeight: 220,
};
