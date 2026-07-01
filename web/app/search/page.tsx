"use client";

import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";

type SearchSource = {
  document_id: string;
  chunk_index: number;
  content: string;
  score: number;
  filename?: string | null;
  doc_no?: string | null;
  doc_date?: string | null;
  dept?: string | null;
  citation_filename?: string | null;
  citation_doc_no?: string | null;
  citation_doc_date?: string | null;
  citation_dept?: string | null;
};

export default function SearchPage() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((e) => {
      setEmail(e);
      setReady(true);
    });
  }, []);

  return (
    <AppShell
      active="search"
      eyebrow="문서 검색"
      title={<>마스킹된 청크를 <span className="gradient-text">권한 범위 안에서</span> 검색</>}
      lede="전자결재 문서의 마스킹된 청크를 권한 범위 안에서 검색합니다."
    >
      {!ready ? <p className="muted">로딩...</p>
        : email ? <Search email={email} onLogout={() => setEmail(null)} />
        : <Login onLogin={setEmail} />}
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
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "로그인 실패");
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

function Search({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchSource[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const resultCount = useMemo(() => results.length, [results]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true);
    setErr("");
    try {
      const token = await getAccessToken();
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ query, k: 12 }),
      });
      if (!res.ok) {
        setResults([]);
        setErr(`검색 실패 (${res.status})`);
        return;
      }
      const data = await res.json();
      setResults(Array.isArray(data.sources) ? data.sources : []);
    } catch (e: unknown) {
      setResults([]);
      setErr(e instanceof Error ? e.message : "검색 실패");
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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
        <span style={{ fontSize: 13, color: "#9aa6d6" }}>{email}</span>
        <button className="btn btn-ghost" onClick={logout} style={{ padding: "6px 14px", fontSize: 13 }}>로그아웃</button>
      </div>
      <form onSubmit={submit} className="glass query-form" style={{ marginTop: 16 }}>
        <div className="query-grid">
          <label className="query-field">
            <span className="sr-only">검색어</span>
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="예) 면접전형 일정" />
          </label>
          <button className="query-submit btn btn-primary" disabled={busy}>{busy ? "검색 중..." : "검색"}</button>
        </div>
      </form>
      {err && <p style={{ color: "#ff7a8a", fontSize: 13 }}>{err}</p>}
      {resultCount > 0 && <p style={{ color: "#9aa6d6", fontSize: 13, marginTop: 16 }}>{resultCount}개 결과</p>}
      <ol style={{ listStyle: "none", margin: "16px 0 0", padding: 0, display: "grid", gap: 12 }}>
        {results.map((source, idx) => (
          <li key={`${source.document_id}-${source.chunk_index}`} style={resultBox}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
              <strong>{idx + 1}. {label(source)}</strong>
              <span style={{ color: "#6f7aa8", fontSize: 12 }}>{source.score.toFixed(4)}</span>
            </div>
            <p style={{ color: "#c7d0f0", lineHeight: 1.6, margin: "8px 0 0" }}>{excerpt(source.content)}</p>
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: "pointer", color: "#c7d0f0", fontSize: 13 }}>마스킹 청크 보기</summary>
              <pre style={chunkBox}>{source.content}</pre>
            </details>
          </li>
        ))}
      </ol>
    </section>
  );
}

function label(source: SearchSource): string {
  let dept = source.citation_dept ?? source.dept;
  const docNo = source.citation_doc_no ?? source.doc_no;
  if (dept && docNo?.startsWith(`${dept}-`)) {
    dept = null;
  }
  const bits = [
    dept,
    docNo,
    source.citation_doc_date ?? source.doc_date,
    source.citation_filename ?? source.filename,
  ].filter(Boolean);
  return bits.length ? bits.join(" · ") : `문서 ${source.document_id.slice(0, 8)}`;
}

function excerpt(content: string): string {
  const text = content.replace(/\s+/g, " ").trim();
  return text.length > 220 ? `${text.slice(0, 220)}...` : text;
}

const resultBox: React.CSSProperties = {
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: 18,
  padding: 18,
  background: "rgba(255,255,255,0.055)",
  backdropFilter: "blur(18px)",
  WebkitBackdropFilter: "blur(18px)",
};
const chunkBox: React.CSSProperties = {
  whiteSpace: "pre-wrap",
  overflowX: "auto",
  background: "rgba(0,0,0,0.25)",
  border: "1px solid rgba(255,255,255,0.07)",
  borderRadius: 12,
  padding: 12,
  lineHeight: 1.5,
  color: "#c7d0f0",
};
