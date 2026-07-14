"use client";

import { useEffect, useState } from "react";
import { MarkdownAnswer } from "@/components/MarkdownAnswer";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";
import { useBatchedText } from "@/lib/useBatchedText";

type Citation = { n: number; label: string };

export function ChatClient() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((value) => {
      setEmail(value);
      setReady(true);
    });
  }, []);

  return !ready ? <p className="muted">로딩…</p>
    : email ? <Chat email={email} onLogout={() => setEmail(null)} />
    : <Login onLogin={setEmail} />;
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

function Chat({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [query, setQuery] = useState("");
  const { text: answer, append: appendAnswer, flush: flushAnswer, reset: resetAnswer } = useBatchedText();
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true);
    resetAnswer();
    setCitations([]);
    try {
      const token = await getAccessToken();
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ query, k: 8 }),
      });
      if (!res.ok) throw new Error((await res.text()) || `chat ${res.status}`);
      if (!res.body) {
        appendAnswer("(응답 없음)");
        return;
      }
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
          const event = /event: (.*)/.exec(block)?.[1];
          const dataLine = /data: (.*)/.exec(block)?.[1];
          if (!event || dataLine == null) continue;
          const data = JSON.parse(dataLine);
          if (event === "citations") setCitations(data as Citation[]);
          else if (event === "token") appendAnswer(String(data));
        }
      }
    } catch (error: unknown) {
      appendAnswer(error instanceof Error ? error.message : "응답을 받지 못했습니다.");
    } finally {
      flushAnswer();
      setBusy(false);
    }
  }

  async function logout() {
    await signOut();
    onLogout();
  }

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
          {answer && <MarkdownAnswer text={answer} />}
          {citations.length > 0 && (
            <div className="sources">
              <h3>출처</h3>
              <ol>{citations.map((citation) => <li key={citation.n}>{citation.label}</li>)}</ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
