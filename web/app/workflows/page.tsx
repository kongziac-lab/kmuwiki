"use client";

import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import type { WorkflowNode } from "@/components/WorkflowBoard";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";

type SavedWorkflowGraph = {
  version?: number;
  nodes?: WorkflowNode[];
  generated_at?: string;
};

type SavedWorkflow = {
  id: string;
  title: string;
  query: string | null;
  target_year: number | null;
  created_at: string;
  updated_at: string;
  graph: SavedWorkflowGraph | null;
};

export default function WorkflowsPage() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((userEmail) => {
      setEmail(userEmail);
      setReady(true);
    });
  }, []);

  return !ready ? <p className="muted">로딩...</p>
    : email ? <SavedWorkflowList email={email} onLogout={() => setEmail(null)} />
    : <Login onLogin={setEmail} />;
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

function SavedWorkflowList({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [workflows, setWorkflows] = useState<SavedWorkflow[]>([]);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setBusy(true);
    setErr("");
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("로그인 세션이 없습니다.");
      const res = await fetch("/api/workflows", {
        headers: { authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      if (!res.ok) throw new Error(await res.text() || `업무흐름도 목록 로드 실패 (${res.status})`);
      const data = await res.json();
      setWorkflows(Array.isArray(data.workflows) ? data.workflows : []);
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "업무흐름도 목록 로드 실패");
      setWorkflows([]);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    await signOut();
    onLogout();
  }

  return (
    <section>
      <div style={accountRow}>
        <span className="pill">{email}</span>
        <div style={buttonRow}>
          <a className="btn btn-ghost" style={compactLink} href="/insights">업무 활용</a>
          <button className="btn btn-ghost" style={compactButton} onClick={load} disabled={busy}>새로고침</button>
          <button className="btn btn-ghost" style={compactButton} onClick={logout}>로그아웃</button>
        </div>
      </div>

      <section className="glass" style={listPanel}>
        <div style={panelHeader}>
          <h2 style={{ margin: 0 }}>저장된 업무흐름도</h2>
          <span className="pill">{workflows.length}건</span>
        </div>
        {busy && <p className="muted">불러오는 중...</p>}
        {err && <p className="error">{err}</p>}
        {!busy && !err && workflows.length === 0 && (
          <p className="muted" style={{ margin: 0 }}>아직 저장된 업무흐름도가 없습니다.</p>
        )}
        <div style={workflowGrid}>
          {workflows.map((workflow) => (
            <a key={workflow.id} href={`/workflows/${workflow.id}`} style={workflowCard}>
              <span style={cardMeta}>{workflow.target_year ? `${workflow.target_year}년` : "연도 미지정"}</span>
              <strong style={cardTitle}>{workflow.title}</strong>
              <span style={cardSubline}>{workflow.query ?? "질의 없음"} · {nodeCount(workflow)}단계</span>
              <span style={cardDate}>{formatDate(workflow.created_at)}</span>
            </a>
          ))}
        </div>
      </section>
    </section>
  );
}

function nodeCount(workflow: SavedWorkflow): number {
  return Array.isArray(workflow.graph?.nodes) ? workflow.graph.nodes.length : 0;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

const accountRow: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  marginBottom: 16,
};

const buttonRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  justifyContent: "flex-end",
  gap: 8,
};

const compactButton: CSSProperties = {
  padding: "6px 14px",
  fontSize: 13,
};

const compactLink: CSSProperties = {
  ...compactButton,
  display: "inline-flex",
  alignItems: "center",
};

const loginBox: CSSProperties = {
  display: "grid",
  gap: 12,
  maxWidth: 380,
};

const listPanel: CSSProperties = {
  display: "grid",
  gap: 18,
};

const panelHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
};

const workflowGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
  gap: 12,
};

const workflowCard: CSSProperties = {
  display: "grid",
  gap: 8,
  minHeight: 156,
  padding: 18,
  color: "var(--text)",
  textDecoration: "none",
  background: "rgba(255,255,255,0.045)",
  border: "1px solid var(--hair)",
  borderRadius: 18,
};

const cardMeta: CSSProperties = {
  color: "var(--blue-bright)",
  fontSize: 12,
  fontWeight: 700,
};

const cardTitle: CSSProperties = {
  color: "var(--text)",
  fontSize: 18,
  lineHeight: 1.45,
};

const cardSubline: CSSProperties = {
  color: "var(--muted)",
  fontSize: 13,
};

const cardDate: CSSProperties = {
  alignSelf: "end",
  color: "var(--muted-dim)",
  fontSize: 12,
};
