"use client";

import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";
import { useBatchedText } from "@/lib/useBatchedText";

type Citation = { n: number; label: string };

type Metrics = {
  query: string;
  document_count: number;
  work_item_count: number;
  category_count: number;
  categories: { label: string; count: number }[];
  document_types: { label: string; count: number }[];
  departments: { label: string; count: number }[];
  period_start?: string | null;
  period_end?: string | null;
};

type StudioResponse = {
  metrics: Metrics;
  mindmap_mermaid: string;
  mindmap_grouping?: "semantic" | "rule";
  slides_marp: string;
  infographic_svg: string;
};

type Tab = "summary" | "mindmap" | "slides" | "infographic";

export default function StudioPage() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((value) => {
      setEmail(value);
      setReady(true);
    });
  }, []);

  return !ready ? <p className="muted">로딩...</p>
    : email ? <StudioWorkspace email={email} onLogout={() => setEmail(null)} />
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

function StudioWorkspace({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [query, setQuery] = useState("교환학생 선발");
  const [dept, setDept] = useState("");
  const [tab, setTab] = useState<Tab>("summary");

  const [studio, setStudio] = useState<StudioResponse | null>(null);
  const { text: summary, append: appendSummary, flush: flushSummary, reset: resetSummary } = useBatchedText();
  const [citations, setCitations] = useState<Citation[]>([]);
  const [busy, setBusy] = useState(false);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [err, setErr] = useState("");

  async function logout() {
    await signOut();
    onLogout();
  }

  async function generate(e: FormEvent) {
    e.preventDefault();
    if (!query.trim() || busy) return;
    setBusy(true);
    setErr("");
    setStudio(null);
    resetSummary();
    setCitations([]);
    setSummaryBusy(true);
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("로그인 세션이 없습니다.");
      const body = { query: query.trim(), dept: dept.trim() || undefined, k: 12 };
      // 한 번의 검색 결과로 산출물과 요약을 함께 스트리밍한다.
      const res = await fetch("/api/studio/stream", {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (!res.ok || !res.body) throw new Error((await res.text()) || `studio ${res.status}`);
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
          if (ev === "studio") setStudio(data as StudioResponse);
          else if (ev === "citations") setCitations(data as Citation[]);
          else if (ev === "token") appendSummary(String(data));
        }
      }
      flushSummary();
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "생성 실패");
    } finally {
      flushSummary();
      setSummaryBusy(false);
      setBusy(false);
    }
  }

  const mindmapTree = useMemo(
    () => (studio ? parseMindmap(studio.mindmap_mermaid) : null),
    [studio],
  );

  return (
    <div>
      <div style={accountRow}>
        <span className="pill">{email}</span>
        <button className="btn btn-ghost" style={compactButton} onClick={logout}>로그아웃</button>
      </div>

      <form onSubmit={generate} className="glass query-form">
        <div className="query-grid">
          <label className="query-field">
            <span className="sr-only">주제</span>
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="예) 교환학생 선발, 공자아카데미 운영" />
          </label>
          <button className="query-submit btn btn-primary" disabled={busy}>
            {busy ? "생성 중…" : "생성"}
          </button>
        </div>
        <div style={secondaryGrid}>
          <label className="query-field">
            <span className="muted" style={{ fontSize: 12 }}>부서(선택)</span>
            <input className="input" value={dept} onChange={(e) => setDept(e.target.value)}
              placeholder="예) 국제교류팀" />
          </label>
        </div>
      </form>

      {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}

      {studio && (
        <>
          <MetricsStrip metrics={studio.metrics} />

          <div style={tabRow}>
            <TabButton id="summary" tab={tab} setTab={setTab} label="한눈에 보기" />
            <TabButton id="mindmap" tab={tab} setTab={setTab} label="마인드맵" />
            <TabButton id="slides" tab={tab} setTab={setTab} label="슬라이드" />
            <TabButton id="infographic" tab={tab} setTab={setTab} label="인포그래픽" />
          </div>

          <div className="glass" style={{ marginTop: 14 }}>
            {tab === "summary" && (
              <SummaryView summary={summary} citations={citations} busy={summaryBusy} />
            )}
            {tab === "mindmap" && mindmapTree && studio && (
              <MindmapView tree={mindmapTree} mermaid={studio.mindmap_mermaid} grouping={studio.mindmap_grouping} />
            )}
            {tab === "slides" && (
              <SlidesView markdown={studio.slides_marp} query={studio.metrics.query} />
            )}
            {tab === "infographic" && (
              <InfographicView svg={studio.infographic_svg} query={studio.metrics.query} />
            )}
          </div>
        </>
      )}
    </div>
  );
}

function TabButton({ id, tab, setTab, label }: { id: Tab; tab: Tab; setTab: (t: Tab) => void; label: string }) {
  return (
    <button
      className={`btn ${tab === id ? "btn-primary" : "btn-ghost"}`}
      style={{ padding: "8px 16px", fontSize: 13 }}
      onClick={() => setTab(id)}
    >
      {label}
    </button>
  );
}

function MetricsStrip({ metrics }: { metrics: Metrics }) {
  const period = metrics.period_start
    ? metrics.period_end && metrics.period_end !== metrics.period_start
      ? `${metrics.period_start} ~ ${metrics.period_end}`
      : metrics.period_start
    : "기간 미상";
  return (
    <div style={metricStrip}>
      <Metric value={metrics.document_count} label="문서" />
      <Metric value={metrics.work_item_count} label="업무" />
      <Metric value={metrics.category_count} label="분류" />
      <div style={{ marginLeft: "auto", alignSelf: "center" }}>
        <span className="muted" style={{ fontSize: 13 }}>{period}</span>
      </div>
    </div>
  );
}

function Metric({ value, label }: { value: number; label: string }) {
  return (
    <div style={metricCard}>
      <div style={{ fontSize: 28, fontWeight: 800 }}>{value}</div>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
    </div>
  );
}

function SummaryView({ summary, citations, busy }: { summary: string; citations: Citation[]; busy: boolean }) {
  if (!summary && busy) return <p className="muted">요약 생성 중…</p>;
  if (!summary) return <p className="muted">요약이 없습니다.</p>;
  return (
    <div>
      <div className="answer" style={{ whiteSpace: "pre-wrap" }}>{summary}{busy ? " ▍" : ""}</div>
      {citations.length > 0 && (
        <div className="sources">
          <h3>출처</h3>
          <ol>{citations.map((c) => <li key={c.n}>{c.label}</li>)}</ol>
        </div>
      )}
    </div>
  );
}

function MindmapView({ tree, mermaid, grouping }: { tree: MindmapTree; mermaid: string; grouping?: "semantic" | "rule" }) {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 0 }}>
        <h3 style={{ margin: 0 }}>🧠 {tree.root}</h3>
        {grouping && (
          <span className="pill" style={{ fontSize: 12 }}>
            {grouping === "semantic" ? "의미 그룹핑(AI)" : "규칙 그룹핑"}
          </span>
        )}
      </div>
      <MindmapNodes nodes={tree.nodes} depth={0} />
      <details style={{ marginTop: 16 }}>
        <summary style={detailsSummary}>Mermaid 원문 (mermaid.live에 붙여넣기)</summary>
        <CopyBlock text={mermaid} />
      </details>
    </div>
  );
}

// 같은 depth의 연속 노드를 그룹으로 묶어 중첩 <ul> 렌더.
function MindmapNodes({ nodes, depth }: { nodes: MindmapNode[]; depth: number }) {
  const items: { node: MindmapNode; children: MindmapNode[] }[] = [];
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].depth === depth) {
      const children: MindmapNode[] = [];
      let j = i + 1;
      while (j < nodes.length && nodes[j].depth > depth) {
        children.push(nodes[j]);
        j++;
      }
      items.push({ node: nodes[i], children });
      i = j - 1;
    }
  }
  if (items.length === 0) return null;
  return (
    <ul style={depth === 0 ? mindmapRootList : mindmapList}>
      {items.map((item, idx) => (
        <li key={idx} style={{ margin: "4px 0" }}>
          <span style={depth === 0 ? mindmapBranch : undefined}>{item.node.text}</span>
          {item.children.length > 0 && (
            <MindmapNodes nodes={item.children} depth={depth + 1} />
          )}
        </li>
      ))}
    </ul>
  );
}

function SlidesView({ markdown, query }: { markdown: string; query: string }) {
  return (
    <div>
      <div style={toolbarRow}>
        <span className="muted" style={{ fontSize: 13 }}>Marp 마크다운 — .md로 저장 후 Marp(VS Code/CLI)로 PDF·PPTX 변환</span>
        <button className="btn btn-primary" style={compactButton}
          onClick={() => download(`${slug(query)}-slides.md`, markdown, "text/markdown")}>
          .md 다운로드
        </button>
      </div>
      <CopyBlock text={markdown} />
    </div>
  );
}

function InfographicView({ svg, query }: { svg: string; query: string }) {
  return (
    <div>
      <div style={toolbarRow}>
        <span className="muted" style={{ fontSize: 13 }}>자립형 SVG — 웹/문서에 그대로 삽입 가능</span>
        <button className="btn btn-primary" style={compactButton}
          onClick={() => download(`${slug(query)}-infographic.svg`, svg, "image/svg+xml")}>
          .svg 다운로드
        </button>
      </div>
      <div style={svgWrap} dangerouslySetInnerHTML={{ __html: svg }} />
    </div>
  );
}

function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <button className="btn btn-ghost" style={{ ...compactButton, position: "absolute", top: 8, right: 8 }}
        onClick={() => {
          navigator.clipboard.writeText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}>
        {copied ? "복사됨" : "복사"}
      </button>
      <pre style={codeBox}>{text}</pre>
    </div>
  );
}

// ── 헬퍼 ─────────────────────────────────────────────────────────
type MindmapNode = { depth: number; text: string };
type MindmapTree = { root: string; nodes: MindmapNode[] };

function parseMindmap(mermaid: string): MindmapTree {
  const lines = mermaid.split("\n").filter((l) => l.trim().length > 0);
  let root = "KMU Wiki";
  const nodes: MindmapNode[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed === "mindmap") continue;
    const rootMatch = /^root\(\((.*)\)\)$/.exec(trimmed);
    if (rootMatch) {
      root = rootMatch[1];
      continue;
    }
    const indent = line.length - line.trimStart().length;
    // root는 2칸, 첫 분기는 4칸부터. depth = (indent - 4) / 2, 최소 0.
    const depth = Math.max(0, Math.round((indent - 4) / 2));
    nodes.push({ depth, text: trimmed });
  }
  return { root, nodes };
}

function download(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function slug(text: string): string {
  return (text || "kmu-wiki").replace(/\s+/g, "-").replace(/[^0-9A-Za-z가-힣_-]/g, "").slice(0, 40) || "kmu-wiki";
}

// ── 스타일 ───────────────────────────────────────────────────────
const loginBox: CSSProperties = {
  display: "grid", gap: 12, maxWidth: 360, margin: "40px auto", padding: 28,
};
const accountRow: CSSProperties = {
  display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12, marginBottom: 14,
};
const compactButton: CSSProperties = { padding: "6px 14px", fontSize: 13 };
const secondaryGrid: CSSProperties = { marginTop: 12, maxWidth: 280 };
const tabRow: CSSProperties = { display: "flex", gap: 8, marginTop: 18, flexWrap: "wrap" };
const metricStrip: CSSProperties = {
  display: "flex", gap: 12, marginTop: 18, flexWrap: "wrap",
};
const metricCard: CSSProperties = {
  minWidth: 92, padding: "12px 18px", borderRadius: 12,
  background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", textAlign: "center",
};
const toolbarRow: CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12,
  flexWrap: "wrap", marginBottom: 12,
};
const codeBox: CSSProperties = {
  background: "rgba(0,0,0,0.28)", borderRadius: 12, padding: 16, overflowX: "auto",
  fontSize: 12.5, lineHeight: 1.6, whiteSpace: "pre-wrap", wordBreak: "break-word",
};
const svgWrap: CSSProperties = {
  background: "#fff", borderRadius: 12, padding: 8, overflowX: "auto",
};
const mindmapRootList: CSSProperties = { listStyle: "none", paddingLeft: 0, margin: 0 };
const mindmapList: CSSProperties = { paddingLeft: 20, margin: 0 };
const mindmapBranch: CSSProperties = { fontWeight: 700 };
const detailsSummary: CSSProperties = { cursor: "pointer", fontSize: 13, marginBottom: 8 };
