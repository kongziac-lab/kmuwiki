"use client";

import { useState } from "react";
import { getAccessToken } from "@/lib/supabase";

type Citation = { n: number; label: string; doc_no?: string; doc_date?: string };

export default function Home() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true);
    setAnswer("");
    setCitations([]);

    const token = await getAccessToken(); // 로그인 안 했으면 null → 서버에서 deny-by-default
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(token ? { authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ query, k: 8 }),
    });

    if (!res.body) {
      setAnswer("(응답 스트림 없음)");
      setBusy(false);
      return;
    }

    // SSE 파싱: "event: <name>\ndata: <json>\n\n"
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

  return (
    <main style={{ maxWidth: 760, margin: "40px auto", padding: "0 16px" }}>
      <h1>KMU Wiki 챗봇</h1>
      <p style={{ color: "#666" }}>전자결재 문서에서 검색해 답합니다. 권한 범위 내 문서만 조회됩니다.</p>

      <form onSubmit={ask} style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="예) 2025년 학사일정 알려줘"
          style={{ flex: 1, padding: 10, fontSize: 16, border: "1px solid #ccc", borderRadius: 8 }}
        />
        <button disabled={busy} style={{ padding: "10px 20px", fontSize: 16, borderRadius: 8 }}>
          {busy ? "검색 중…" : "질문"}
        </button>
      </form>

      {answer && (
        <section style={{ marginTop: 24, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
          {answer}
        </section>
      )}

      {citations.length > 0 && (
        <aside style={{ marginTop: 24, borderTop: "1px solid #eee", paddingTop: 12 }}>
          <h3 style={{ fontSize: 14, color: "#666" }}>출처</h3>
          <ol style={{ fontSize: 14, color: "#444" }}>
            {citations.map((c) => (
              <li key={c.n}>{c.label}</li>
            ))}
          </ol>
        </aside>
      )}
    </main>
  );
}
