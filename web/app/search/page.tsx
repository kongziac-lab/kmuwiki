"use client";

import { useEffect, useMemo, useState } from "react";
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

  if (!ready) return <Shell><p style={{ color: "#9aa6d6" }}>로딩...</p></Shell>;
  return <Shell>{email ? <Search email={email} onLogout={() => setEmail(null)} /> : <Login onLogin={setEmail} />}</Shell>;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="page" style={{ maxWidth: 920 }}>
      <div className="topnav">
        <span className="brand">KMU Wiki</span>
        <nav>
          <a className="navlink" href="/">챗봇</a>
          <a className="navlink active" href="/search">문서 검색</a>
          <a className="navlink" href="/admin">관리자</a>
        </nav>
      </div>
      <span className="eyebrow">문서 검색</span>
      <h1>마스킹된 청크를 <span className="gradient-text">권한 범위 안에서</span> 검색</h1>
      <p className="lede">전자결재 문서의 마스킹된 청크를 권한 범위 안에서 검색합니다.</p>
      {children}
    </main>
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
        <button onClick={logout} style={{ ...btn, padding: "4px 12px", fontSize: 13 }}>로그아웃</button>
      </div>
      <form onSubmit={submit} style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="예) 면접전형 일정" style={{ ...inp, flex: 1 }} />
        <button disabled={busy} style={btn}>{busy ? "검색 중..." : "검색"}</button>
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
  const bits = [source.dept, source.doc_no, source.doc_date, source.filename].filter(Boolean);
  return bits.length ? bits.join(" · ") : `문서 ${source.document_id.slice(0, 8)}`;
}

function excerpt(content: string): string {
  const text = content.replace(/\s+/g, " ").trim();
  return text.length > 220 ? `${text.slice(0, 220)}...` : text;
}

const link: React.CSSProperties = { color: "#7aa2ff", textDecoration: "none", fontSize: 14, fontWeight: 500 };
const inp: React.CSSProperties = { padding: "13px 16px", fontSize: 15, color: "#eef2ff", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 };
const btn: React.CSSProperties = { padding: "12px 22px", fontSize: 15, fontWeight: 600, color: "#0a0f2c", background: "linear-gradient(180deg,#aac4ff,#5b8bff)", border: "none", borderRadius: 999, cursor: "pointer" };
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
