from __future__ import annotations

import html
from typing import Literal

from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


class SearchIntake(BaseModel):
    target_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    entity_type: Literal["person", "company", "other"] = "person"
    purpose: str = Field(min_length=1)
    known_info: list[str] = Field(default_factory=list)
    search_scope: list[str] = Field(default_factory=list)
    constraints: str | None = None


class GraphPayload(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class SearchResponse(BaseModel):
    intake: SearchIntake
    node_count: int
    edge_count: int
    graph: GraphPayload
    partial_results: bool = False
    warnings: list[str] = Field(default_factory=list)
    rate_limit_hits: int = 0


def build_research_seed(intake: SearchIntake) -> str:
    lines = [
        f"Target: {intake.target_name}",
        f"Entity type: {intake.entity_type}",
        f"Purpose: {intake.purpose}",
    ]
    if intake.aliases:
        lines.append(f"Aliases: {', '.join(intake.aliases)}")
    if intake.known_info:
        lines.append(f"Known info: {'; '.join(intake.known_info)}")
    if intake.search_scope:
        lines.append(f"Search scope: {', '.join(intake.search_scope)}")
    if intake.constraints:
        lines.append(f"Constraints: {intake.constraints}")
    return "\n".join(lines)


def execute_research(intake: SearchIntake) -> dict:
    from osint_agents import run_research

    graph = run_research(
        build_research_seed(intake),
        max_depth=2,
        max_tasks=8,
        max_tasks_per_entity=3,
    )
    metadata = getattr(graph, "metadata", {}) or {}
    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "graph": {"nodes": graph.nodes, "edges": graph.edges},
        "partial_results": bool(metadata.get("partial_results", False)),
        "warnings": list(metadata.get("warnings", [])),
        "rate_limit_hits": int(metadata.get("rate_limit_hits", 0)),
    }


app = FastAPI(
    title="Octopus Intake API",
    description="Structured intake + OSINT research trigger API for the Octopus prototype.",
    version="0.1.0",
)
app.state.execute_research = execute_research
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _split_lines(raw_value: str) -> list[str]:
    return [line.strip() for line in raw_value.splitlines() if line.strip()]


def _build_search_response(intake: SearchIntake) -> SearchResponse:
    result = app.state.execute_research(intake)
    return SearchResponse(
        intake=intake,
        node_count=result["node_count"],
        edge_count=result["edge_count"],
        graph=GraphPayload(**result["graph"]),
        partial_results=result.get("partial_results", False),
        warnings=result.get("warnings", []),
        rate_limit_hits=result.get("rate_limit_hits", 0),
    )


def render_form(result: dict | None = None, error: str | None = None) -> str:
    summary_html = ""
    if error:
        summary_html = f"""
        <section class="card error">
          <h2>Hata</h2>
          <p>{html.escape(error)}</p>
        </section>
        """
    elif result:
        intake = result["intake"]
        summary_html = f"""
        <section class="card">
          <h2>Arama Başlatıldı</h2>
          <p><b>Hedef:</b> {html.escape(intake["target_name"])}</p>
          <p><b>Amaç:</b> {html.escape(intake["purpose"])}</p>
          <p><b>Düğüm:</b> {result["node_count"]} | <b>İlişki:</b> {result["edge_count"]}</p>
          <details>
            <summary>Gönderilen Structured Input</summary>
            <pre>{html.escape(str(intake))}</pre>
          </details>
        </section>
        """

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Octopus Intake</title>
  <style>
    :root {{
      --bg: #0c1720;
      --panel: #132531;
      --panel-2: #0f1f29;
      --text: #e8f4f2;
      --muted: #94aeb5;
      --accent: #4defd6;
      --warn: #f2b84b;
      --error: #ff8f8f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, sans-serif;
      background: radial-gradient(circle at top, #173042 0%, var(--bg) 55%);
      color: var(--text);
      min-height: 100vh;
    }}
    main {{
      max-width: 880px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}
    h1 {{ margin-bottom: 8px; }}
    p.lead {{
      color: var(--muted);
      max-width: 680px;
      line-height: 1.55;
      margin-bottom: 24px;
    }}
    form, .card {{
      background: rgba(19, 37, 49, 0.94);
      border: 1px solid #24404f;
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 12px 36px rgba(0, 0, 0, 0.24);
    }}
    .card {{ margin-top: 18px; }}
    .card.error {{ border-color: #6a3232; color: var(--error); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }}
    label {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-weight: 600;
      margin-bottom: 16px;
    }}
    input, select, textarea {{
      width: 100%;
      border: 1px solid #2a4858;
      border-radius: 10px;
      background: var(--panel-2);
      color: var(--text);
      padding: 12px 14px;
      font: inherit;
    }}
    textarea {{ min-height: 110px; resize: vertical; }}
    .help {{ color: var(--muted); font-size: 0.9rem; font-weight: 400; }}
    .scopes {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      margin: 8px 0 18px;
    }}
    .scopes label {{
      flex-direction: row;
      align-items: center;
      font-weight: 500;
      margin: 0;
    }}
    button {{
      border: none;
      border-radius: 12px;
      background: var(--accent);
      color: #052923;
      padding: 12px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <main>
    <h1>Octopus Structured Intake</h1>
    <p class="lead">Kullanıcı önce hedefi, amacı ve bilinen bilgileri girer. Sistem bu structured input ile araştırma prompt'unu kurar ve ondan sonra OSINT akışını başlatır.</p>
    <form method="post" action="/search">
      <div class="grid">
        <label>
          Target Name
          <input name="target_name" placeholder="Örn. Elon Musk" required>
        </label>
        <label>
          Entity Type
          <select name="entity_type">
            <option value="person">person</option>
            <option value="company">company</option>
            <option value="other">other</option>
          </select>
        </label>
      </div>
      <label>
        Purpose
        <input name="purpose" placeholder="Örn. aday değerlendirmesi / genel şirket araştırması" required>
      </label>
      <label>
        Aliases
        <textarea name="aliases" placeholder="Her satıra bir alternatif isim yaz"></textarea>
        <span class="help">Opsiyonel. Her satıra bir alias.</span>
      </label>
      <label>
        Known Info
        <textarea name="known_info" placeholder="Bilinen şirket, şehir, repo, ünvan vb."></textarea>
        <span class="help">Opsiyonel. Her satıra bir bilgi.</span>
      </label>
      <label>
        Search Scope
      </label>
      <div class="scopes">
        <label><input type="checkbox" name="search_scope" value="github"> GitHub</label>
        <label><input type="checkbox" name="search_scope" value="linkedin"> LinkedIn</label>
        <label><input type="checkbox" name="search_scope" value="wikipedia"> Wikipedia</label>
        <label><input type="checkbox" name="search_scope" value="general_web"> Genel Web</label>
      </div>
      <label>
        Constraints
        <textarea name="constraints" placeholder="Zaman aralığı, coğrafya, dil, kapsam sınırı vb."></textarea>
      </label>
      <button type="submit">Araştırmayı Başlat</button>
    </form>
    {summary_html}
  </main>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def intake_form() -> HTMLResponse:
    return HTMLResponse(render_form())


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/search", response_model=SearchResponse, tags=["research"])
async def api_search(intake: SearchIntake) -> SearchResponse:
    return _build_search_response(intake)


@app.post("/search", response_class=HTMLResponse)
async def submit_search(
    target_name: str = Form(...),
    entity_type: str = Form("person"),
    purpose: str = Form(...),
    aliases: str = Form(""),
    known_info: str = Form(""),
    search_scope: list[str] = Form(default=[]),
    constraints: str = Form(""),
) -> HTMLResponse:
    intake = SearchIntake(
        target_name=target_name.strip(),
        aliases=_split_lines(aliases),
        entity_type=entity_type,
        purpose=purpose.strip(),
        known_info=_split_lines(known_info),
        search_scope=search_scope,
        constraints=constraints.strip() or None,
    )
    result = _build_search_response(intake)
    return HTMLResponse(
        render_form(
            result={
                "intake": result.intake.model_dump(),
                "node_count": result.node_count,
                "edge_count": result.edge_count,
            }
        )
    )
