"use client";

import { useMemo } from "react";

export type WorkflowNodeType = "start" | "step" | "decision" | "end";

export type WorkflowNode = {
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

export function WorkflowBoard({
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

  if (nodes.length === 0) {
    return <p className="muted">저장된 업무흐름도 단계가 없습니다.</p>;
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

function workflowNodeType(type: WorkflowNodeType): string {
  return {
    start: "START",
    step: "STEP",
    decision: "DECISION",
    end: "END",
  }[type];
}
