"""Interactive browser-based local UI runner for Knowledge Brain.

Launches a local web UI where you can visually test recall, remember, handoff, and forget.
"""

from __future__ import annotations

import webbrowser
from typing import Any
import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from brain.memory_service import MemoryService

svc = MemoryService()

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Knowledge Brain (Local MCP Test Runner)</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }
    h1 { color: #38bdf8; margin-bottom: 4px; }
    p.sub { color: #94a3b8; margin-top: 0; margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 18px; }
    .card h2 { margin-top: 0; font-size: 1.1rem; color: #f1f5f9; border-bottom: 1px solid #334155; padding-bottom: 8px; }
    label { display: block; font-size: 0.82rem; color: #94a3b8; margin-top: 10px; margin-bottom: 4px; }
    input, select, textarea { width: 100%; box-sizing: border-box; background: #0f172a; border: 1px solid #475569; border-radius: 4px; padding: 8px; color: #f8fafc; font-family: inherit; }
    textarea { resize: vertical; }
    button { background: #2563eb; color: white; border: none; border-radius: 4px; padding: 10px 16px; margin-top: 12px; cursor: pointer; font-weight: 600; width: 100%; }
    button:hover { background: #1d4ed8; }
    pre { background: #020617; border: 1px solid #1e293b; border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 0.85rem; color: #a5f3fc; white-space: pre-wrap; }
    .status-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; background: #065f46; color: #a7f3d0; font-size: 0.75rem; font-weight: bold; }
  </style>
</head>
<body>
  <h1>🧠 Knowledge Brain: Local MCP Runner</h1>
  <p class="sub">Test all 4 MCP tools interactively on your local Kuzu graph database.</p>

  <div class="grid">
    <!-- RECALL TOOL -->
    <div class="card">
      <h2>1. 🔍 recall(query, token_budget)</h2>
      <label>Search Query</label>
      <input type="text" id="recall_q" value="database choice for contest platform">
      <label>Token Budget</label>
      <input type="number" id="recall_budget" value="1200">
      <button onclick="doRecall()">Run recall()</button>
      <label>Retrieved Context Output:</label>
      <pre id="recall_out">// Results will appear here</pre>
    </div>

    <!-- REMEMBER TOOL -->
    <div class="card">
      <h2>2. 💾 remember(kind, topic, title, content)</h2>
      <div style="display:flex; gap:10px;">
        <div style="flex:1;">
          <label>Kind</label>
          <select id="rem_kind">
            <option value="decision">decision</option>
            <option value="constraint">constraint</option>
            <option value="failed_attempt">failed_attempt</option>
            <option value="preference">preference</option>
          </select>
        </div>
        <div style="flex:1;">
          <label>Authority</label>
          <select id="rem_auth">
            <option value="user">user</option>
            <option value="verified">verified</option>
            <option value="agent">agent</option>
          </select>
        </div>
      </div>
      <label>Topic</label>
      <input type="text" id="rem_topic" value="database">
      <label>Subject Key</label>
      <input type="text" id="rem_key" value="db:primary">
      <label>Title</label>
      <input type="text" id="rem_title" value="Use MongoDB for contest data">
      <label>Content / Trade-offs</label>
      <textarea id="rem_content" rows="2">Contest schemas change weekly; document model avoids schema migrations.</textarea>
      <button onclick="doRemember()">Run remember()</button>
      <label>Response:</label>
      <pre id="rem_out">// Status will appear here</pre>
    </div>

    <!-- HANDOFF TOOL -->
    <div class="card">
      <h2>3. 🤝 handoff(summary, next_steps, blockers)</h2>
      <label>Summary of Progress</label>
      <input type="text" id="ho_sum" value="Completed RS256 token validation middleware.">
      <label>Concrete Next Steps</label>
      <input type="text" id="ho_next" value="Wire up refresh token endpoint in auth router.">
      <label>Known Blockers</label>
      <input type="text" id="ho_block" value="Need test Redis container on port 6379.">
      <button onclick="doHandoff()">Run handoff()</button>
      <label>Response:</label>
      <pre id="ho_out">// Handover ID & dirty files captured</pre>
    </div>

    <!-- FORGET TOOL -->
    <div class="card">
      <h2>4. 🧹 forget(target)</h2>
      <label>Target phrase or secret to redact across graph</label>
      <input type="text" id="fg_target" value="super_secret_token_42">
      <button onclick="doForget()" style="background:#dc2626;">Run forget() with 0-Leak Verification</button>
      <label>Verification Audit Result:</label>
      <pre id="fg_out">// Scrub count and leak verification</pre>
    </div>
  </div>

  <script>
    async function doRecall() {
      const q = document.getElementById('recall_q').value;
      const b = document.getElementById('recall_budget').value;
      const res = await fetch('/api/recall', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query: q, token_budget: parseInt(b)})
      });
      const data = await res.json();
      document.getElementById('recall_out').textContent =
        `[Retrieved Tokens: ${data.retrieved_tokens} | Baseline: ${data.full_history_tokens} | Savings: ${data.savings_pct}% | Latency: ${data.latency_ms}ms]\n\n` + data.context;
    }

    async function doRemember() {
      const payload = {
        kind: document.getElementById('rem_kind').value,
        authority: document.getElementById('rem_auth').value,
        topic: document.getElementById('rem_topic').value,
        subject_key: document.getElementById('rem_key').value,
        title: document.getElementById('rem_title').value,
        content: document.getElementById('rem_content').value
      };
      const res = await fetch('/api/remember', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      document.getElementById('rem_out').textContent = JSON.stringify(data, null, 2);
    }

    async function doHandoff() {
      const payload = {
        summary: document.getElementById('ho_sum').value,
        next_steps: document.getElementById('ho_next').value,
        blockers: document.getElementById('ho_block').value
      };
      const res = await fetch('/api/handoff', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      document.getElementById('ho_out').textContent = JSON.stringify(data, null, 2);
    }

    async function doForget() {
      const target = document.getElementById('fg_target').value;
      const res = await fetch('/api/forget', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target: target})
      });
      const data = await res.json();
      document.getElementById('fg_out').textContent = JSON.stringify(data, null, 2);
    }
  </script>
</body>
</html>
"""

async def homepage(request):
    return HTMLResponse(HTML_PAGE)

async def api_recall(request):
    body = await request.json()
    res = svc.recall(query=body.get("query", ""), token_budget=body.get("token_budget", 1200))
    return JSONResponse(res)

async def api_remember(request):
    body = await request.json()
    res = svc.remember(
        kind=body.get("kind", "decision"),
        authority=body.get("authority", "user"),
        topic=body.get("topic", "general"),
        subject_key=body.get("subject_key", "general"),
        title=body.get("title", ""),
        content=body.get("content", ""),
    )
    return JSONResponse(res)

async def api_handoff(request):
    body = await request.json()
    res = svc.handoff(
        summary=body.get("summary", ""),
        next_steps=body.get("next_steps", ""),
        blockers=body.get("blockers", ""),
    )
    return JSONResponse(res)

async def api_forget(request):
    body = await request.json()
    res = svc.forget(target=body.get("target", ""))
    return JSONResponse(res)

app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/api/recall", api_recall, methods=["POST"]),
        Route("/api/remember", api_remember, methods=["POST"]),
        Route("/api/handoff", api_handoff, methods=["POST"]),
        Route("/api/forget", api_forget, methods=["POST"]),
    ]
)

def main():
    print("Opening Knowledge Brain test UI in your browser at http://127.0.0.1:8765 ...")
    webbrowser.open("http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")

if __name__ == "__main__":
    main()

