"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";

type Citation = { n: number; label: string };

export default function Home() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((e) => { setEmail(e); setReady(true); });
  }, []);

  return (
    <AppShell
      active="chat"
      eyebrow="AI 문서 비서"
      title={<>전자결재 문서에<br /><span className="gradient-text">바로 질문하세요.</span></>}
      lede="권한 범위 안의 문서만 검색해, 근거와 출처를 함께 답합니다."
    >
      {!ready ? <p className="muted">로딩…</p>
        : email ? <Chat email={email} onLogout={() => setEmail(null)} />
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
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <span className="pill">{email}</span>
        <button className="btn btn-ghost" style={{ padding: "6px 14px", fontSize: 13 }} onClick={logout}>로그아웃</button>
      </div>

      <form onSubmit={ask} className="glass query-form">
        <div className="query-grid">
          <label className="query-field">
            <span className="sr-only">질문</span>
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="예) 교환학생 면접전형은 언제 어떻게 진행되나요?" />
          </label>
          <button className="query-submit btn btn-primary" disabled={busy}>
            {busy ? "검색 중…" : "질문"}
          </button>
        </div>
      </form>

      {(answer || citations.length > 0) && (
        <div className="glass" style={{ marginTop: 18 }}>
          {answer && <div className="answer">{answer}</div>}
          {citations.length > 0 && (
            <div className="sources">
              <h3>출처</h3>
              <ol>{citations.map((c) => <li key={c.n}>{c.label}</li>)}</ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
