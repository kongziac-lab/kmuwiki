"use client";

import { useEffect, useState } from "react";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";

type Citation = { n: number; label: string };

export default function Home() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((e) => { setEmail(e); setReady(true); });
  }, []);

  if (!ready) return <Shell><p style={{ color: "#888" }}>로딩…</p></Shell>;
  return <Shell>{email ? <Chat email={email} onLogout={() => setEmail(null)} /> : <Login onLogin={setEmail} />}</Shell>;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main style={{ maxWidth: 760, margin: "40px auto", padding: "0 16px" }}>
      <h1>KMU Wiki 챗봇</h1>
      <p style={{ color: "#666" }}>전자결재 문서에서 검색해 답합니다. 권한 범위 내 문서만 조회됩니다.</p>
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
    setBusy(true); setErr("");
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
    <form onSubmit={submit} style={{ marginTop: 24, display: "grid", gap: 8, maxWidth: 320 }}>
      <h3 style={{ margin: 0 }}>로그인</h3>
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="이메일"
        autoComplete="username" style={inp} />
      <input value={pw} onChange={(e) => setPw(e.target.value)} placeholder="비밀번호"
        type="password" autoComplete="current-password" style={inp} />
      <button disabled={busy} style={btn}>{busy ? "확인 중…" : "로그인"}</button>
      {err && <p style={{ color: "#c00", fontSize: 13 }}>{err}</p>}
    </form>
  );
}

function Chat({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true); setAnswer(""); setCitations([]);
    const token = await getAccessToken();
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ query, k: 8 }),
    });
    if (!res.body) { setAnswer("(응답 없음)"); setBusy(false); return; }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const blocks = buf.split("\n\n");
      buf = blocks.pop() ?? "";
      for (const block of blocks) {
        const ev = /event: (.*)/.exec(block)?.[1];
        const dataLine = /data: (.*)/.exec(block)?.[1];
        if (!ev || dataLine == null) continue;
        const data = JSON.parse(dataLine);
        if (ev === "citations") setCitations(data as Citation[]);
        else if (ev === "token") setAnswer((a) => a + data);
      }
    }
    setBusy(false);
  }

  async function logout() { await signOut(); onLogout(); }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
        <span style={{ fontSize: 13, color: "#666" }}>{email}</span>
        <button onClick={logout} style={{ ...btn, padding: "4px 12px", fontSize: 13 }}>로그아웃</button>
      </div>
      <form onSubmit={ask} style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="예) 교환학생 선발 일정 알려줘" style={{ ...inp, flex: 1 }} />
        <button disabled={busy} style={btn}>{busy ? "검색 중…" : "질문"}</button>
      </form>
      {answer && <section style={{ marginTop: 24, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{answer}</section>}
      {citations.length > 0 && (
        <aside style={{ marginTop: 24, borderTop: "1px solid #eee", paddingTop: 12 }}>
          <h3 style={{ fontSize: 14, color: "#666" }}>출처</h3>
          <ol style={{ fontSize: 14, color: "#444" }}>
            {citations.map((c) => <li key={c.n}>{c.label}</li>)}
          </ol>
        </aside>
      )}
    </div>
  );
}

const inp: React.CSSProperties = { padding: 10, fontSize: 16, border: "1px solid #ccc", borderRadius: 8 };
const btn: React.CSSProperties = { padding: "10px 20px", fontSize: 16, borderRadius: 8, cursor: "pointer" };
