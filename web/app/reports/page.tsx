"use client";

import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";

type ReportSource = {
  index: number;
  document_id: string;
  label: string;
  filename?: string | null;
  doc_no?: string | null;
  doc_date?: string | null;
  dept?: string | null;
  score: number;
};

type WorkItem = {
  work_id: string;
  work_title: string;
  task_category: string;
  terms?: string[];
  document_count: number;
  document_types: string[];
};

type ReportResponse = {
  status: string;
  engine: string;
  skill_chain: string[];
  report_type: string;
  report_label: string;
  title: string;
  sender: string;
  recipient: string;
  target_year?: number | null;
  query: string;
  body: string;
  source_count: number;
  sources: ReportSource[];
  work_items: WorkItem[];
  quality_checks: string[];
};

const REPORT_TYPES = [
  { value: "result", label: "결과 보고" },
  { value: "plan", label: "계획 보고" },
  { value: "cooperation", label: "협조 요청" },
  { value: "briefing", label: "내부 보고" },
];

export default function ReportsPage() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((value) => {
      setEmail(value);
      setReady(true);
    });
  }, []);

  return (
    <AppShell
      active="reports"
      eyebrow="업무 활용 · 보고서 생성"
      title={<>Wiki DB에서 <span className="gradient-text">공문서형 보고서</span> 만들기</>}
      lede="Wiki 문서를 근거로 보고서 초안을 만들고, Korean Gov Doc·HWPX 변환 규칙에 맞춰 제출용 문서로 정리합니다."
    >
      {!ready ? <p className="muted">로딩...</p>
        : email ? <ReportWorkspace email={email} onLogout={() => setEmail(null)} />
        : <Login onLogin={setEmail} />}
    </AppShell>
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
    <form onSubmit={submit} className="glass" style={loginBox}>
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

function ReportWorkspace({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [query, setQuery] = useState("공자아카데미 운영 결과");
  const [reportType, setReportType] = useState("result");
  const [targetYear, setTargetYear] = useState(String(new Date().getFullYear()));
  const [recipient, setRecipient] = useState("총장");
  const [sender, setSender] = useState("계명대학교 국제처");
  const [dept, setDept] = useState("");
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [result, setResult] = useState<ReportResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function logout() {
    await signOut();
    onLogout();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true);
    setErr("");
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("로그인 세션이 없습니다.");
      const year = Number(targetYear);
      const body = {
        query: query.trim(),
        report_type: reportType,
        target_year: Number.isInteger(year) && year > 2000 ? year : undefined,
        recipient: recipient.trim() || "[수신처]",
        sender: sender.trim() || "[발신기관명]",
        dept: dept.trim() || undefined,
        k: 14,
      };
      setResult(await postJson<ReportResponse>("/api/reports", token, body));
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "보고서 생성 실패");
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

      <form onSubmit={submit} className="glass query-form" style={formPanel}>
        <div style={skillStrip}>
          {["wiki-report-writer", "korean-gov-doc", "hwpx-autofill-conversion"].map((skill) => (
            <span key={skill} style={skillPill}>{skill}</span>
          ))}
        </div>
        <div className="query-grid">
          <label className="query-field">
            보고서 주제
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="예) 2026 공자아카데미 운영 결과" />
          </label>
          <label className="query-field">
            보고서 유형
            <select value={reportType} onChange={(e) => setReportType(e.target.value)}>
              {REPORT_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label className="query-field">
            대상 연도
            <input className="input" value={targetYear} onChange={(e) => setTargetYear(e.target.value)}
              inputMode="numeric" placeholder="2026" />
          </label>
        </div>
        <div className="query-grid" style={secondaryGrid}>
          <label className="query-field">
            수신
            <input className="input" value={recipient} onChange={(e) => setRecipient(e.target.value)}
              placeholder="예) 총장" />
          </label>
          <label className="query-field">
            발신기관
            <input className="input" value={sender} onChange={(e) => setSender(e.target.value)}
              placeholder="예) 계명대학교 국제처" />
          </label>
          <label className="query-field">
            부서 필터
            <input className="input" value={dept} onChange={(e) => setDept(e.target.value)}
              placeholder="예) 국제교류팀" />
          </label>
          <button className="query-submit btn btn-primary" disabled={busy}>
            {busy ? "생성 중..." : "보고서 생성"}
          </button>
        </div>
        <label className="query-field" style={templateField}>
          HWPX 양식 업로드
          <input
            className="input"
            type="file"
            accept=".hwpx,application/hwp+zip"
            onChange={(e) => setTemplateFile(e.target.files?.[0] ?? null)}
          />
        </label>
      </form>

      {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}
      {result && <ReportResult report={result} templateFile={templateFile} />}
    </section>
  );
}

function ReportResult({ report, templateFile }: { report: ReportResponse; templateFile: File | null }) {
  return (
    <div style={results}>
      <div style={summaryStrip}>
        <Metric label="근거 문서" value={report.source_count} />
        <Metric label="업무 묶음" value={report.work_items.length} />
        <Metric label="검증 항목" value={report.quality_checks.length} />
      </div>

      <section className="glass" style={widePanel}>
        <div style={resultHeader}>
          <div>
            <span className="eyebrow" style={miniEyebrow}>{report.report_label}</span>
            <h2 style={{ margin: "8px 0 0" }}>{report.title}</h2>
          </div>
          <div style={downloadActions}>
            <button className="btn btn-ghost" style={downloadButton} onClick={() => downloadHwpx(report)}>
              기본 HWPX
            </button>
            <button
              className="btn btn-primary"
              style={downloadButton}
              onClick={() => downloadTemplateHwpx(report, templateFile)}
              disabled={!templateFile}
              title={templateFile ? templateFile.name : "HWPX 양식을 먼저 업로드하세요"}
            >
              업로드 양식으로 HWPX
            </button>
          </div>
        </div>
        {templateFile && <p style={templateNote}>적용 양식: {templateFile.name}</p>}
        <pre style={reportBox}>{report.body}</pre>
      </section>

      <div style={twoColumn}>
        <section className="glass" style={panel}>
          <PanelHeader title="적용 규칙" meta={report.engine} />
          <div style={skillList}>
            {report.skill_chain.map((skill) => <span key={skill} style={skillPill}>{skill}</span>)}
          </div>
          <ol style={stepList}>
            {report.quality_checks.map((check) => <li key={check}>{check}</li>)}
          </ol>
        </section>

        <section className="glass" style={panel}>
          <PanelHeader title="업무 묶음" meta={`${report.work_items.length}건`} />
          <div style={listStack}>
            {report.work_items.length === 0 && <p className="muted" style={{ margin: 0 }}>검색된 업무 묶음이 없습니다.</p>}
            {report.work_items.map((item) => (
              <article key={item.work_id} style={itemBox}>
                <strong>{item.work_title}</strong>
                <p style={itemMeta}>{item.task_category} · {item.document_types.join(", ") || "문서"} · {item.document_count}건</p>
                <p style={itemMeta}>{item.terms?.join(", ") || "학기 정보 없음"}</p>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="glass" style={widePanel}>
        <PanelHeader title="근거 문서" meta={`${report.sources.length}건`} />
        <div style={tableWrap}>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>문서번호</th>
                <th>일자</th>
                <th>파일명</th>
                <th>부서</th>
              </tr>
            </thead>
            <tbody>
              {report.sources.map((source) => (
                <tr key={`${source.document_id}-${source.index}`}>
                  <td>{source.index}</td>
                  <td>{source.doc_no ?? "-"}</td>
                  <td>{source.doc_date ?? "-"}</td>
                  <td>{source.filename ?? source.label}</td>
                  <td>{source.dept ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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

async function downloadHwpx(report: ReportResponse): Promise<void> {
  const token = await getAccessToken();
  if (!token) {
    window.alert("로그인 세션이 없습니다.");
    return;
  }
  const filename = `${safeFilename(report.title)}.hwpx`;
  const res = await fetch("/api/hermes/hwpx", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify({
      title: report.title,
      hwpx_filename: filename,
      body: report.body,
      source_label: report.sources[0]?.label ?? report.query,
      approval_form_plan: report.quality_checks,
    }),
  });
  if (!res.ok) {
    window.alert(`HWPX 생성 실패 (${res.status})`);
    return;
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
}

async function downloadTemplateHwpx(report: ReportResponse, templateFile: File | null): Promise<void> {
  if (!templateFile) {
    window.alert("HWPX 양식을 먼저 업로드하세요.");
    return;
  }
  const token = await getAccessToken();
  if (!token) {
    window.alert("로그인 세션이 없습니다.");
    return;
  }
  const filename = `${safeFilename(report.title)}.hwpx`;
  const form = new FormData();
  form.append("template", templateFile);
  form.append("title", filename);
  form.append("body", report.body);
  const res = await fetch("/api/reports/template-hwpx", {
    method: "POST",
    headers: { authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    window.alert(`양식 HWPX 생성 실패 (${res.status})`);
    return;
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
}

function safeFilename(value: string): string {
  return value.replace(/[\\/:*?"<>|]+/g, "").trim() || "wiki-report";
}

const loginBox: CSSProperties = {
  display: "grid",
  gap: 12,
  maxWidth: 380,
};

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

const formPanel: CSSProperties = {
  display: "grid",
  gap: 14,
};

const secondaryGrid: CSSProperties = {
  marginTop: 0,
};

const templateField: CSSProperties = {
  marginTop: 2,
};

const skillStrip: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
};

const skillList: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
  marginBottom: 12,
};

const skillPill: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  maxWidth: "100%",
  padding: "4px 10px",
  borderRadius: 999,
  color: "var(--blue-bright)",
  background: "rgba(122,162,255,0.1)",
  border: "1px solid rgba(122,162,255,0.22)",
  fontSize: 12,
  fontWeight: 700,
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

const resultHeader: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 14,
  flexWrap: "wrap",
  marginBottom: 14,
};

const miniEyebrow: CSSProperties = {
  marginBottom: 0,
};

const downloadButton: CSSProperties = {
  whiteSpace: "nowrap",
};

const downloadActions: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  justifyContent: "flex-end",
  gap: 8,
};

const templateNote: CSSProperties = {
  margin: "-4px 0 12px",
  color: "var(--muted)",
  fontSize: 13,
};

const reportBox: CSSProperties = {
  whiteSpace: "pre-wrap",
  overflowX: "auto",
  margin: 0,
  background: "rgba(0,0,0,0.25)",
  border: "1px solid var(--hair-soft)",
  borderRadius: 14,
  padding: 16,
  color: "var(--text)",
  lineHeight: 1.75,
  maxHeight: 620,
};

const twoColumn: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 18,
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

const stepList: CSSProperties = {
  margin: "8px 0 0",
  paddingLeft: 22,
  color: "var(--muted)",
  fontSize: 14,
  lineHeight: 1.7,
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

const itemMeta: CSSProperties = {
  margin: "5px 0 0",
  color: "var(--muted)",
  fontSize: 13,
  lineHeight: 1.5,
};

const tableWrap: CSSProperties = {
  overflowX: "auto",
};
