"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { WorkflowBoard, type WorkflowNode } from "@/components/WorkflowBoard";
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
  graph: SavedWorkflowGraph | null;
  created_at: string;
  updated_at: string;
};

export default function WorkflowDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((userEmail) => {
      setEmail(userEmail);
      setReady(true);
    });
  }, []);

  return !ready ? <p className="muted">로딩...</p>
    : email ? <WorkflowDetail id={id} email={email} onLogout={() => setEmail(null)} />
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

function WorkflowDetail({ id, email, onLogout }: { id: string; email: string; onLogout: () => void }) {
  const [workflow, setWorkflow] = useState<SavedWorkflow | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");

  const nodes = useMemo(() => {
    return Array.isArray(workflow?.graph?.nodes) ? workflow.graph.nodes : [];
  }, [workflow]);

  useEffect(() => {
    load();
  }, [id]);

  useEffect(() => {
    if (nodes.length > 0 && !selectedId) setSelectedId(nodes[0].id);
  }, [nodes, selectedId]);

  async function load() {
    setBusy(true);
    setErr("");
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("로그인 세션이 없습니다.");
      const res = await fetch(`/api/workflows/${id}`, {
        headers: { authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      if (!res.ok) throw new Error(await res.text() || `업무흐름도 로드 실패 (${res.status})`);
      const data = await res.json();
      setWorkflow(data.workflow ?? null);
      setSelectedId(null);
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "업무흐름도 로드 실패");
      setWorkflow(null);
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
          <a className="btn btn-ghost" style={compactLink} href="/workflows">목록</a>
          <button className="btn btn-ghost" style={compactButton} onClick={load} disabled={busy}>새로고침</button>
          <button className="btn btn-ghost" style={compactButton} onClick={logout}>로그아웃</button>
        </div>
      </div>

      <section className="glass" style={detailPanel}>
        {busy && <p className="muted">불러오는 중...</p>}
        {err && <p className="error">{err}</p>}
        {!busy && workflow && (
          <>
            <div style={panelHeader}>
              <div>
                <h2 style={{ margin: 0 }}>{workflow.title}</h2>
                <p className="muted" style={{ margin: "6px 0 0" }}>
                  {workflow.query ?? "질의 없음"} · {workflow.target_year ? `${workflow.target_year}년` : "연도 미지정"} · {nodes.length}단계
                </p>
              </div>
              <span className="pill">{formatDate(workflow.created_at)}</span>
            </div>
            <WorkflowBoard nodes={nodes} selectedId={selectedId} onSelect={setSelectedId} />
          </>
        )}
        {!busy && !err && !workflow && <p className="muted">저장된 업무흐름도를 찾을 수 없습니다.</p>}
      </section>
    </section>
  );
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

const detailPanel: CSSProperties = {
  display: "grid",
  gap: 18,
};

const panelHeader: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 12,
};
