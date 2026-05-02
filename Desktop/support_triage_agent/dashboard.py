"""
STIS Web Dashboard — FastAPI server + live triage API.
Run: python src/dashboard.py
Open: http://localhost:8000
"""

import os, sys, json, time
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, StreamingResponse
    import uvicorn
    FASTAPI = True
except ImportError:
    FASTAPI = False

sys.path.insert(0, str(Path(__file__).parent))
from engine import process, LOG_FILE, OUT_FILE

app = FastAPI(title="STIS Dashboard", docs_url=None, redoc_url=None) if FASTAPI else None

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>STIS — Support Triage Intelligence System</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;700;800&display=swap');

  :root {
    --bg:     #05070f;
    --panel:  #0c1020;
    --border: #1a2040;
    --accent: #3d7fff;
    --green:  #00e5a0;
    --yellow: #f5c518;
    --red:    #ff4444;
    --pink:   #ff2d6b;
    --dim:    #3a4060;
    --text:   #cdd6f4;
    --mono:   'JetBrains Mono', monospace;
    --sans:   'Syne', sans-serif;
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--mono);
    font-size: 13px;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Grid noise overlay */
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image:
      linear-gradient(rgba(61,127,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(61,127,255,0.03) 1px, transparent 1px);
    background-size: 32px 32px;
    pointer-events: none;
    z-index: 0;
  }

  /* Header */
  header {
    position: sticky; top: 0; z-index: 100;
    background: rgba(5,7,15,0.92);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 16px;
    padding: 14px 28px;
  }
  .logo {
    font-family: var(--sans);
    font-size: 20px;
    font-weight: 800;
    letter-spacing: -0.5px;
    color: #fff;
  }
  .logo span { color: var(--accent); }
  .tagline { font-size: 11px; color: var(--dim); letter-spacing: 2px; text-transform: uppercase; }
  .header-right { margin-left: auto; display: flex; gap: 20px; align-items: center; }
  .stat-pill {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 11px;
    display: flex; gap: 6px; align-items: center;
  }
  .stat-pill .val { color: var(--accent); font-weight: 700; }
  .live-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green);
    animation: pulse 1.5s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(.8)} }

  /* Layout */
  .layout {
    display: grid;
    grid-template-columns: 320px 1fr;
    grid-template-rows: 1fr;
    height: calc(100vh - 57px);
    position: relative; z-index: 1;
  }

  /* Sidebar */
  .sidebar {
    background: var(--panel);
    border-right: 1px solid var(--border);
    display: flex; flex-direction: column;
    overflow: hidden;
  }
  .sidebar-title {
    padding: 16px 20px 12px;
    font-family: var(--sans);
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--dim);
    border-bottom: 1px solid var(--border);
  }

  /* Input form */
  .form-section { padding: 16px 20px; border-bottom: 1px solid var(--border); }
  label { display: block; font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--dim); margin-bottom: 5px; }
  input[type=text], select, textarea {
    width: 100%;
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: var(--mono);
    font-size: 12px;
    padding: 8px 10px;
    margin-bottom: 10px;
    transition: border-color .2s;
    resize: vertical;
  }
  input[type=text]:focus, select:focus, textarea:focus {
    outline: none;
    border-color: var(--accent);
  }
  select option { background: var(--panel); }
  textarea { min-height: 100px; }

  .btn-primary {
    width: 100%;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 10px;
    font-family: var(--sans);
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1px;
    cursor: pointer;
    transition: opacity .2s, transform .1s;
  }
  .btn-primary:hover { opacity: .85; }
  .btn-primary:active { transform: scale(.98); }
  .btn-primary:disabled { opacity: .4; cursor: not-allowed; }

  /* Ticket feed */
  .feed { flex: 1; overflow-y: auto; }
  .feed::-webkit-scrollbar { width: 4px; }
  .feed::-webkit-scrollbar-track { background: transparent; }
  .feed::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  .ticket-item {
    padding: 12px 20px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background .15s;
    animation: slideIn .25s ease;
  }
  @keyframes slideIn { from{opacity:0;transform:translateX(-8px)} to{opacity:1;transform:none} }
  .ticket-item:hover { background: rgba(61,127,255,0.05); }
  .ticket-item.active { background: rgba(61,127,255,0.1); border-left: 2px solid var(--accent); }

  .ti-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .ti-id { font-size: 10px; color: var(--dim); }
  .ti-status { font-size: 10px; font-weight: 700; border-radius: 3px; padding: 1px 6px; }
  .ti-status.replied   { color: var(--green); border: 1px solid var(--green); }
  .ti-status.escalated { color: var(--yellow); border: 1px solid var(--yellow); }
  .ti-subject { font-size: 12px; font-weight: 600; margin-bottom: 3px; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ti-meta { font-size: 10px; color: var(--dim); display: flex; gap: 8px; }
  .risk-badge { font-size: 10px; font-weight: 700; padding: 0px 5px; border-radius: 3px; }
  .risk-LOW      { color: var(--green); }
  .risk-MEDIUM   { color: var(--yellow); }
  .risk-HIGH     { color: var(--red); }
  .risk-CRITICAL { color: #fff; background: var(--red); }

  /* Main panel */
  .main-panel {
    display: flex; flex-direction: column;
    overflow: hidden;
  }

  /* Detail view */
  .detail-empty {
    flex: 1; display: flex; align-items: center; justify-content: center;
    flex-direction: column; gap: 12px; color: var(--dim);
  }
  .detail-empty .icon { font-size: 48px; opacity: .2; }

  .detail-view { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; }
  .detail-view::-webkit-scrollbar { width: 4px; }
  .detail-view::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  .detail-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }
  .dh-left h2 { font-family: var(--sans); font-size: 20px; font-weight: 800; color: #fff; }
  .dh-left .dh-sub { font-size: 11px; color: var(--dim); margin-top: 3px; }
  .dh-right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }

  .big-status {
    font-family: var(--sans);
    font-size: 18px; font-weight: 800;
    letter-spacing: 2px;
    padding: 4px 14px;
    border-radius: 6px;
  }
  .big-status.replied   { color: var(--green); border: 2px solid var(--green); }
  .big-status.escalated { color: var(--yellow); border: 2px solid var(--yellow); }

  /* Cards grid */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 14px;
  }
  .card-label { font-size: 9px; letter-spacing: 2px; text-transform: uppercase; color: var(--dim); margin-bottom: 6px; }
  .card-val { font-size: 15px; font-weight: 700; color: #fff; }
  .card-val.green  { color: var(--green); }
  .card-val.yellow { color: var(--yellow); }
  .card-val.red    { color: var(--red); }
  .card-val.blue   { color: var(--accent); }

  /* Risk bar */
  .risk-bar-wrap { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
  .rbw-title { font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: var(--dim); margin-bottom: 10px; }
  .risk-bar-track { background: var(--border); border-radius: 4px; height: 8px; overflow: hidden; }
  .risk-bar-fill { height: 100%; border-radius: 4px; transition: width 1s ease; }
  .risk-bar-meta { display: flex; justify-content: space-between; margin-top: 6px; font-size: 11px; }
  .triggers { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .trigger-tag {
    background: rgba(255,68,68,.12);
    color: var(--red);
    border: 1px solid rgba(255,68,68,.3);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 10px;
  }

  /* Response box */
  .response-box {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }
  .rb-header {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--dim);
  }
  .rb-body { padding: 16px; line-height: 1.7; color: var(--text); font-size: 13px; }

  /* Intent section */
  .intent-box {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
  }
  .intent-primary { font-size: 14px; color: #fff; margin-bottom: 8px; }
  .intent-flags { display: flex; flex-wrap: wrap; gap: 5px; }
  .intent-flag {
    background: rgba(255,45,107,.1);
    color: var(--pink);
    border: 1px solid rgba(255,45,107,.3);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 10px;
  }

  /* Coverage bar */
  .cov-wrap { display: flex; align-items: center; gap: 10px; margin-top: 4px; }
  .cov-track { flex: 1; background: var(--border); border-radius: 4px; height: 6px; overflow: hidden; }
  .cov-fill { height: 100%; border-radius: 4px; background: var(--accent); transition: width 1s ease; }
  .cov-label { font-size: 11px; min-width: 36px; text-align: right; }

  /* Justification */
  .justif { font-size: 12px; color: var(--dim); font-style: italic; padding: 10px 0; }

  /* Processing thinking indicator */
  .thinking {
    display: none;
    align-items: center; gap: 10px;
    padding: 12px 20px;
    background: rgba(61,127,255,.07);
    border-top: 1px solid var(--border);
    font-size: 12px; color: var(--accent);
  }
  .thinking.show { display: flex; }
  .spin { animation: spin .8s linear infinite; display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Scrollable log */
  .log-panel {
    border-top: 1px solid var(--border);
    height: 140px;
    overflow-y: auto;
    background: #030508;
    font-size: 11px;
    color: #5a6080;
    padding: 8px 16px;
  }
  .log-panel::-webkit-scrollbar { width: 3px; }
  .log-panel::-webkit-scrollbar-thumb { background: var(--border); }
  .log-line { padding: 1px 0; font-family: var(--mono); }
  .log-line .ts { color: var(--dim); margin-right: 8px; }
  .log-line .info { color: var(--accent); }
  .log-line .warn { color: var(--yellow); }
  .log-line .err  { color: var(--red); }
</style>
</head>
<body>

<header>
  <div>
    <div class="logo">ST<span>I</span>S</div>
    <div class="tagline">Support Triage Intelligence System</div>
  </div>
  <div class="header-right">
    <div class="stat-pill"><span>Tickets</span><span class="val" id="hdr-total">0</span></div>
    <div class="stat-pill"><span>Replied</span><span class="val" id="hdr-replied" style="color:var(--green)">0</span></div>
    <div class="stat-pill"><span>Escalated</span><span class="val" id="hdr-escalated" style="color:var(--yellow)">0</span></div>
    <div class="stat-pill"><span>Threats</span><span class="val" id="hdr-threats" style="color:var(--red)">0</span></div>
    <div class="live-dot" title="System live"></div>
  </div>
</header>

<div class="layout">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-title">Submit Ticket</div>

    <div class="form-section">
      <label>Domain</label>
      <select id="f-company">
        <option value="hackerrank">HackerRank</option>
        <option value="claude">Claude</option>
        <option value="visa">Visa</option>
      </select>

      <label>Subject</label>
      <input type="text" id="f-subject" placeholder="Brief summary…" />

      <label>Issue</label>
      <textarea id="f-issue" placeholder="Describe the support request in detail…"></textarea>

      <button class="btn-primary" id="submit-btn" onclick="submitTicket()">▶ ANALYZE TICKET</button>
    </div>

    <div class="sidebar-title" style="margin-top:0">Recent Tickets</div>
    <div class="feed" id="ticket-feed"></div>
  </aside>

  <!-- Main -->
  <main class="main-panel">
    <div class="detail-view" id="detail-view">
      <div class="detail-empty">
        <div class="icon">⬡</div>
        <div>Submit a ticket to begin triage analysis</div>
      </div>
    </div>

    <div class="thinking" id="thinking">
      <span class="spin">⟳</span>
      <span id="thinking-text">Decomposing intent…</span>
    </div>

    <div class="log-panel" id="log-panel">
      <div class="log-line"><span class="ts">00:00:00</span><span class="info">STIS initialized. Awaiting tickets.</span></div>
    </div>
  </main>
</div>

<script>
const tickets = [];
let counters = { total:0, replied:0, escalated:0, threats:0 };

function log(msg, type='info') {
  const lp = document.getElementById('log-panel');
  const ts = new Date().toTimeString().slice(0,8);
  const div = document.createElement('div');
  div.className = 'log-line';
  div.innerHTML = `<span class="ts">${ts}</span><span class="${type}">${msg}</span>`;
  lp.appendChild(div);
  lp.scrollTop = lp.scrollHeight;
}

const THINKING_STEPS = [
  'Decomposing intent layers…',
  'Scoring risk profile…',
  'Searching corpus…',
  'Running routing logic…',
  'Generating response…',
];
let thinkingTimer = null;

function startThinking() {
  let i = 0;
  const el = document.getElementById('thinking-text');
  document.getElementById('thinking').classList.add('show');
  thinkingTimer = setInterval(() => {
    el.textContent = THINKING_STEPS[i % THINKING_STEPS.length];
    i++;
  }, 900);
}
function stopThinking() {
  clearInterval(thinkingTimer);
  document.getElementById('thinking').classList.remove('show');
}

function riskColor(level) {
  return { LOW:'#00e5a0', MEDIUM:'#f5c518', HIGH:'#ff4444', CRITICAL:'#ff4444' }[level] || '#888';
}

function updateHeaders() {
  document.getElementById('hdr-total').textContent = counters.total;
  document.getElementById('hdr-replied').textContent = counters.replied;
  document.getElementById('hdr-escalated').textContent = counters.escalated;
  document.getElementById('hdr-threats').textContent = counters.threats;
}

function addTicketToFeed(tk) {
  const feed = document.getElementById('ticket-feed');
  const div = document.createElement('div');
  div.className = 'ticket-item';
  div.dataset.idx = tickets.length - 1;
  div.innerHTML = `
    <div class="ti-header">
      <span class="ti-id">${tk.ticket_id}</span>
      <span class="ti-status ${tk.status}">${tk.status.toUpperCase()}</span>
    </div>
    <div class="ti-subject">${escHtml(tk.subject || '(no subject)')}</div>
    <div class="ti-meta">
      <span class="risk-badge risk-${tk.risk.level}">${tk.risk.level}</span>
      <span>${tk.domain}</span>
      <span>${tk.product_area}</span>
    </div>`;
  div.onclick = () => showDetail(parseInt(div.dataset.idx));
  feed.insertBefore(div, feed.firstChild);
  showDetail(tickets.length - 1);
}

function showDetail(idx) {
  // un-highlight all
  document.querySelectorAll('.ticket-item').forEach(el => el.classList.remove('active'));
  const feedItems = document.querySelectorAll('.ticket-item');
  const reverseIdx = feedItems.length - 1 - idx;
  if(feedItems[reverseIdx]) feedItems[reverseIdx].classList.add('active');

  const tk = tickets[idx];
  if(!tk) return;

  const riskPct = tk.risk.score;
  const rc = riskColor(tk.risk.level);
  const covPct = Math.round(tk.grounding.coverage_score * 100);
  const confPct = Math.round(tk.confidence * 100);

  const hiddenFlags = (tk.intent.hidden_flags || []).filter(f => f && f !== 'none');
  const triggers    = (tk.risk.triggers || []);

  document.getElementById('detail-view').innerHTML = `
    <div class="detail-header">
      <div class="dh-left">
        <h2>${escHtml(tk.subject || '(no subject)')}</h2>
        <div class="dh-sub">${tk.ticket_id} · ${tk.domain.toUpperCase()} · ${tk.processing_ms}ms</div>
      </div>
      <div class="dh-right">
        <div class="big-status ${tk.status}">${tk.status.toUpperCase()}</div>
        <div style="font-size:11px;color:var(--dim)">${new Date().toLocaleTimeString()}</div>
      </div>
    </div>

    <!-- Cards -->
    <div class="cards">
      <div class="card"><div class="card-label">Risk Level</div>
        <div class="card-val" style="color:${rc}">${tk.risk.level}</div></div>
      <div class="card"><div class="card-label">Risk Score</div>
        <div class="card-val" style="color:${rc}">${riskPct}/100</div></div>
      <div class="card"><div class="card-label">Product Area</div>
        <div class="card-val blue">${tk.product_area}</div></div>
      <div class="card"><div class="card-label">Request Type</div>
        <div class="card-val">${tk.request_type}</div></div>
      <div class="card"><div class="card-label">Malicious</div>
        <div class="card-val ${tk.risk.malicious?'red':'green'}">${tk.risk.malicious?'YES ☠':'NO ✓'}</div></div>
      <div class="card"><div class="card-label">Confidence</div>
        <div class="card-val ${confPct>60?'green':confPct>30?'yellow':'red'}">${confPct}%</div></div>
    </div>

    <!-- Risk bar -->
    <div class="risk-bar-wrap">
      <div class="rbw-title">Risk Profile</div>
      <div class="risk-bar-track">
        <div class="risk-bar-fill" style="width:${riskPct}%;background:${rc}"></div>
      </div>
      <div class="risk-bar-meta">
        <span style="color:var(--dim)">Risk Score</span>
        <span style="color:${rc};font-weight:700">${riskPct}/100</span>
      </div>
      ${triggers.length ? `<div class="triggers">${triggers.map(t=>`<span class="trigger-tag">${t}</span>`).join('')}</div>` : ''}
    </div>

    <!-- Intent -->
    <div class="intent-box">
      <div class="card-label">Decomposed Intent</div>
      <div class="intent-primary">${escHtml(tk.intent.primary || '—')}</div>
      ${hiddenFlags.length ? `<div class="intent-flags">${hiddenFlags.map(f=>`<span class="intent-flag">⚑ ${f}</span>`).join('')}</div>` : ''}
    </div>

    <!-- Coverage -->
    <div class="card">
      <div class="card-label">Corpus Coverage</div>
      <div class="cov-wrap">
        <div class="cov-track"><div class="cov-fill" style="width:${covPct}%"></div></div>
        <div class="cov-label" style="color:${covPct>50?'var(--green)':covPct>20?'var(--yellow)':'var(--red)'}">${covPct}%</div>
      </div>
    </div>

    <!-- Response -->
    <div class="response-box">
      <div class="rb-header">
        <span>${tk.status === 'replied' ? '✉ Response' : '⚡ Escalation Message'}</span>
      </div>
      <div class="rb-body">${escHtml(tk.response || '—')}</div>
    </div>

    <!-- Justification -->
    ${tk.justification ? `<div class="justif">⟶ ${escHtml(tk.justification)}</div>` : ''}
  `;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/\n/g,'<br>');
}

async function submitTicket() {
  const company = document.getElementById('f-company').value;
  const subject = document.getElementById('f-subject').value.trim();
  const issue   = document.getElementById('f-issue').value.trim();
  const btn     = document.getElementById('submit-btn');

  if(!subject || !issue) { log('Subject and issue are required.', 'warn'); return; }

  btn.disabled = true;
  startThinking();
  log(`Submitting ticket — domain:${company} subject:"${subject.slice(0,40)}"`, 'info');

  try {
    const res = await fetch('/api/triage', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ company, subject, issue }),
    });
    const data = await res.json();
    tickets.push(data);
    counters.total++;
    if(data.status === 'replied') counters.replied++;
    else counters.escalated++;
    if(data.risk && data.risk.malicious) counters.threats++;
    updateHeaders();
    addTicketToFeed(data);
    log(`[${data.ticket_id}] ${data.status.toUpperCase()} | Risk:${data.risk.level}(${data.risk.score}) | Area:${data.product_area} | ${data.processing_ms}ms`, data.status==='replied'?'info':'warn');
    document.getElementById('f-subject').value = '';
    document.getElementById('f-issue').value = '';
  } catch(e) {
    log('Error: ' + e.message, 'err');
  } finally {
    btn.disabled = false;
    stopThinking();
  }
}

// keyboard shortcut
document.addEventListener('keydown', e => {
  if((e.ctrlKey || e.metaKey) && e.key === 'Enter') submitTicket();
});

log('Dashboard ready. Ctrl+Enter to submit.', 'info');
</script>
</body>
</html>
"""

_ticket_counter = [0]

if FASTAPI:
    from pydantic import BaseModel

    class TicketRequest(BaseModel):
        company: str
        subject: str
        issue: str

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return DASHBOARD_HTML

    @app.post("/api/triage")
    async def triage(req: TicketRequest):
        _ticket_counter[0] += 1
        tid = f"WEB-{_ticket_counter[0]:04d}"
        dec = process(tid, req.issue, req.subject, req.company)
        return {
            "ticket_id":   tid,
            "status":      dec.status,
            "product_area":dec.product_area,
            "request_type":dec.request_type,
            "domain":      dec.domain,
            "confidence":  dec.confidence,
            "processing_ms": dec.processing_ms,
            "subject":     req.subject,
            "intent":  {
                "primary":      dec.intent.primary,
                "secondary":    dec.intent.secondary,
                "hidden_flags": dec.intent.hidden_flags,
            },
            "risk": {
                "level":     dec.risk.level,
                "score":     dec.risk.score,
                "triggers":  dec.risk.triggers,
                "malicious": dec.risk.malicious,
            },
            "grounding": {
                "coverage_score": dec.grounding.coverage_score,
                "sources":        dec.grounding.sources,
            },
            "response":     dec.response,
            "justification":dec.justification,
        }

    @app.get("/api/logs")
    async def logs():
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text().strip().splitlines()[-50:]
            return [json.loads(l) for l in lines if l.strip()]
        return []


def main():
    if not FASTAPI:
        print("FastAPI not installed. Run: pip install fastapi uvicorn")
        return
    print("🌐 STIS Dashboard → http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
