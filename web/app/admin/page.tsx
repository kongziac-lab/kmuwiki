"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";

type Summary = {
  zip_count?: number;
  document_count?: number;
  chunk_count?: number;
  review_required?: number;
  status_counts?: Record<string, number>;
  category_counts?: Record<string, number>;
  latest_imported_at?: string | null;
  latest_processed_at?: string | null;
};

type ReviewDocument = {
  id: string;
  filename: string;
  source_path?: string | null;
  path_in_zip: string;
  status: string;
  dept?: string | null;
  security_level?: string | null;
  task_category?: string | null;
  classification_confidence?: number | null;
  review_required: boolean;
  doc_date?: string | null;
  error?: string | null;
};

type LocalIngestStatus = {
  allowed: boolean;
  zipDir: string;
  host: string;
  production: boolean;
};

export default function AdminPage() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((value) => {
      setEmail(value);
      setReady(true);
    });
  }, []);

  if (!ready) return <Frame><p style={muted}>로딩...</p></Frame>;
  return (
    <Frame>
      {email ? <Dashboard email={email} onLogout={() => setEmail(null)} /> : <Login onLogin={setEmail} />}
    </Frame>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
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

function Login({ onLogin }: { onLogin: (email: string) => void }) {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
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
      <button className="btn btn-primary" disabled={busy}>{busy ? "확인 중…" : "로그인"}</button>
      {err && <p className="error">{err}</p>}
    </form>
  );
}

function Dashboard({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [reviewDocs, setReviewDocs] = useState<ReviewDocument[]>([]);
  const [ingest, setIngest] = useState<LocalIngestStatus | null>(null);
  const [zipDirInput, setZipDirInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [ingestBusy, setIngestBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [err, setErr] = useState("");

  const statusCounts = useMemo(() => summary?.status_counts ?? {}, [summary]);
  const categoryCounts = useMemo(() => summary?.category_counts ?? {}, [summary]);

  const authFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    const token = await getAccessToken();
    const headers = new Headers(init.headers);
    headers.set("content-type", headers.get("content-type") ?? "application/json");
    if (token) headers.set("authorization", `Bearer ${token}`);
    return fetch(url, { ...init, headers });
  }, []);

  const refresh = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      const [summaryRes, reviewRes, ingestRes] = await Promise.all([
        authFetch("/api/admin/summary"),
        authFetch("/api/admin/review?limit=50"),
        authFetch("/api/admin/ingest"),
      ]);
      if (summaryRes.status === 403 || reviewRes.status === 403) {
        setErr("관리자 권한이 없습니다.");
        setSummary(null);
        setReviewDocs([]);
        return;
      }
      if (!summaryRes.ok) throw new Error(`summary ${summaryRes.status}`);
      if (!reviewRes.ok) throw new Error(`review ${reviewRes.status}`);
      setSummary(await summaryRes.json());
      const reviewBody = await reviewRes.json();
      setReviewDocs(Array.isArray(reviewBody.documents) ? reviewBody.documents : []);
      const ingestBody = ingestRes.ok ? await ingestRes.json() as LocalIngestStatus : null;
      setIngest(ingestBody);
      if (ingestBody?.zipDir) {
        setZipDirInput((value) => value.trim() ? value : ingestBody.zipDir);
      }
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "대시보드 조회 실패");
    } finally {
      setBusy(false);
    }
  }, [authFetch]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function logout() {
    await signOut();
    onLogout();
  }

  async function runIngest() {
    setIngestBusy(true);
    setMessage("");
    setErr("");
    try {
      const res = await authFetch("/api/admin/ingest", {
        method: "POST",
        body: JSON.stringify({ zipDir: zipDirInput.trim() }),
      });
      const text = await res.text();
      if (!res.ok) throw new Error(text || `ingest ${res.status}`);
      const body = JSON.parse(text);
      setMessage(`인제스트 완료: ${body.zipDir}`);
      await refresh();
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "인제스트 실행 실패");
    } finally {
      setIngestBusy(false);
    }
  }

  async function markReviewed(doc: ReviewDocument) {
    setErr("");
    const res = await authFetch("/api/admin/review", {
      method: "PATCH",
      body: JSON.stringify({
        document_id: doc.id,
        dept: doc.dept,
        security_level: doc.security_level ?? "일반",
        task_category: doc.task_category ?? "미분류",
        review_required: false,
      }),
    });
    if (!res.ok) {
      setErr(await res.text());
      return;
    }
    await refresh();
  }

  return (
    <section>
      <div style={accountRow}>
        <span style={muted}>{email}</span>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={refresh} disabled={busy} style={smallButton}>{busy ? "갱신 중" : "새로고침"}</button>
          <button onClick={logout} style={smallButton}>로그아웃</button>
        </div>
      </div>

      {err && <p style={errorText}>{err}</p>}
      {message && <p style={okText}>{message}</p>}

      <div style={metricGrid}>
        <Metric label="ZIP" value={summary?.zip_count ?? 0} accent="linear-gradient(90deg, #7aa2ff, #4ad7ff)" />
        <Metric label="문서" value={summary?.document_count ?? 0} accent="linear-gradient(90deg, #8cffc7, #7aa2ff)" />
        <Metric label="청크" value={summary?.chunk_count ?? 0} accent="linear-gradient(90deg, #f6c85f, #ff8a4c)" />
        <Metric label="검토 필요" value={summary?.review_required ?? 0} accent="linear-gradient(90deg, #ff7a8a, #c084fc)" />
      </div>

      <div className="admin-dashboard-grid">
        <section className="admin-dashboard-card admin-dashboard-card-wide">
          <div style={sectionHead}>
            <h2 style={sectionTitle}>로컬 인제스트</h2>
            <button onClick={runIngest} disabled={!ingest?.allowed || ingestBusy || !zipDirInput.trim()} style={button}>
              {ingestBusy ? "실행 중..." : "인제스트 실행"}
            </button>
          </div>
          <label style={fieldLabel}>
            로컬 ZIP 폴더
            <input
              className="input"
              value={zipDirInput}
              onChange={(event) => setZipDirInput(event.target.value)}
              placeholder="/Users/kdh/Documents/KMU-Wiki-Zips 또는 \\\\NAS\\KMU-Wiki-Zips"
            />
          </label>
          <p style={helperText}>localhost 관리자 화면에서만 실행됩니다. macOS 절대경로, Windows 드라이브, NAS UNC 경로를 입력할 수 있습니다.</p>
          <dl style={detailsGrid}>
            <Info label="기본 폴더" value={ingest?.zipDir ?? "-"} />
            <Info label="실행 폴더" value={zipDirInput.trim() || "-"} />
            <Info label="호스트" value={ingest?.host ?? "-"} />
            <Info label="상태" value={ingest?.allowed ? "실행 가능" : "localhost 전용"} />
          </dl>
        </section>

        <section className="admin-dashboard-card">
          <h2 style={sectionTitle}>상태</h2>
          <div style={pillRow}>
            {Object.entries(statusCounts).map(([key, value]) => <Pill key={key} label={key} value={value} />)}
          </div>
        </section>

        <section className="admin-dashboard-card">
          <h2 style={sectionTitle}>업무 분류</h2>
          <div style={pillRow}>
            {Object.entries(categoryCounts).map(([key, value]) => <Pill key={key} label={key} value={value} />)}
          </div>
        </section>
      </div>

      <details className="admin-review-panel">
        <summary className="admin-review-summary">
          <span>검토 큐</span>
          <span className="admin-review-count">{reviewDocs.length.toLocaleString()}건</span>
        </summary>
        <div className="admin-review-body">
          <table style={table}>
            <thead>
              <tr>
                <Th>문서</Th>
                <Th>상태</Th>
                <Th>업무</Th>
                <Th>보안</Th>
                <Th>처리</Th>
              </tr>
            </thead>
            <tbody>
              {reviewDocs.map((doc) => (
                <tr key={doc.id}>
                  <Td>
                    <strong>{doc.filename}</strong>
                    <div style={tiny}>{doc.source_path || doc.path_in_zip}</div>
                    {doc.error && <div style={errorTiny}>{doc.error}</div>}
                  </Td>
                  <Td>{doc.status}</Td>
                  <Td>{doc.task_category || "미분류"}</Td>
                  <Td>{doc.security_level || "미상"}</Td>
                  <Td><button onClick={() => markReviewed(doc)} style={smallButton}>검토완료</button></Td>
                </tr>
              ))}
              {reviewDocs.length === 0 && (
                <tr><Td colSpan={5}>검토 대기 문서가 없습니다.</Td></tr>
              )}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function Metric({ label, value, accent }: { label: string; value: number; accent: string }) {
  const style = { "--metric-accent": accent } as React.CSSProperties;

  return (
    <div className="admin-metric" style={style}>
      <span className="admin-metric-label">{label}</span>
      <strong className="admin-metric-value">{value.toLocaleString()}</strong>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt style={tiny}>{label}</dt>
      <dd style={{ margin: "4px 0 0", wordBreak: "break-all" }}>{value}</dd>
    </div>
  );
}

function Pill({ label, value }: { label: string; value: number }) {
  return <span style={pill}>{label} <strong>{value}</strong></span>;
}

function Th({ children }: { children: React.ReactNode }) {
  return <th style={th}>{children}</th>;
}

function Td({ children, colSpan }: { children: React.ReactNode; colSpan?: number }) {
  return <td colSpan={colSpan} style={td}>{children}</td>;
}

const HAIR = "1px solid rgba(255,255,255,0.12)";
const HAIR_SOFT = "1px solid rgba(255,255,255,0.07)";
const muted: React.CSSProperties = { color: "#9aa6d6", margin: "8px 0 0" };
const button: React.CSSProperties = { padding: "12px 22px", fontSize: 15, fontWeight: 600, color: "#0a0f2c", background: "linear-gradient(180deg,#aac4ff,#5b8bff)", border: "none", borderRadius: 999, cursor: "pointer" };
const smallButton: React.CSSProperties = { padding: "7px 14px", fontSize: 13, color: "#eef2ff", background: "rgba(255,255,255,0.09)", border: HAIR, borderRadius: 999, cursor: "pointer" };
const accountRow: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 };
const metricGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 14 };
const sectionHead: React.CSSProperties = { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" };
const sectionTitle: React.CSSProperties = { margin: 0, fontSize: 20, fontWeight: 700 };
const fieldLabel: React.CSSProperties = { display: "grid", gap: 8, marginTop: 16, color: "#9aa6d6", fontSize: 13, fontWeight: 600 };
const helperText: React.CSSProperties = { color: "#6f7aa8", fontSize: 12, margin: "8px 0 0", lineHeight: 1.5 };
const detailsGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, margin: "14px 0 0" };
const pillRow: React.CSSProperties = { display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 };
const pill: React.CSSProperties = { border: HAIR, background: "rgba(255,255,255,0.06)", borderRadius: 999, padding: "6px 12px", fontSize: 13, color: "#9aa6d6" };
const table: React.CSSProperties = { width: "100%", borderCollapse: "collapse", marginTop: 12 };
const th: React.CSSProperties = { textAlign: "left", borderBottom: HAIR, padding: "10px 8px", fontSize: 13, color: "#9aa6d6", fontWeight: 600 };
const td: React.CSSProperties = { borderBottom: HAIR_SOFT, padding: "11px 8px", verticalAlign: "top", fontSize: 14 };
const tiny: React.CSSProperties = { color: "#6f7aa8", fontSize: 12 };
const errorText: React.CSSProperties = { color: "#ff7a8a", fontSize: 13 };
const errorTiny: React.CSSProperties = { color: "#ff7a8a", fontSize: 12, marginTop: 4 };
const okText: React.CSSProperties = { color: "#5fd6a0", fontSize: 13 };
