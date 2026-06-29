"use client";

import { useEffect, useMemo, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { getAccessToken, getUserEmail, signIn, signOut } from "@/lib/supabase";

type Classification = {
  document_id: string;
  task_category: string;
  document_type: string;
  year?: number | null;
  semester?: number | null;
  work_id?: string;
  work_title?: string;
  label: string;
};

type WorkDocument = {
  document_id: string;
  document_type: string;
  label: string;
  doc_no?: string | null;
  doc_date?: string | null;
  filename?: string | null;
  year?: number | null;
  semester?: number | null;
};

type WorkItem = {
  work_id: string;
  work_title: string;
  task_category: string;
  year?: number | null;
  years?: number[];
  semesters?: number[];
  terms?: string[];
  start_date?: string | null;
  end_date?: string | null;
  document_count: number;
  document_types: string[];
  documents: WorkDocument[];
};

type CalendarDraft = {
  status: string;
  date: string;
  title: string;
  source_document_id: string;
  source_label: string;
  source_document_ids?: string[];
  source_labels?: string[];
};

type ReportWorkflow = {
  source_format: string;
  source_title: string;
  steps: string[];
  templates: { name: string; best_for: string }[];
  markdown_preview: string;
};

type InsightsResponse = {
  work_items: WorkItem[];
  classifications: Classification[];
  workflow_mermaid: string;
  calendar_drafts: CalendarDraft[];
  report_draft: string;
  report_workflow: ReportWorkflow;
};

type RecurringWork = {
  template_title: string;
  years: number[];
  document_ids: string[];
  task_category: string;
};

type UpdateReport = {
  summary: string;
  new_documents: string[];
  classifications: Classification[];
  recurring_work: RecurringWork[];
};

type DocumentDraft = {
  status: string;
  title: string;
  export_format?: string;
  hwpx_filename?: string;
  docx_filename?: string;
  approval_form_plan?: string[];
  body: string;
  source_document_id: string;
  source_label: string;
};

type HermesResponse = {
  update_report: UpdateReport;
  recurring_work: RecurringWork[];
  drafts: DocumentDraft[];
};

type CombinedResult = {
  query: string;
  targetYear: number;
  insights: InsightsResponse;
  hermes: HermesResponse;
};

type TimelineItem = {
  when: string;
  title: string;
  detail: string;
};

type WorkflowNodeType = "start" | "step" | "decision" | "end";

type WorkflowNode = {
  id: string;
  type: WorkflowNodeType;
  label: string;
  description: string;
  period: string;
  processingDays: string;
  procedures: string[];
  requiredDocs: string[];
  outputs: string[];
  collaborators: string[];
  notes: string[];
};

type WorkflowColumn = {
  id: string;
  top: WorkflowNode[];
  bottom: WorkflowNode | null;
};

type WorkflowStageDocument = WorkDocument & {
  workTitle: string;
  taskCategory: string;
  term: string;
};

type WorkflowStage = {
  key: string;
  label: string;
  order: number;
  workTitles: string[];
  taskCategories: string[];
  documentTypes: string[];
  documents: WorkflowStageDocument[];
  terms: string[];
  startDate?: string | null;
  endDate?: string | null;
};

export default function InsightsPage() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getUserEmail().then((value) => {
      setEmail(value);
      setReady(true);
    });
  }, []);

  return (
    <AppShell
      active="insights"
      eyebrow="업무 활용"
      title={<>문서 묶음에서 <span className="gradient-text">업무 흐름과 초안</span> 만들기</>}
      lede="권한 범위 안의 문서를 기반으로 분류, 일정, 보고서, 반복업무 초안을 생성합니다."
    >
      {!ready ? <p className="muted">로딩...</p>
        : email ? <Workspace email={email} onLogout={() => setEmail(null)} />
        : <Login onLogin={setEmail} />}
    </AppShell>
  );
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
    <form onSubmit={submit} className="glass" style={{ display: "grid", gap: 12, maxWidth: 380 }}>
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

function Workspace({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [query, setQuery] = useState("파견교환학생");
  const [targetYear, setTargetYear] = useState(String(new Date().getFullYear() + 1));
  const [result, setResult] = useState<CombinedResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function logout() {
    await signOut();
    onLogout();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || busy) return;

    setBusy(true);
    setErr("");
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("로그인 세션이 없습니다.");

      const parsedYear = Number(targetYear);
      const normalizedYear = Number.isInteger(parsedYear) && parsedYear > 2000 ? parsedYear : new Date().getFullYear() + 1;
      const body = { query: trimmed, k: 12, target_year: normalizedYear };
      const [insights, hermes] = await Promise.all([
        postJson<InsightsResponse>("/api/insights", token, body),
        postJson<HermesResponse>("/api/hermes", token, body),
      ]);
      setResult({ query: trimmed, targetYear: normalizedYear, insights, hermes });
    } catch (error: unknown) {
      setErr(error instanceof Error ? error.message : "업무 활용 생성 실패");
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div style={accountRow}>
        <span className="pill">{email}</span>
        <button className="btn btn-ghost" style={compactButton} onClick={logout}>로그아웃</button>
      </div>

      <form onSubmit={submit} className="glass query-form">
        <div className="query-grid">
          <label className="query-field">
            업무
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="예) 2026 파견교환학생" />
          </label>
          <label className="query-field">
            대상 연도
            <input className="input" value={targetYear} onChange={(e) => setTargetYear(e.target.value)}
              inputMode="numeric" placeholder="2027" />
          </label>
          <button className="query-submit btn btn-primary" disabled={busy}>
            {busy ? "생성 중..." : "생성"}
          </button>
        </div>
      </form>

      {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}
      {result && <ResultView result={result} />}
    </section>
  );
}

function ResultView({ result }: { result: CombinedResult }) {
  const timeline = useMemo(() => parseTimeline(result.insights.workflow_mermaid), [result.insights.workflow_mermaid]);
  const classifications = result.insights.classifications ?? [];
  const workItems = result.insights.work_items ?? fallbackWorkItems(classifications);
  const workflowNodes = useMemo(() => buildWorkflowNodes(workItems), [workItems]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const calendarDrafts = result.insights.calendar_drafts ?? [];
  const recurring = result.hermes.recurring_work ?? [];
  const drafts = result.hermes.drafts ?? [];
  const newDocuments = result.hermes.update_report?.new_documents ?? [];
  const workflow = result.insights.report_workflow;

  return (
    <div style={results}>
      <div style={summaryStrip}>
        <Metric label="업무" value={workItems.length} />
        <Metric label="일정 초안" value={calendarDrafts.length} />
        <Metric label="신규 문서" value={newDocuments.length} />
        <Metric label={`${result.targetYear} HWPX`} value={drafts.length} />
      </div>

      <section className="glass" style={widePanel}>
        <PanelHeader title="업데이트 보고" meta={result.query} />
        <p style={{ margin: 0, color: "var(--text)" }}>{result.hermes.update_report?.summary ?? "요약 없음"}</p>
        {newDocuments.length > 0 && (
          <div style={chipRow}>
            {newDocuments.slice(0, 8).map((id) => <span key={id} style={chip}>{shortId(id)}</span>)}
          </div>
        )}
      </section>

      <section className="glass" style={widePanel}>
        <PanelHeader title="업무흐름도" meta={`${workflowNodes.length || timeline.length}단계`} />
        {workflowNodes.length > 0
          ? <WorkflowBoard nodes={workflowNodes} selectedId={selectedWorkflowId} onSelect={setSelectedWorkflowId} />
          : timeline.length > 0 ? <Timeline items={timeline} /> : <pre style={codeBox}>{result.insights.workflow_mermaid}</pre>}
        <details style={{ marginTop: 14 }}>
          <summary style={detailsSummary}>Mermaid 원문</summary>
          <pre style={codeBox}>{result.insights.workflow_mermaid}</pre>
        </details>
      </section>

      <div style={twoColumn}>
        <section className="glass" style={panel}>
          <PanelHeader title="업무 분류" meta={`${workItems.length}개 업무 · ${classifications.length}개 문서`} />
          <div style={tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>업무</th>
                  <th>학년도/학기</th>
                  <th>분류</th>
                  <th>유형</th>
                  <th>기간</th>
                  <th>문서 수</th>
                </tr>
              </thead>
              <tbody>
                {workItems.map((row) => (
                  <tr key={row.work_id}>
                    <td>{row.work_title}</td>
                    <td>{termSummary(row)}</td>
                    <td>{row.task_category}</td>
                    <td>{joinTypes(row.document_types)}</td>
                    <td>{dateRange(row.start_date, row.end_date)}</td>
                    <td>{row.document_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="glass" style={panel}>
          <PanelHeader title="연간일정 초안" meta={`${calendarDrafts.length}건`} />
          <div style={listStack}>
            {calendarDrafts.length === 0 && <Empty>일정 후보가 없습니다.</Empty>}
            {calendarDrafts.map((draft) => (
              <article key={`${draft.date}-${draft.title}`} style={itemBox}>
                <div style={itemTop}>
                  <strong>{draft.date}</strong>
                  <span className="pill">{draft.status}</span>
                </div>
                <p style={itemTitle}>{draft.title}</p>
                <p style={itemMeta}>{sourceSummary(draft)}</p>
              </article>
            ))}
          </div>
        </section>
      </div>

      <div style={twoColumn}>
        <section className="glass" style={panel}>
          <PanelHeader title="반복업무" meta={`${recurring.length}건`} />
          <div style={listStack}>
            {recurring.length === 0 && <Empty>반복 패턴이 없습니다.</Empty>}
            {recurring.map((pattern) => (
              <article key={`${pattern.template_title}-${pattern.years.join("-")}`} style={itemBox}>
                <div style={itemTop}>
                  <strong>{pattern.template_title}</strong>
                  <span style={chip}>{pattern.task_category}</span>
                </div>
                <p style={itemMeta}>{pattern.years.join(", ")} · {pattern.document_ids.length}개 문서</p>
              </article>
            ))}
          </div>
        </section>

        <section className="glass" style={panel}>
          <PanelHeader title={`${result.targetYear} 문서 초안`} meta={`${drafts.length}개 HWPX`} />
          <div style={listStack}>
            {drafts.length === 0 && <Empty>차년도 초안 후보가 없습니다.</Empty>}
            {drafts.map((draft) => (
              <article key={`${draft.source_document_id}-${draft.title}`} style={itemBox}>
                <div style={itemTop}>
                  <strong>{draft.hwpx_filename ?? draft.title}</strong>
                  <span className="pill">{draft.export_format ?? draft.status}</span>
                </div>
                <p style={itemMeta}>{draft.source_label}</p>
                <button className="btn btn-ghost" style={downloadButton} onClick={() => downloadHwpx(draft)}>
                  HWPX 다운로드
                </button>
                {draft.approval_form_plan && (
                  <ol style={stepList}>
                    {draft.approval_form_plan.map((step) => <li key={step}>{step}</li>)}
                  </ol>
                )}
                <pre style={draftBody}>{clip(draft.body, 900)}</pre>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="glass" style={widePanel}>
        <PanelHeader title="보고서 초안" meta="Markdown" />
        <pre style={reportBox}>{result.insights.report_draft}</pre>
      </section>

      {workflow && (
        <section className="glass" style={widePanel}>
          <PanelHeader title="보고서 작성 플로우" meta={workflow.source_format.toUpperCase()} />
          <div style={twoColumn}>
            <div>
              <h3>단계</h3>
              <ol style={stepList}>
                {workflow.steps.map((step) => <li key={step}>{step}</li>)}
              </ol>
            </div>
            <div>
              <h3>양식</h3>
              <div style={listStack}>
                {workflow.templates.map((template) => (
                  <article key={template.name} style={templateRow}>
                    <strong>{template.name}</strong>
                    <span style={itemMeta}>{template.best_for}</span>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

function WorkflowBoard({
  nodes,
  selectedId,
  onSelect,
}: {
  nodes: WorkflowNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const selected = nodes.find((node) => node.id === selectedId) ?? nodes[0];
  const columns = useMemo(() => buildWorkflowColumns(nodes), [nodes]);

  function renderCard(node: WorkflowNode, displayIndex: number) {
    const selectedClass = selected.id === node.id ? " workflow-board-card--selected" : "";

    return (
      <button
        type="button"
        className={`workflow-board-card workflow-board-card--${node.type}${selectedClass}`}
        onClick={() => onSelect(node.id)}
        aria-pressed={selected.id === node.id}
      >
        <div className="workflow-board-card-top">
          <span className={`workflow-board-index workflow-board-index--${node.type}`}>{displayIndex}</span>
          <span className="workflow-board-type">{workflowNodeType(node.type)}</span>
          {node.processingDays && <span className="workflow-board-days">{node.processingDays}</span>}
        </div>
        <strong>{node.label}</strong>
        <span>{node.period}</span>
        <div className="workflow-board-pills">
          {node.procedures.length > 0 && <span>절차 {node.procedures.length}</span>}
          {node.requiredDocs.length > 0 && <span>서류 {node.requiredDocs.length}</span>}
          {node.outputs.length > 0 && <span>산출 {node.outputs.length}</span>}
          {node.collaborators.length > 0 && <span>협조 {node.collaborators.length}</span>}
        </div>
      </button>
    );
  }

  return (
    <div className="workflow-board">
      <div className="workflow-board-lane" aria-label="업무흐름도 단계">
        {columns.map((column, index) => (
          <div className="workflow-board-step" key={column.id}>
            <div className="workflow-board-column">
              {column.top.length > 0 && (
                <div className="workflow-board-column-top">
                  {column.top.map((node) => renderCard(node, nodes.findIndex((candidate) => candidate.id === node.id) + 1))}
                  <span className="workflow-board-connector" aria-hidden="true" />
                </div>
              )}
              {column.bottom
                ? renderCard(column.bottom, nodes.findIndex((candidate) => candidate.id === column.bottom?.id) + 1)
                : <div className="workflow-board-empty" />}
            </div>
            {index < columns.length - 1 && <WorkflowArrow />}
          </div>
        ))}
      </div>

      {selected && <WorkflowDetail node={selected} />}
    </div>
  );
}

function WorkflowArrow() {
  return (
    <span className="workflow-board-arrow" aria-hidden="true">
      <svg width="22" height="12" viewBox="0 0 22 12" fill="none">
        <path d="M1 6h18M15 2l4 4-4 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

function WorkflowDetail({ node }: { node: WorkflowNode }) {
  return (
    <article className={`workflow-board-detail workflow-board-detail--${node.type}`}>
      <div className="workflow-board-detail-head">
        <span className="workflow-board-type">{workflowNodeType(node.type)}</span>
        <h3>{node.label}</h3>
        {node.processingDays && <span className="workflow-board-days">{node.processingDays}</span>}
      </div>
      <p>{node.description}</p>
      <div className="workflow-board-detail-grid">
        <WorkflowDetailList title="업무처리 절차" items={node.procedures} ordered />
        <WorkflowDetailList title="필요서류" items={node.requiredDocs} />
        <WorkflowDetailList title="산출물" items={node.outputs} />
        <WorkflowDetailList title="협조부서" items={node.collaborators} />
      </div>
      {node.notes.length > 0 && (
        <div className="workflow-board-notes">
          {node.notes.map((note) => <span key={note}>{note}</span>)}
        </div>
      )}
    </article>
  );
}

function WorkflowDetailList({ title, items, ordered = false }: { title: string; items: string[]; ordered?: boolean }) {
  if (items.length === 0) return null;
  const List = ordered ? "ol" : "div";

  return (
    <section className="workflow-board-detail-list">
      <h4>{title}</h4>
      <List>
        {items.map((item) => ordered ? <li key={item}>{item}</li> : <span key={item}>{item}</span>)}
      </List>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div style={metricBox}>
      <span style={metricLabel}>{label}</span>
      <strong style={metricValue}>{value.toLocaleString("ko-KR")}</strong>
    </div>
  );
}

function PanelHeader({ title, meta }: { title: string; meta?: string }) {
  return (
    <div style={panelHeader}>
      <h2 style={{ margin: 0 }}>{title}</h2>
      {meta && <span style={panelMeta}>{meta}</span>}
    </div>
  );
}

function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol style={timelineList}>
      {items.map((item, index) => (
        <li key={`${item.when}-${item.title}-${index}`} style={timelineItem}>
          <span style={timelineDot} />
          <div>
            <div style={itemTop}>
              <strong>{item.when}</strong>
              <span style={chip}>{index + 1}</span>
            </div>
            <p style={itemTitle}>{item.title}</p>
            <p style={itemMeta}>{item.detail}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p style={{ margin: 0, color: "var(--muted)", fontSize: 14 }}>{children}</p>;
}

async function postJson<T>(url: string, token: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${url} ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function downloadHwpx(draft: DocumentDraft): Promise<void> {
  const token = await getAccessToken();
  if (!token) {
    window.alert("로그인 세션이 없습니다.");
    return;
  }
  const filename = hwpxDownloadName(draft);
  const res = await fetch("/api/hermes/hwpx", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify({
      title: draft.title,
      hwpx_filename: filename,
      body: draft.body,
      source_label: draft.source_label,
      approval_form_plan: draft.approval_form_plan,
    }),
  });
  if (!res.ok) {
    window.alert(`HWPX 생성 실패 (${res.status})`);
    return;
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
}

function hwpxDownloadName(draft: DocumentDraft): string {
  const base = draft.hwpx_filename ?? draft.docx_filename ?? draft.title ?? "draft";
  return `${base.replace(/\.[^.]+$/, "").replace(/[\\/:*?"<>|]+/g, "").trim() || "draft"}.hwpx`;
}

function parseTimeline(workflow_mermaid: string): TimelineItem[] {
  return workflow_mermaid
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !["timeline"].includes(line) && !line.startsWith("title "))
    .map((line) => {
      const [when = "", title = "", ...rest] = line.split(" : ");
      return { when, title, detail: rest.join(" : ") };
    })
    .filter((item) => item.when && item.title);
}

function clip(text: string, limit: number): string {
  const normalized = text.trim();
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

function shortId(id: string): string {
  return id.length > 10 ? id.slice(0, 10) : id;
}

function fallbackWorkItems(classifications: Classification[]): WorkItem[] {
  const grouped = new Map<string, WorkItem>();
  for (const row of classifications) {
    const key = row.work_id ?? row.work_title ?? row.task_category;
    const term = termLabel(row.year, row.semester);
    const item = grouped.get(key) ?? {
      work_id: key,
      work_title: row.work_title ?? row.task_category,
      task_category: row.task_category,
      year: row.year,
      years: [],
      semesters: [],
      terms: [],
      start_date: null,
      end_date: null,
      document_count: 0,
      document_types: [],
      documents: [],
    };
    item.document_count += 1;
    if (row.year && !item.years?.includes(row.year)) item.years?.push(row.year);
    if (row.semester && !item.semesters?.includes(row.semester)) item.semesters?.push(row.semester);
    if (term && !item.terms?.includes(term)) item.terms?.push(term);
    if (!item.document_types.includes(row.document_type)) item.document_types.push(row.document_type);
    item.documents.push({
      document_id: row.document_id,
      document_type: row.document_type,
      label: row.label,
      year: row.year,
      semester: row.semester,
    });
    grouped.set(key, item);
  }
  return Array.from(grouped.values()).map((item) => ({
    ...item,
    years: [...(item.years ?? [])].sort(),
    semesters: [...(item.semesters ?? [])].sort(),
    terms: [...(item.terms ?? [])].sort(),
  }));
}

function joinTypes(types: string[]): string {
  return types.length ? types.join(", ") : "-";
}

function dateRange(start?: string | null, end?: string | null): string {
  if (!start && !end) return "-";
  if (!end || start === end) return start ?? end ?? "-";
  return `${start} ~ ${end}`;
}

function sourceSummary(draft: CalendarDraft): string {
  const labels = draft.source_labels ?? [draft.source_label].filter(Boolean);
  const count = draft.source_document_ids?.length ?? labels.length;
  const label = labels[0] ?? draft.source_label;
  return count > 1 ? `${label} 외 ${count - 1}개 원문 병합` : label;
}

function buildWorkflowNodes(workItems: WorkItem[]): WorkflowNode[] {
  return buildWorkflowStageNodes(workItems);
}

function buildWorkflowStageNodes(workItems: WorkItem[]): WorkflowNode[] {
  const groups = new Map<string, WorkflowStage>();

  for (const item of workItems) {
    for (const doc of item.documents ?? []) {
      const stage = workflowStageForDocument(doc);
      const key = stageWorkflowKey(stage.label);
      const term = termLabel(doc.year ?? item.year, doc.semester) || termSummary(item);
      const group = groups.get(key) ?? {
        key,
        label: stage.label,
        order: stage.order,
        workTitles: [],
        taskCategories: [],
        documentTypes: [],
        documents: [],
        terms: [],
        startDate: doc.doc_date,
        endDate: doc.doc_date,
      };

      if (!group.workTitles.includes(item.work_title)) group.workTitles.push(item.work_title);
      if (!group.taskCategories.includes(item.task_category)) group.taskCategories.push(item.task_category);
      if (!group.documentTypes.includes(doc.document_type)) group.documentTypes.push(doc.document_type);
      if (term && !group.terms.includes(term)) group.terms.push(term);
      if (doc.doc_date && (!group.startDate || doc.doc_date < group.startDate)) group.startDate = doc.doc_date;
      if (doc.doc_date && (!group.endDate || doc.doc_date > group.endDate)) group.endDate = doc.doc_date;
      group.documents.push({ ...doc, workTitle: item.work_title, taskCategory: item.task_category, term });
      groups.set(key, group);
    }
  }

  const stages = Array.from(groups.values()).sort((a, b) => {
    const dateCompare = (a.startDate ?? "9999-12-31").localeCompare(b.startDate ?? "9999-12-31");
    return a.order - b.order || dateCompare || a.label.localeCompare(b.label, "ko");
  });

  if (stages.length === 0) return buildWorkItemFallbackNodes(workItems);

  return stages.map((stage, index) => {
    const docs = stage.documents.sort((a, b) => {
      return (a.doc_date ?? "9999-12-31").localeCompare(b.doc_date ?? "9999-12-31")
        || (a.doc_no ?? "").localeCompare(b.doc_no ?? "", "ko")
        || (a.filename ?? a.label).localeCompare(b.filename ?? b.label, "ko");
    });
    const filenames = uniqueStrings(docs.map((doc) => doc.filename ?? doc.label)).slice(0, 6);
    const collaborators = uniqueStrings(docs.map((doc) => departmentFromLabel(doc.label))).slice(0, 5);

    return {
      id: `stage-${stage.key}`,
      type: workflowTypeFor(stage, index, stages.length),
      label: stage.label,
      description: `${stage.workTitles.join(", ")} 업무의 ${stage.label} 단계입니다.`,
      period: dateRange(stage.startDate, stage.endDate),
      processingDays: workflowDuration(stage.startDate, stage.endDate),
      procedures: docs.slice(0, 6).map((doc, docIndex) => {
        const date = doc.doc_date ?? "날짜 미상";
        const term = doc.term && doc.term !== "-" ? `${doc.term} · ` : "";
        const title = doc.filename ?? doc.label ?? `문서 ${docIndex + 1}`;
        return `${date} · ${term}${doc.document_type} · ${title}`;
      }),
      requiredDocs: uniqueStrings(stage.documentTypes).slice(0, 6),
      outputs: filenames,
      collaborators,
      notes: [
        ...uniqueStrings(stage.terms).slice(0, 6),
        docs.length > 1 ? `원문 ${docs.length}개 병합` : "원문 1개",
      ],
    };
  });
}

function buildWorkItemFallbackNodes(workItems: WorkItem[]): WorkflowNode[] {
  const ordered = [...workItems].sort((a, b) => {
    return (a.start_date ?? "9999-12-31").localeCompare(b.start_date ?? "9999-12-31")
      || a.work_title.localeCompare(b.work_title, "ko");
  });

  return ordered.map((item, index) => ({
    id: item.work_id || `${item.work_title}-${index}`,
    type: workflowTypeFor({
      label: item.work_title,
      documentTypes: item.document_types,
      documents: item.documents.map((doc) => ({ ...doc, workTitle: item.work_title, taskCategory: item.task_category, term: termLabel(doc.year ?? item.year, doc.semester) || "" })),
    }, index, ordered.length),
    label: item.work_title || item.task_category || `업무 ${index + 1}`,
    description: `${item.task_category || "미분류"} 업무로 묶인 ${item.document_count}개 문서입니다.`,
    period: dateRange(item.start_date, item.end_date),
    processingDays: workflowDuration(item.start_date, item.end_date),
    procedures: [],
    requiredDocs: item.document_types.slice(0, 6),
    outputs: [],
    collaborators: [],
    notes: [termSummary(item), item.document_count > 1 ? `원문 ${item.document_count}개 병합` : "원문 1개"].filter(Boolean),
  }));
}

function workflowStageForDocument(doc: WorkDocument): { label: string; order: number } {
  const text = `${doc.document_type} ${doc.filename ?? ""} ${doc.label}`;
  if (text.includes("지원 기준") || text.includes("변경")) return { label: "지원 기준 변경", order: 15 };
  if (text.includes("시험")) return { label: "선발 시험", order: 20 };
  if (text.includes("서류전형")) return { label: "서류전형", order: 30 };
  if (text.includes("면접")) return { label: "면접전형", order: 40 };
  if (text.includes("결과") || text.includes("합격자") || text.includes("후속") || text.includes("진행 계획")) {
    return { label: "결과 보고", order: 50 };
  }
  if (text.includes("추가 모집") || text.includes("추가모집") || text.includes("모집")) {
    return { label: "모집 공고", order: 10 };
  }
  if (text.includes("공고문") || text.includes("홈페이지") || text.includes("안내문")) {
    return { label: "홈페이지 공고문", order: 60 };
  }
  if (doc.document_type && doc.document_type !== "문서") return { label: doc.document_type, order: 70 };
  return { label: "기타 문서", order: 90 };
}

function stageWorkflowKey(label: string): string {
  return label.replace(/[^0-9A-Za-z가-힣]+/g, "").toLowerCase();
}

function termSummary(item: WorkItem): string {
  if (item.terms?.length) return item.terms.join(", ");
  const years = item.years?.length ? item.years : item.year ? [item.year] : [];
  const semesters = item.semesters ?? [];
  if (years.length && semesters.length) {
    return years.flatMap((year) => semesters.map((semester) => `${year}학년도 ${semester}학기`)).join(", ");
  }
  if (years.length) return years.map((year) => `${year}학년도`).join(", ");
  if (semesters.length) return semesters.map((semester) => `${semester}학기`).join(", ");
  return "-";
}

function termLabel(year?: number | null, semester?: number | null): string {
  if (year && semester) return `${year}학년도 ${semester}학기`;
  if (year) return `${year}학년도`;
  if (semester) return `${semester}학기`;
  return "";
}

function buildWorkflowColumns(nodes: WorkflowNode[]): WorkflowColumn[] {
  const columns: WorkflowColumn[] = [];
  let pendingDecisions: WorkflowNode[] = [];

  for (const node of nodes) {
    if (node.type === "decision") {
      pendingDecisions.push(node);
      continue;
    }
    columns.push({ id: node.id, top: pendingDecisions, bottom: node });
    pendingDecisions = [];
  }

  if (pendingDecisions.length > 0) {
    columns.push({ id: pendingDecisions[0].id, top: pendingDecisions, bottom: null });
  }

  return columns;
}

function workflowTypeFor(stage: Pick<WorkflowStage, "label" | "documentTypes" | "documents">, index: number, total: number): WorkflowNodeType {
  if (total === 1) return "step";
  if (index === 0) return "start";
  if (index === total - 1) return "end";

  const text = `${stage.label} ${stage.documentTypes.join(" ")}`;
  const decisionKeywords = ["심사", "평가", "검토", "승인", "변경"];
  return decisionKeywords.some((keyword) => text.includes(keyword)) ? "decision" : "step";
}

function workflowNodeType(type: WorkflowNodeType): string {
  return {
    start: "START",
    step: "STEP",
    decision: "DECISION",
    end: "END",
  }[type];
}

function workflowDuration(start?: string | null, end?: string | null): string {
  if (!start && !end) return "";
  if (!start || !end || start === end) return "당일";

  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  const diffMs = endDate.getTime() - startDate.getTime();
  const days = Math.round(diffMs / 86_400_000) + 1;
  return Number.isFinite(days) && days > 0 && days < 366 ? `${days}일` : "";
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.map((value) => value?.trim()).filter(Boolean) as string[]));
}

function departmentFromLabel(label?: string | null): string {
  const first = label?.split("·")[0]?.trim() ?? "";
  return first && !first.includes(".") ? first : "";
}

const accountRow: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  alignItems: "center",
  gap: 10,
  marginBottom: 14,
};

const compactButton: CSSProperties = {
  padding: "6px 14px",
  fontSize: 13,
};

const downloadButton: CSSProperties = {
  marginTop: 10,
  padding: "6px 12px",
  fontSize: 13,
};

const results: CSSProperties = {
  display: "grid",
  gap: 18,
  marginTop: 18,
};

const summaryStrip: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 12,
};

const metricBox: CSSProperties = {
  border: "1px solid var(--hair)",
  borderRadius: 18,
  background: "rgba(255,255,255,0.055)",
  padding: 16,
};

const metricLabel: CSSProperties = {
  display: "block",
  color: "var(--muted)",
  fontSize: 12,
  marginBottom: 4,
};

const metricValue: CSSProperties = {
  color: "var(--text)",
  fontSize: 28,
  lineHeight: 1,
};

const widePanel: CSSProperties = {
  padding: 22,
};

const panel: CSSProperties = {
  padding: 22,
  minWidth: 0,
};

const panelHeader: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 12,
  marginBottom: 14,
};

const panelMeta: CSSProperties = {
  color: "var(--muted)",
  fontSize: 12,
};

const chipRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
  marginTop: 12,
};

const chip: CSSProperties = {
  display: "inline-block",
  padding: "3px 9px",
  borderRadius: 999,
  background: "rgba(122,162,255,0.12)",
  border: "1px solid rgba(122,162,255,0.22)",
  color: "var(--blue-bright)",
  fontSize: 12,
  whiteSpace: "nowrap",
};

const twoColumn: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 18,
};

const tableWrap: CSSProperties = {
  overflowX: "auto",
};

const listStack: CSSProperties = {
  display: "grid",
  gap: 10,
};

const stepList: CSSProperties = {
  margin: "8px 0 0",
  paddingLeft: 22,
  color: "var(--muted)",
  fontSize: 14,
  lineHeight: 1.7,
};

const itemBox: CSSProperties = {
  border: "1px solid var(--hair-soft)",
  borderRadius: 14,
  background: "rgba(0,0,0,0.14)",
  padding: 14,
};

const itemTop: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 10,
};

const itemTitle: CSSProperties = {
  margin: "6px 0 0",
  color: "var(--text)",
  fontWeight: 600,
};

const itemMeta: CSSProperties = {
  margin: "5px 0 0",
  color: "var(--muted)",
  fontSize: 13,
  lineHeight: 1.5,
};

const timelineList: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 10,
};

const timelineItem: CSSProperties = {
  position: "relative",
  display: "grid",
  gridTemplateColumns: "18px 1fr",
  gap: 12,
  padding: "12px 0",
  borderTop: "1px solid var(--hair-soft)",
};

const timelineDot: CSSProperties = {
  width: 10,
  height: 10,
  borderRadius: 999,
  background: "var(--blue-bright)",
  marginTop: 8,
  boxShadow: "0 0 0 5px rgba(122,162,255,0.12)",
};

const detailsSummary: CSSProperties = {
  cursor: "pointer",
  color: "var(--muted)",
  fontSize: 13,
};

const codeBox: CSSProperties = {
  whiteSpace: "pre-wrap",
  overflowX: "auto",
  margin: 0,
  background: "rgba(0,0,0,0.25)",
  border: "1px solid var(--hair-soft)",
  borderRadius: 14,
  padding: 14,
  color: "var(--muted)",
  lineHeight: 1.5,
};

const reportBox: CSSProperties = {
  ...codeBox,
  color: "var(--text)",
  maxHeight: 460,
};

const draftBody: CSSProperties = {
  ...codeBox,
  marginTop: 10,
  fontSize: 13,
  maxHeight: 220,
};

const templateRow: CSSProperties = {
  display: "grid",
  gap: 4,
  borderTop: "1px solid var(--hair-soft)",
  paddingTop: 10,
};
