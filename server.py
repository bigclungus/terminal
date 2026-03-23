#!/usr/bin/env python3
"""
Live terminal stream server — streams /tmp/screenlog.txt to websocket clients,
served alongside an xterm.js HTML page.
"""
import asyncio
import glob
import json
import os
import re
import subprocess
import time
import urllib.request
import falkordb as _fdb
from datetime import datetime, timezone
from aiohttp import web

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTH_PASSWORD = "rbl8D4NgcA9Mp@2o"
AUTH_COOKIE   = "tauth"
COOKIE_MAX_AGE = 86400  # 24 hours

LOGIN_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Login — BigClungus Terminal</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#0d0d0d; color:#d4d4d4; font-family:monospace;
           display:flex; align-items:center; justify-content:center; height:100vh; }}
    .box {{ background:#1a1a2e; border:1px solid #e94560; border-radius:6px;
           padding:32px 40px; min-width:300px; text-align:center; }}
    h2 {{ color:#e94560; margin-bottom:20px; font-size:16px; letter-spacing:.05em; }}
    input[type=password] {{ width:100%; padding:8px 10px; background:#0d0d0d;
      border:1px solid #2a2a4e; color:#d4d4d4; font-family:monospace;
      font-size:14px; border-radius:3px; margin-bottom:12px; outline:none; }}
    input[type=password]:focus {{ border-color:#e94560; }}
    button {{ width:100%; padding:9px; background:#e94560; color:#fff;
             border:none; border-radius:3px; font-family:monospace;
             font-size:14px; cursor:pointer; }}
    button:hover {{ background:#c73050; }}
    .err {{ color:#e94560; font-size:12px; margin-top:10px; }}
  </style>
</head>
<body>
  <div class="box">
    <h2>&#x1F916; BigClungus Terminal</h2>
    <form method="POST" action="/login">
      <input type="password" name="password" placeholder="Password" autofocus>
      <button type="submit">Enter</button>
      {error}
    </form>
  </div>
</body>
</html>"""


async def login_handler(request):
    if request.method == 'GET':
        return web.Response(
            text=LOGIN_HTML.format(error=''),
            content_type='text/html',
        )
    # POST — check password
    try:
        data = await request.post()
        pw = data.get('password', '')
    except Exception:
        pw = ''
    if pw == AUTH_PASSWORD:
        resp = web.HTTPFound('/')
        resp.set_cookie(
            AUTH_COOKIE, 'ok',
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite='Lax',
        )
        return resp
    return web.Response(
        text=LOGIN_HTML.format(error='<p class="err">Wrong password.</p>'),
        content_type='text/html',
        status=401,
    )


def _is_authed(request):
    return request.cookies.get(AUTH_COOKIE) == 'ok'


@web.middleware
async def auth_middleware(request, handler):
    path = request.path
    if path == '/login':
        return await handler(request)
    if not _is_authed(request):
        raise web.HTTPFound('/login')
    return await handler(request)
# ─────────────────────────────────────────────────────────────────────────────

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

LOGFILE = "/tmp/screenlog.txt"
TASKS_DIR = "/tmp/claude-1001/-mnt-data/bb9407c6-0d39-400c-af71-7c6765df2c69/tasks"

HTML = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="icon" type="image/png" href="https://hello.clung.us/favicon.png">
  <title>BigClungus Live Terminal</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css" />
  <script src="/gamecube-sounds.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { background: #0d0d0d; display: flex; flex-direction: column; height: 100vh; font-family: monospace; }
    #header {
      background: #1a1a2e;
      color: #e94560;
      padding: 8px 16px;
      font-size: 14px;
      font-weight: bold;
      display: flex;
      align-items: center;
      gap: 12px;
      border-bottom: 1px solid #e94560;
      flex-shrink: 0;
    }
    #status { font-size: 11px; color: #888; margin-left: auto; }
    #status.connected { color: #4caf50; }
    #status.disconnected { color: #e94560; }
    #healthbar {
      background: #111122;
      border-bottom: 1px solid #2a2a4e;
      padding: 5px 16px;
      display: flex;
      align-items: center;
      gap: 18px;
      flex-wrap: wrap;
      flex-shrink: 0;
      font-size: 11px;
      font-family: monospace;
      color: #aaa;
    }
    .hb-metric {
      display: flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }
    .hb-label {
      color: #e94560;
      font-weight: bold;
      min-width: 30px;
    }
    .hb-bar-wrap {
      width: 60px;
      height: 6px;
      background: #2a2a4e;
      border-radius: 3px;
      overflow: hidden;
    }
    .hb-bar-fill {
      height: 100%;
      border-radius: 3px;
      background: #4caf50;
      transition: width 0.4s ease;
    }
    .hb-bar-fill.warn { background: #f0c040; }
    .hb-bar-fill.crit { background: #e94560; }
    .hb-val { color: #ccc; min-width: 34px; }
    .hb-sep { color: #2a2a4e; }
    .hb-svc {
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .hb-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #444;
      flex-shrink: 0;
    }
    .hb-dot.ok { background: #4caf50; box-shadow: 0 0 4px #4caf50; }
    .hb-dot.down { background: #e94560; box-shadow: 0 0 4px #e94560; }
    .hb-uptime { color: #888; }
    #main {
      display: flex;
      flex: 1;
      overflow: hidden;
      min-height: 0;
    }
    #terminal {
      width: 70%;
      padding: 4px;
      overflow: hidden;
      flex-shrink: 0;
    }
    #agents {
      width: 30%;
      background: #1a1a2e;
      border-left: 1px solid #2a2a4e;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    #agents-header {
      padding: 10px 14px;
      color: #e94560;
      font-size: 12px;
      font-weight: bold;
      border-bottom: 1px solid #2a2a4e;
      flex-shrink: 0;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }
    #agents-list {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
    }
    #agents-list::-webkit-scrollbar { width: 4px; }
    #agents-list::-webkit-scrollbar-track { background: #1a1a2e; }
    #agents-list::-webkit-scrollbar-thumb { background: #e94560; border-radius: 2px; }
    .xterm-viewport::-webkit-scrollbar { width: 4px; }
    .xterm-viewport::-webkit-scrollbar-track { background: #1a1a2e; }
    .xterm-viewport::-webkit-scrollbar-thumb { background: #e94560; border-radius: 2px; }
    .task-card {
      background: #0d0d1a;
      border: 1px solid #2a2a4e;
      border-radius: 4px;
      padding: 8px 10px;
      margin-bottom: 6px;
      font-size: 11px;
    }
    .task-card:hover { border-color: #e94560; }
    .task-top {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 4px;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .dot.running { background: #f0c040; box-shadow: 0 0 4px #f0c040; }
    .dot.completed { background: #4caf50; }
    .task-id {
      color: #c0c0d0;
      font-weight: bold;
      font-size: 11px;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .task-age {
      color: #555;
      font-size: 10px;
      flex-shrink: 0;
    }
    .task-description {
      color: #aaa;
      font-size: 11px;
      margin-bottom: 4px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .task-requester {
      color: #6b5ce7;
      font-size: 10px;
      flex-shrink: 0;
    }
    .task-summary {
      color: #777;
      font-size: 10px;
      line-height: 1.4;
      word-break: break-all;
      white-space: pre-wrap;
      max-height: 48px;
      overflow: hidden;
    }
    .task-card {
      cursor: pointer;
    }
    .task-card.expanded {
      border-color: #e94560;
    }
    .task-expand {
      display: none;
      margin-top: 8px;
      background: #060610;
      border: 1px solid #2a2a4e;
      border-radius: 3px;
      padding: 8px;
      max-height: 300px;
      overflow-y: auto;
      font-size: 10px;
      color: #bbb;
      white-space: pre-wrap;
      word-break: break-all;
      line-height: 1.5;
    }
    .task-expand::-webkit-scrollbar { width: 4px; }
    .task-expand::-webkit-scrollbar-track { background: #0d0d1a; }
    .task-expand::-webkit-scrollbar-thumb { background: #e94560; border-radius: 2px; }
    .task-expand.visible { display: block; }
    .task-expand-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
      color: #e94560;
      font-size: 10px;
      font-weight: bold;
    }
    .task-expand-close {
      cursor: pointer;
      padding: 0 4px;
      color: #e94560;
      font-size: 13px;
      line-height: 1;
    }
    .task-expand-close:hover { color: #fff; }
    #agents-empty {
      color: #444;
      font-size: 11px;
      text-align: center;
      padding: 24px 8px;
    }
    #graph-link {
      color: #8b949e;
      font-size: 10px;
      font-weight: normal;
      text-decoration: none;
      letter-spacing: 0;
      text-transform: none;
      padding: 2px 6px;
      border: 1px solid #2a2a4e;
      border-radius: 3px;
      background: #0d1117;
      transition: color 0.15s, border-color 0.15s;
      white-space: nowrap;
    }
    #graph-link:hover { color: #58a6ff; border-color: #58a6ff; }
    #topology-link {
      color: #8b949e;
      font-size: 10px;
      font-weight: normal;
      text-decoration: none;
      letter-spacing: 0;
      text-transform: none;
      padding: 2px 6px;
      border: 1px solid #2a2a4e;
      border-radius: 3px;
      background: #0d1117;
      transition: color 0.15s, border-color 0.15s;
      white-space: nowrap;
    }
    #topology-link:hover { color: #58a6ff; border-color: #58a6ff; }
    #home-link {
      color: #8b949e;
      font-size: 10px;
      font-weight: normal;
      text-decoration: none;
      letter-spacing: 0;
      text-transform: none;
      padding: 2px 6px;
      border: 1px solid #2a2a4e;
      border-radius: 3px;
      background: #0d1117;
      transition: color 0.15s, border-color 0.15s;
      white-space: nowrap;
    }
    #home-link:hover { color: #58a6ff; border-color: #58a6ff; }
    #restart-btn {
      color: #8b949e;
      font-size: 10px;
      font-weight: normal;
      text-decoration: none;
      letter-spacing: 0;
      text-transform: none;
      padding: 2px 6px;
      border: 1px solid #2a2a4e;
      border-radius: 3px;
      background: #0d1117;
      transition: color 0.15s, border-color 0.15s;
      white-space: nowrap;
      cursor: pointer;
    }
    #restart-btn:hover { color: #e94560; border-color: #e94560; }
  </style>
</head>
<body>
  <div id="header">
    <span>&#x1F916; BigClungus Live Session</span>
    <span id="status" class="disconnected">&#x25CF; disconnected</span>
    <a id="home-link" href="https://hello.clung.us/" target="_blank">&#x2190; clung.us</a>
    <a id="graph-link" href="/graph" target="_blank">&#x238B; Knowledge Graph</a>
    <a id="topology-link" href="/topology" target="_blank">&#x1F5FA; system</a>
    <button id="restart-btn">&#x2620; restart</button>
  </div>
  <div id="healthbar">
    <div class="hb-metric">
      <span class="hb-label">CPU</span>
      <div class="hb-bar-wrap"><div class="hb-bar-fill" id="hb-cpu-bar" style="width:0%"></div></div>
      <span class="hb-val" id="hb-cpu-val">--</span>
    </div>
    <div class="hb-sep">|</div>
    <div class="hb-metric">
      <span class="hb-label">RAM</span>
      <div class="hb-bar-wrap"><div class="hb-bar-fill" id="hb-ram-bar" style="width:0%"></div></div>
      <span class="hb-val" id="hb-ram-val">--</span>
    </div>
    <div class="hb-sep">|</div>
    <div class="hb-metric">
      <span class="hb-label">DISK</span>
      <div class="hb-bar-wrap"><div class="hb-bar-fill" id="hb-disk-bar" style="width:0%"></div></div>
      <span class="hb-val" id="hb-disk-val">--</span>
    </div>
    <div class="hb-sep">|</div>
    <div class="hb-metric">
      <span class="hb-label">SWAP</span>
      <div class="hb-bar-wrap"><div class="hb-bar-fill" id="hb-swap-bar" style="width:0%"></div></div>
      <span class="hb-val" id="hb-swap-val">--</span>
    </div>
    <div class="hb-sep">|</div>
    <div class="hb-metric">
      <span class="hb-label" style="min-width:52px">OpenAI</span>
      <div class="hb-bar-wrap" style="width:80px"><div class="hb-bar-fill" id="hb-openai-bar" style="width:0%"></div></div>
      <span class="hb-val" id="hb-openai-val" style="min-width:100px">--</span>
    </div>
    <div class="hb-sep">|</div>
    <div class="hb-svc">
      <div class="hb-dot" id="hb-dot-cloudflared"></div>
      <span>cloudflared</span>
    </div>
    <div class="hb-svc">
      <div class="hb-dot" id="hb-dot-terminal"></div>
      <span>terminal-server</span>
    </div>
    <div class="hb-sep">|</div>
    <span class="hb-uptime" id="hb-uptime">up --</span>
  </div>
  <div id="main">
    <div id="terminal"></div>
    <div id="agents">
      <div id="agents-header">&#x25A3; Subagent Tasks</div>
      <div id="agents-list">
        <div id="agents-empty">No recent tasks</div>
      </div>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js"></script>
  <script>
    const term = new Terminal({
      theme: {
        background: '#0d0d0d',
        foreground: '#d4d4d4',
        cursor: '#e94560',
      },
      convertEol: true,
      scrollback: 5000,
      fontSize: 13,
      fontFamily: 'Consolas, "Courier New", monospace',
    });
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminal'));
    fitAddon.fit();
    window.addEventListener('resize', () => fitAddon.fit());

    const statusEl = document.getElementById('status');

    function connect() {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${proto}//${location.host}/ws`);
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        statusEl.textContent = '\u25CF live';
        statusEl.className = 'connected';
      };
      ws.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) {
          term.write(new Uint8Array(e.data), () => term.scrollToBottom());
        } else {
          term.write(e.data, () => term.scrollToBottom());
        }
      };
      ws.onclose = () => {
        statusEl.textContent = '\u25CF disconnected \u2014 reconnecting...';
        statusEl.className = 'disconnected';
        setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    }
    connect();

    // Agent task panel
    function relativeTime(mtime) {
      const secs = Math.floor(Date.now() / 1000) - mtime;
      if (secs < 60) return secs + 's ago';
      if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
      return Math.floor(secs / 3600) + 'h ago';
    }

    function stripAnsi(str) {
      return str.replace(/\x1B\[[0-9;]*[mGKHF]/g, '').replace(/\x1B\][^\x07]*\x07/g, '');
    }

    function escHtml(s) {
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    const expandedCards = new Set();

    async function toggleCardExpand(card) {
      const agentId = card.dataset.id;
      const expandEl = card.querySelector('.task-expand');
      if (!expandEl) return;

      if (expandedCards.has(agentId)) {
        expandedCards.delete(agentId);
        card.classList.remove('expanded');
        expandEl.classList.remove('visible');
        return;
      }

      expandedCards.add(agentId);
      card.classList.add('expanded');
      expandEl.classList.add('visible');

      const contentEl = expandEl.querySelector('.task-expand-content');
      if (contentEl && contentEl.dataset.loaded !== 'true') {
        contentEl.textContent = 'Loading...';
        try {
          const resp = await fetch('/task-output/' + agentId);
          if (resp.ok) {
            const text = await resp.text();
            contentEl.textContent = stripAnsi(text).trim() || '(empty)';
          } else {
            contentEl.textContent = 'Error: ' + resp.status;
          }
        } catch (e) {
          contentEl.textContent = 'Fetch error: ' + e.message;
        }
        contentEl.dataset.loaded = 'true';
        // Scroll to bottom of output
        expandEl.scrollTop = expandEl.scrollHeight;
      }
    }

    function renderTasks(tasks) {
      const list = document.getElementById('agents-list');
      const empty = document.getElementById('agents-empty');
      if (!tasks || tasks.length === 0) {
        empty.style.display = '';
        // Remove any existing cards
        Array.from(list.querySelectorAll('.task-card')).forEach(c => c.remove());
        return;
      }
      empty.style.display = 'none';

      // Build a map of current task ids in DOM
      const existing = {};
      list.querySelectorAll('.task-card').forEach(c => { existing[c.dataset.id] = c; });

      const seen = new Set();
      tasks.forEach((task, idx) => {
        seen.add(task.id);
        let card = existing[task.id];
        const isNew = !card;
        if (isNew) {
          card = document.createElement('div');
          card.className = 'task-card';
          card.dataset.id = task.id;
        }
        const summary = stripAnsi(task.summary || '').trim();
        const requesterHtml = task.requester ? `<span class="task-requester">@${escHtml(task.requester)}</span>` : '';
        const desc = task.description ? `<div class="task-description">${task.description}${requesterHtml}</div>` : '';
        const wasExpanded = expandedCards.has(task.id);
        // Preserve loaded content across re-renders
        let loadedContent = null;
        let wasLoaded = false;
        if (!isNew) {
          const old = card.querySelector('.task-expand-content');
          if (old && old.dataset.loaded === 'true') {
            loadedContent = old.textContent;
            wasLoaded = true;
          }
        }
        card.innerHTML = `
          ${desc}
          <div class="task-top">
            <div class="dot ${task.status}"></div>
            <div class="task-id">${task.id.substring(0, 8)}</div>
            <div class="task-age">${relativeTime(task.mtime)}</div>
          </div>
          <div class="task-summary">${summary.substring(summary.length - 300)}</div>
          <div class="task-expand${wasExpanded ? ' visible' : ''}">
            <div class="task-expand-header">
              <span>Full Output</span>
              <span class="task-expand-close" title="Close">&times;</span>
            </div>
            <div class="task-expand-content"${wasLoaded ? ' data-loaded="true"' : ''}>${wasLoaded ? loadedContent.replace(/&/g,'&amp;').replace(/</g,'&lt;') : ''}</div>
          </div>
        `;
        if (wasExpanded) card.classList.add('expanded');

        // Close button
        card.querySelector('.task-expand-close').addEventListener('click', (e) => {
          e.stopPropagation();
          expandedCards.delete(task.id);
          card.classList.remove('expanded');
          card.querySelector('.task-expand').classList.remove('visible');
        });

        // Card click to expand
        if (isNew) {
          card.addEventListener('click', () => toggleCardExpand(card));
        }

        // Insert in order
        const cards = list.querySelectorAll('.task-card');
        if (cards.length === 0 || idx >= cards.length) {
          list.appendChild(card);
        } else if (cards[idx] !== card) {
          list.insertBefore(card, cards[idx]);
        }
      });

      // Remove stale cards
      Object.keys(existing).forEach(id => {
        if (!seen.has(id)) existing[id].remove();
      });
    }

    async function pollTasks() {
      try {
        const resp = await fetch('/tasks');
        if (resp.ok) {
          const tasks = await resp.json();
          renderTasks(tasks);
        }
      } catch (e) {
        // silently ignore
      }
    }

    pollTasks();
    setInterval(pollTasks, 3000);

    // Health bar
    function setBar(barId, valId, pct, label) {
      const bar = document.getElementById(barId);
      const val = document.getElementById(valId);
      if (!bar || !val) return;
      const w = Math.min(100, Math.max(0, pct));
      bar.style.width = w + '%';
      bar.className = 'hb-bar-fill' + (w >= 90 ? ' crit' : w >= 70 ? ' warn' : '');
      val.textContent = label;
    }

    function setOpenAIBar(spend, limit) {
      const bar = document.getElementById('hb-openai-bar');
      const val = document.getElementById('hb-openai-val');
      if (!bar || !val) return;
      const pct = limit > 0 ? Math.min(100, (spend / limit) * 100) : 0;
      bar.style.width = pct + '%';
      bar.className = 'hb-bar-fill' + (pct >= 80 ? ' crit' : pct >= 50 ? ' warn' : '');
      val.textContent = '$' + spend.toFixed(2) + ' / $' + limit.toFixed(2);
    }

    function setDot(id, ok) {
      const el = document.getElementById(id);
      if (!el) return;
      el.className = 'hb-dot ' + (ok ? 'ok' : 'down');
    }

    async function pollHealth() {
      try {
        const resp = await fetch('/health');
        if (!resp.ok) return;
        const d = await resp.json();
        setBar('hb-cpu-bar', 'hb-cpu-val', d.cpu_percent, d.cpu_percent.toFixed(1) + '%');
        setBar('hb-ram-bar', 'hb-ram-val', d.ram.percent, d.ram.percent.toFixed(1) + '%');
        setBar('hb-disk-bar', 'hb-disk-val', d.disk.percent, d.disk.percent.toFixed(1) + '%');
        setBar('hb-swap-bar', 'hb-swap-val', d.swap.percent, d.swap.percent.toFixed(1) + '%');
        if (d.openai_spend !== undefined) setOpenAIBar(d.openai_spend, d.openai_limit || 10.0);
        setDot('hb-dot-cloudflared', d.services.cloudflared);
        setDot('hb-dot-terminal', d.services['terminal-server']);
        document.getElementById('hb-uptime').textContent = 'up ' + d.uptime;
      } catch (e) {
        // silently ignore
      }
    }

    pollHealth();
    setInterval(pollHealth, 5000);

    // Restart bot button
    document.getElementById('restart-btn').addEventListener('click', async () => {
      const pw = prompt('Password:');
      if (pw === null) return;
      try {
        const resp = await fetch('/restart-bot', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({password: pw}),
        });
        const data = await resp.json();
        if (data.ok) {
          alert('Bot restarted.');
        } else {
          alert('Failed: ' + (data.error || 'unknown error'));
        }
      } catch (e) {
        alert('Request error: ' + e.message);
      }
    });

    // GameCube sounds on all buttons and nav links
    document.querySelectorAll('button, #header a').forEach(function(el) {
      el.addEventListener('mouseenter', function() { if (window.GCSounds) GCSounds.hover(); });
      el.addEventListener('click', function() { if (window.GCSounds) GCSounds.click(); }, true);
    });

  </script>
</body>
</html>
"""

async def index(request):
    return web.Response(text=HTML, content_type='text/html')

async def graph_page_handler(request):
    graph_html_path = os.path.join(os.path.dirname(__file__), 'graph.html')
    with open(graph_html_path, 'r') as f:
        content = f.read()
    return web.Response(text=content, content_type='text/html')

async def websocket_handler(request):
    if not _is_authed(request):
        # Reject unauthenticated WebSocket connections immediately
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.close(code=4401, message=b'Unauthorized')
        return ws

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Send existing log content first
    try:
        with open(LOGFILE, 'rb') as f:
            existing = f.read()
        if existing:
            await ws.send_bytes(existing)
    except FileNotFoundError:
        pass

    # Tail new content
    with open(LOGFILE, 'rb') as f:
        f.seek(0, 2)  # seek to end
        while not ws.closed:
            chunk = f.read(4096)
            if chunk:
                await ws.send_bytes(chunk)
            else:
                await asyncio.sleep(0.05)

    return ws

def get_task_description(agent_id, fpath):
    """Return a short human-readable description for a task.

    Priority:
    1. {agent_id}.meta.json in the same directory — use its 'description' field.
    2. First line of the output file parsed as JSONL — extract message.content,
       take the first line, truncate to 60 chars, strip 'You are BigClungus' prefix.
    """
    tasks_dir = os.path.dirname(fpath)
    meta_path = os.path.join(tasks_dir, agent_id + '.meta.json')
    try:
        with open(meta_path, 'r') as f:
            meta = json.load(f)
        desc = meta.get('description', '').strip()
        if desc:
            return desc
    except (OSError, json.JSONDecodeError, KeyError):
        pass

    # Fall back to parsing first line of output file
    try:
        with open(fpath, 'r', errors='replace') as f:
            first_line = f.readline()
        obj = json.loads(first_line)
        if not isinstance(obj, dict):
            return ''
        content = obj.get('message', {}).get('content', '')
        if not isinstance(content, str):
            return ''
        # Take first non-empty line of the content
        first_content_line = ''
        for line in content.splitlines():
            if line.strip():
                first_content_line = line.strip()
                break
        if not first_content_line:
            return ''
        # Strip common prefix
        prefix = 'You are BigClungus'
        if first_content_line.startswith(prefix):
            remainder = first_content_line[len(prefix):].lstrip('., ')
            # Take up to first sentence end or just truncate
            for sep in ['. ', '! ', '? ']:
                idx = remainder.find(sep)
                if idx != -1:
                    remainder = remainder[:idx + 1]
                    break
            first_content_line = remainder
        return first_content_line[:60]
    except (OSError, json.JSONDecodeError, KeyError, StopIteration):
        return ''


async def tasks_handler(request):
    now = time.time()
    two_hours_ago = now - 7200
    thirty_secs_ago = now - 30

    tasks = []
    try:
        entries = os.listdir(TASKS_DIR)
    except FileNotFoundError:
        return web.Response(text='[]', content_type='application/json')

    for fname in entries:
        if not fname.endswith('.output'):
            continue
        fpath = os.path.join(TASKS_DIR, fname)
        try:
            stat = os.stat(fpath)
        except OSError:
            continue

        mtime = stat.st_mtime
        if mtime < two_hours_ago:
            continue

        # Read last 200 bytes for summary
        summary = ''
        try:
            with open(fpath, 'rb') as f:
                f.seek(max(0, stat.st_size - 200), 0)
                raw = f.read(200)
            summary = raw.decode('utf-8', errors='replace')
            # Get last non-empty line
            lines = [l for l in summary.splitlines() if l.strip()]
            summary = lines[-1] if lines else summary.strip()
        except OSError:
            pass

        agent_id = fname[:-7]  # strip .output
        status = 'running' if mtime >= thirty_secs_ago else 'completed'
        description = get_task_description(agent_id, fpath)

        requester = ''
        meta_path = os.path.join(TASKS_DIR, agent_id + '.meta.json')
        try:
            with open(meta_path) as f:
                requester = json.load(f).get('requester', '')
        except (OSError, json.JSONDecodeError):
            pass

        tasks.append({
            'id': agent_id,
            'status': status,
            'summary': summary,
            'description': description,
            'requester': requester,
            'mtime': int(mtime),
        })

    tasks.sort(key=lambda t: t['mtime'], reverse=True)
    return web.Response(text=json.dumps(tasks), content_type='application/json')


async def task_output_handler(request):
    agent_id = request.match_info['agentId']
    if not agent_id.replace('-', '').replace('_', '').isalnum():
        return web.Response(status=400, text='Invalid agentId')
    fpath = os.path.join(TASKS_DIR, agent_id + '.output')
    try:
        with open(fpath, 'r', errors='replace') as f:
            content = f.read()
    except FileNotFoundError:
        return web.Response(status=404, text='Task output not found')
    except OSError as e:
        return web.Response(status=500, text=str(e))
    return web.Response(text=content, content_type='text/plain')


async def meta_handler(request):
    agent_id = request.match_info['agentId']
    # Basic sanity check — agent IDs are hex strings
    if not agent_id.replace('-', '').replace('_', '').isalnum():
        return web.Response(status=400, text='Invalid agentId')
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text='Invalid JSON')
    description = body.get('description', '').strip()
    if not description:
        return web.Response(status=400, text='Missing description field')
    requester = body.get('requester', '').strip()
    meta_path = os.path.join(TASKS_DIR, agent_id + '.meta.json')
    try:
        os.makedirs(TASKS_DIR, exist_ok=True)
        with open(meta_path, 'w') as f:
            json.dump({'description': description, 'requester': requester}, f)
    except OSError as e:
        return web.Response(status=500, text=str(e))
    return web.Response(text=json.dumps({'ok': True, 'agentId': agent_id, 'description': description}),
                        content_type='application/json')

def format_uptime(seconds):
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def check_service_running(name):
    """Return True if a systemd --user service is active."""
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', name],
            capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip() == 'active'
    except Exception:
        return False


def check_process_running(name):
    """Return True if a process with the given name is running."""
    if HAS_PSUTIL:
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                pname = proc.info['name'] or ''
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if name in pname or name in cmdline:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return False
    # Fallback: check /proc
    try:
        for pid in os.listdir('/proc'):
            if not pid.isdigit():
                continue
            try:
                with open(f'/proc/{pid}/comm', 'r') as f:
                    if name in f.read():
                        return True
            except OSError:
                pass
    except OSError:
        pass
    return False


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_SPEND_LIMIT = 10.0
_openai_cache = {'spend': 0.0, 'ts': 0.0}

# Approximate cost per 1M tokens by model snapshot prefix (prompt / completion)
_MODEL_PRICING = {
    'gpt-4o':        (2.50, 10.00),
    'gpt-4-turbo':   (10.00, 30.00),
    'gpt-4':         (30.00, 60.00),
    'gpt-3.5-turbo': (0.50,  1.50),
    'o1':            (15.00, 60.00),
    'o3':            (10.00, 40.00),
}

def _estimate_cost(snapshot_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated USD cost for a usage record."""
    prompt_usd_per_m, compl_usd_per_m = 2.50, 10.00  # default to gpt-4o pricing
    sid = (snapshot_id or '').lower()
    for prefix, pricing in _MODEL_PRICING.items():
        if sid.startswith(prefix):
            prompt_usd_per_m, compl_usd_per_m = pricing
            break
    return (prompt_tokens * prompt_usd_per_m + completion_tokens * compl_usd_per_m) / 1_000_000


async def fetch_openai_spend() -> float:
    """Fetch today's OpenAI spend in USD. Cached for 60 seconds."""
    now = time.time()
    if now - _openai_cache['ts'] < 60:
        return _openai_cache['spend']

    today = time.strftime('%Y-%m-%d')
    url = f'https://api.openai.com/v1/usage?date={today}'
    loop = asyncio.get_event_loop()

    def _do_fetch():
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {OPENAI_API_KEY}'})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    result = await loop.run_in_executor(None, _do_fetch)
    spend = 0.0
    if result and isinstance(result, dict):
        for record in result.get('data', []):
            snapshot_id = record.get('snapshot_id', '')
            prompt_tokens = record.get('n_context_tokens_total', 0) or 0
            completion_tokens = record.get('n_generated_tokens_total', 0) or 0
            spend += _estimate_cost(snapshot_id, prompt_tokens, completion_tokens)

    _openai_cache['spend'] = spend
    _openai_cache['ts'] = now
    return spend


async def health_handler(request):
    data = {}

    if HAS_PSUTIL:
        # CPU
        data['cpu_percent'] = psutil.cpu_percent(interval=0.1)

        # RAM
        vm = psutil.virtual_memory()
        data['ram'] = {
            'total': vm.total,
            'used': vm.used,
            'available': vm.available,
            'percent': vm.percent,
        }

        # Disk
        du = psutil.disk_usage('/')
        data['disk'] = {
            'total': du.total,
            'used': du.used,
            'free': du.free,
            'percent': du.percent,
        }

        # Swap
        sw = psutil.swap_memory()
        data['swap'] = {
            'total': sw.total,
            'used': sw.used,
            'percent': sw.percent,
        }

        # Uptime
        boot_time = psutil.boot_time()
        uptime_secs = time.time() - boot_time
        data['uptime'] = format_uptime(uptime_secs)
        data['uptime_seconds'] = int(uptime_secs)
    else:
        # Fallback: parse /proc files
        # CPU (single snapshot, not interval-based — less accurate)
        try:
            with open('/proc/stat', 'r') as f:
                line = f.readline()
            fields = list(map(int, line.split()[1:]))
            idle = fields[3]
            total = sum(fields)
            data['cpu_percent'] = round((1 - idle / total) * 100, 1)
        except Exception:
            data['cpu_percent'] = 0.0

        # RAM
        try:
            meminfo = {}
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    k, v = line.split(':')
                    meminfo[k.strip()] = int(v.split()[0]) * 1024
            total = meminfo.get('MemTotal', 0)
            avail = meminfo.get('MemAvailable', 0)
            used = total - avail
            pct = round(used / total * 100, 1) if total else 0
            data['ram'] = {'total': total, 'used': used, 'available': avail, 'percent': pct}
        except Exception:
            data['ram'] = {'total': 0, 'used': 0, 'available': 0, 'percent': 0}

        # Disk
        try:
            st = os.statvfs('/')
            total = st.f_blocks * st.f_frsize
            free = st.f_bfree * st.f_frsize
            used = total - free
            pct = round(used / total * 100, 1) if total else 0
            data['disk'] = {'total': total, 'used': used, 'free': free, 'percent': pct}
        except Exception:
            data['disk'] = {'total': 0, 'used': 0, 'free': 0, 'percent': 0}

        # Swap
        try:
            swapinfo = {}
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    k, v = line.split(':')
                    swapinfo[k.strip()] = int(v.split()[0]) * 1024
            stotal = swapinfo.get('SwapTotal', 0)
            sfree = swapinfo.get('SwapFree', 0)
            sused = stotal - sfree
            spct = round(sused / stotal * 100, 1) if stotal else 0
            data['swap'] = {'total': stotal, 'used': sused, 'percent': spct}
        except Exception:
            data['swap'] = {'total': 0, 'used': 0, 'percent': 0}

        # Uptime
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_secs = float(f.read().split()[0])
            data['uptime'] = format_uptime(uptime_secs)
            data['uptime_seconds'] = int(uptime_secs)
        except Exception:
            data['uptime'] = 'unknown'
            data['uptime_seconds'] = 0

    # Services
    data['services'] = {
        'cloudflared': check_process_running('cloudflared'),
        'terminal-server': check_service_running('terminal-server'),
    }

    # OpenAI spend
    data['openai_spend'] = await fetch_openai_spend()
    data['openai_limit'] = OPENAI_SPEND_LIMIT

    return web.Response(
        text=json.dumps(data),
        content_type='application/json',
        headers={'Cache-Control': 'no-cache'},
    )


GRAPHITI_GRAPHS = ['discord', 'infrastructure', 'discord-history', 'discord_history']
FALKORDB_CONTAINER = 'docker-falkordb-1'

# Entity classifier — module-level constants so they're built once, not per-request.
_ENTITY_PEOPLE = {
    'jaboostin', 'justin', 'koole', 'graeme', 'centronias', 'bernie', 'biden',
    'trump', 'musk', 'elon', 'elon musk', 'donald trump', 'joe biden',
    'bernie sanders', 'harris', 'kamala', 'kamala harris', 'obama', 'pelosi',
    'aoc', 'ocasio-cortez', 'zelensky', 'putin', 'xi jinping', 'xi', 'pope',
    'pope francis', 'zuckerberg', 'mark zuckerberg', 'sam altman', 'altman',
    'bezos', 'jeff bezos', 'cook', 'tim cook', 'sundar pichai',
}
_ENTITY_PLACES = {
    'america', 'usa', 'us', 'united states', 'new york', 'texas', 'california',
    'florida', 'ohio', 'michigan', 'pennsylvania', 'georgia', 'arizona',
    'washington', 'dc', 'washington dc', 'canada', 'mexico', 'uk',
    'united kingdom', 'europe', 'russia', 'china', 'ukraine', 'israel',
    'gaza', 'taiwan', 'north korea', 'iran', 'iraq', 'afghanistan',
    'san francisco', 'los angeles', 'chicago', 'boston', 'seattle',
    'new jersey', 'brooklyn', 'manhattan', 'silicon valley',
}
_ENTITY_COMPANIES = {
    'openai', 'anthropic', 'google', 'microsoft', 'meta', 'apple', 'amazon',
    'tesla', 'spacex', 'twitter', 'x', 'discord', 'reddit', 'facebook',
    'instagram', 'tiktok', 'youtube', 'netflix', 'uber', 'lyft',
    'nvidia', 'amd', 'intel', 'qualcomm', 'arm', 'broadcom',
    'palantir', 'oracle', 'ibm', 'salesforce', 'shopify', 'stripe',
    'github', 'gitlab', 'atlassian', 'slack', 'zoom', 'twitch',
    'bytedance', 'baidu', 'alibaba', 'tencent', 'huawei',
    'nyt', 'new york times', 'cnn', 'fox', 'fox news', 'msnbc',
    'bbc', 'reuters', 'ap', 'associated press', 'washington post',
}
_ENTITY_TECH = {
    'ai', 'ml', 'llm', 'gpt', 'chatgpt', 'grok', 'gemini', 'claude',
    'llama', 'mistral', 'deepseek', 'copilot', 'dall-e', 'midjourney',
    'stable diffusion', 'neural network', 'machine learning',
    'python', 'javascript', 'rust', 'golang', 'typescript',
    'linux', 'windows', 'macos', 'android', 'ios',
    'bitcoin', 'ethereum', 'crypto', 'nft', 'blockchain',
    'docker', 'kubernetes', 'aws', 'gcp', 'azure', 'cloud',
    'internet', 'web', 'api', 'github', 'open source',
}
_ENTITY_POLITICS = {
    'congress', 'senate', 'house', 'democrat', 'republican', 'gop',
    'election', 'vote', 'voting', 'ballot', 'primary', 'campaign',
    'white house', 'president', 'vice president', 'secretary',
    'supreme court', 'court', 'roe', 'abortion', 'immigration',
    'nato', 'un', 'united nations', 'eu', 'european union',
    'tariff', 'tariffs', 'trade war', 'sanctions', 'doge',
    'maga', 'woke', 'progressive', 'conservative', 'liberal',
    'left', 'right', 'socialism', 'capitalism', 'populism',
    'fbi', 'cia', 'nsa', 'doj', 'fcc', 'sec', 'fed', 'federal reserve',
}
_ENTITY_SUMMARY_KEYWORDS = {
    'Person':   ['person', 'user', 'developer', 'engineer', 'founder', 'ceo',
                 'politician', 'activist', 'journalist', 'researcher', 'scientist',
                 'actor', 'comedian', 'artist', 'streamer', 'youtuber'],
    'Place':    ['country', 'city', 'state', 'region', 'location', 'territory',
                 'nation', 'continent', 'island', 'coast', 'district', 'county'],
    'Company':  ['company', 'corporation', 'startup', 'firm', 'organization',
                 'platform', 'service', 'media', 'publication', 'outlet'],
    'Tech':     ['technology', 'software', 'hardware', 'model', 'framework',
                 'language', 'protocol', 'algorithm', 'database', 'system',
                 'network', 'ai model', 'tool', 'library', 'cryptocurrency'],
    'Politics': ['policy', 'political', 'legislation', 'bill', 'law', 'party',
                 'movement', 'government', 'administration', 'department',
                 'agency', 'bureau', 'committee', 'ideology'],
}
_DISCORD_USER_ALIASES = {
    'justin':              'jaboostin',
    'discord user':        'discord',
    'americans':           'america',
    'american':            'america',
    'new york city':       'new york',
    'new yorkers':         'new york',
    'openai millionaires': 'openai',
    'genai':               'ai',
    'grok ai chatbot':     'grok',
    'biden administration':'biden',
    'bernie sanders':      'bernie',
    'bernie bros':         'bernie',
}


def _classify_entity(name: str, summary: str) -> str:
    n = (name or '').strip().lower()
    s = (summary or '').lower()
    if n in _ENTITY_PEOPLE:    return 'Person'
    if n in _ENTITY_PLACES:    return 'Place'
    if n in _ENTITY_COMPANIES: return 'Company'
    if n in _ENTITY_TECH:      return 'Tech'
    if n in _ENTITY_POLITICS:  return 'Politics'
    for group, keywords in _ENTITY_SUMMARY_KEYWORDS.items():
        if any(kw in s for kw in keywords):
            return group
    return 'Concept'


def _user_dedup_key(label: str) -> str:
    k = (label or '').strip().lower()
    return _DISCORD_USER_ALIASES.get(k, k)


def _run_falkordb_query(graph: str, query: str) -> list[str]:
    """Run a Cypher query against FalkorDB via docker exec redis-cli.

    Returns a flat list of all non-blank, non-metadata lines from the output.
    The first N lines are column headers; callers use _parse_falkordb_table to
    strip headers and split into rows.
    """
    try:
        result = subprocess.run(
            ['docker', 'exec', FALKORDB_CONTAINER,
             'redis-cli', '-p', '6379', 'GRAPH.QUERY', graph, query],
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.splitlines()
    except Exception:
        return []

    all_data = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('Cached execution') or stripped.startswith('Query internal'):
            break
        if stripped == '':
            continue
        all_data.append(stripped)

    return all_data


def _parse_falkordb_table(raw_lines: list[str], num_cols: int) -> list[list[str]]:
    """Given flat list of values from redis-cli GRAPH.QUERY, split into rows."""
    # Skip the header row (first num_cols lines)
    data = raw_lines[num_cols:]
    rows = []
    for i in range(0, len(data), num_cols):
        row = data[i:i + num_cols]
        if len(row) == num_cols:
            rows.append(row)
    return rows


def _query_graph(graph_name: str):
    """Query a FalkorDB graph for entity nodes and edges (uses Python library for multi-line safety)."""
    r = _fdb.FalkorDB(host='localhost', port=6379)
    g = r.select_graph(graph_name)
    node_results, edge_results = [], []
    try:
        res = g.query(
            "MATCH (n) WHERE NOT 'Episodic' IN labels(n) "
            "RETURN n.uuid, n.name, labels(n), n.summary"
        )
        node_results = res.result_set
    except Exception as exc:
        print(f'[graph_data] node query failed for {graph_name!r}: {exc}')
    try:
        res = g.query(
            "MATCH (a)-[r:RELATES_TO]->(b) "
            "RETURN a.uuid, a.name, r.name, r.fact, b.uuid, b.name"
        )
        edge_results = res.result_set
    except Exception as exc:
        print(f'[graph_data] edge query failed for {graph_name!r}: {exc}')
    return node_results, edge_results


async def graph_data_handler(request):
    """Query all Graphiti FalkorDB graphs and return nodes + edges for vis.js."""
    loop = asyncio.get_event_loop()

    nodes_map = {}   # uuid -> {id, label, group, title}
    edges_list = []  # {from, to, label, title}
    edge_set = set()

    all_results = await asyncio.gather(
        *[loop.run_in_executor(None, _query_graph, graph) for graph in GRAPHITI_GRAPHS]
    )
    for graph, (node_results, edge_results) in zip(GRAPHITI_GRAPHS, all_results):

        for row in node_results:
            if len(row) < 4:
                continue
            uuid_val, name_val, labels_val, summary_val = row
            if not uuid_val:
                continue
            # labels_val is a list like ['Entity', 'Organization']
            if isinstance(labels_val, list):
                parts = labels_val
            else:
                parts = [p.strip() for p in str(labels_val).strip('[]').split(',')]
            new_groups = [p for p in parts if p not in ('Entity', '')]
            summary_str = str(summary_val) if summary_val else ''
            if uuid_val not in nodes_map:
                nodes_map[uuid_val] = {
                    'id': uuid_val,
                    'label': name_val,
                    'summary': summary_str,
                    'groups': new_groups,
                    '_graphs': [graph],
                }
            else:
                existing = nodes_map[uuid_val]
                for g in new_groups:
                    if g not in existing['groups']:
                        existing['groups'].append(g)
                if graph not in existing['_graphs']:
                    existing['_graphs'].append(graph)

        for row in edge_results:
            if len(row) < 6:
                continue
            src_uuid, _src_name, rel_name, fact, dst_uuid, _dst_name = row
            if not src_uuid or not dst_uuid:
                continue
            key = (src_uuid, dst_uuid, rel_name)
            if key in edge_set:
                continue
            edge_set.add(key)
            edges_list.append({
                'from': src_uuid,
                'to': dst_uuid,
                'label': rel_name,
                'title': fact or rel_name,
            })

    name_to_canonical = {}
    uuid_remap = {}
    for uuid_val, node in list(nodes_map.items()):
        key = _user_dedup_key(node.get('label') or '')
        if not key:
            continue
        if key not in name_to_canonical:
            name_to_canonical[key] = uuid_val
        else:
            canonical_uuid = name_to_canonical[key]
            uuid_remap[uuid_val] = canonical_uuid
            del nodes_map[uuid_val]

    # Finalise vis.js fields: classify entity type and build title tooltip.
    for node in nodes_map.values():
        node.pop('groups', None)
        graphs = node.pop('_graphs', [])
        summary = node.pop('summary', '')
        vis_group = _classify_entity(node.get('label', ''), summary)
        node['group'] = vis_group
        graphs_str = ', '.join(graphs)
        node['title'] = f"{node['label']} [{vis_group}] ({graphs_str})"

    # Remap edge endpoints and deduplicate.
    seen_edges = set()
    deduped_edges = []
    for edge in edges_list:
        src = uuid_remap.get(edge['from'], edge['from'])
        dst = uuid_remap.get(edge['to'], edge['to'])
        if src == dst:
            continue
        key = (src, dst, edge.get('label'))
        if key not in seen_edges:
            seen_edges.add(key)
            deduped_edges.append({**edge, 'from': src, 'to': dst})

    payload = {
        'nodes': list(nodes_map.values()),
        'edges': deduped_edges,
    }
    return web.Response(
        text=json.dumps(payload),
        content_type='application/json',
        headers={'Cache-Control': 'no-cache'},
    )


JSONL_PATH = "/home/clungus/.claude/projects/-home-clungus-work/bb9407c6-0d39-400c-af71-7c6765df2c69.jsonl"
CLAUDE_PRICING = {
    'input':       3.00 / 1_000_000,
    'output':     15.00 / 1_000_000,
    'cache_read':  0.30 / 1_000_000,
    'cache_write': 3.75 / 1_000_000,
}
_cost_cache = {'data': None, 'ts': 0.0}


def _parse_cost_data():
    totals = {
        'input': 0,
        'output': 0,
        'cache_read': 0,
        'cache_write': 0,
    }
    session_start = None
    now = time.time()
    one_hour_ago = now - 3600
    recent_tokens = 0

    try:
        with open(JSONL_PATH, 'r', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get('type') != 'assistant':
                    continue
                msg = obj.get('message', {})
                if not isinstance(msg, dict):
                    continue
                usage = msg.get('usage')
                if not usage or not isinstance(usage, dict):
                    continue

                ts_str = obj.get('timestamp', '')
                ts = None
                if ts_str:
                    try:
                        # Parse ISO timestamp with Z suffix
                        ts_clean = ts_str.replace('Z', '+00:00')
                        import datetime
                        dt = datetime.datetime.fromisoformat(ts_clean)
                        ts = dt.timestamp()
                    except Exception:
                        pass

                if session_start is None and ts is not None:
                    session_start = ts_str

                inp = usage.get('input_tokens', 0) or 0
                out = usage.get('output_tokens', 0) or 0
                cr = usage.get('cache_read_input_tokens', 0) or 0
                cw = usage.get('cache_creation_input_tokens', 0) or 0

                totals['input'] += inp
                totals['output'] += out
                totals['cache_read'] += cr
                totals['cache_write'] += cw

                if ts is not None and ts >= one_hour_ago:
                    recent_tokens += inp + out + cr + cw

    except FileNotFoundError:
        pass

    cost_input = totals['input'] * CLAUDE_PRICING['input']
    cost_output = totals['output'] * CLAUDE_PRICING['output']
    cost_cr = totals['cache_read'] * CLAUDE_PRICING['cache_read']
    cost_cw = totals['cache_write'] * CLAUDE_PRICING['cache_write']
    total_cost = cost_input + cost_output + cost_cr + cost_cw

    elapsed_hours = 0.0
    if session_start:
        try:
            import datetime
            dt = datetime.datetime.fromisoformat(session_start.replace('Z', '+00:00'))
            elapsed_hours = (now - dt.timestamp()) / 3600
        except Exception:
            pass

    tokens_per_hour = 0.0
    cost_per_hour = 0.0
    if elapsed_hours > 0:
        total_tokens = totals['input'] + totals['output'] + totals['cache_read'] + totals['cache_write']
        tokens_per_hour = total_tokens / elapsed_hours
        cost_per_hour = total_cost / elapsed_hours

    return {
        'session_start': session_start,
        'elapsed_hours': round(elapsed_hours, 3),
        'total_input_tokens': totals['input'],
        'total_output_tokens': totals['output'],
        'total_cache_read_tokens': totals['cache_read'],
        'total_cache_write_tokens': totals['cache_write'],
        'total_cost_usd': round(total_cost, 6),
        'cost_breakdown': {
            'input': round(cost_input, 6),
            'output': round(cost_output, 6),
            'cache_read': round(cost_cr, 6),
            'cache_write': round(cost_cw, 6),
        },
        'tokens_per_hour': round(tokens_per_hour, 1),
        'cost_per_hour': round(cost_per_hour, 6),
        'tokens_last_hour': recent_tokens,
    }


async def cost_data_handler(request):
    now = time.time()
    if now - _cost_cache['ts'] < 60 and _cost_cache['data'] is not None:
        data = _cost_cache['data']
    else:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _parse_cost_data)
        data['openai_spend_usd'] = await fetch_openai_spend()
        _cost_cache['data'] = data
        _cost_cache['ts'] = now

    return web.Response(
        text=json.dumps(data),
        content_type='application/json',
        headers={
            'Cache-Control': 'no-cache',
            'Access-Control-Allow-Origin': '*',
        },
    )


RESTART_PASSWORD = "shotgun"

async def restart_bot_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text='Invalid JSON')
    if body.get('password') != RESTART_PASSWORD:
        return web.Response(
            status=403,
            text=json.dumps({'ok': False, 'error': 'wrong password'}),
            content_type='application/json',
        )
    try:
        subprocess.run(
            ['systemctl', '--user', 'restart', 'claude-bot'],
            env={**os.environ, 'XDG_RUNTIME_DIR': '/run/user/1001'},
            check=True,
            timeout=10,
        )
    except Exception as e:
        return web.Response(
            text=json.dumps({'ok': False, 'error': str(e)}),
            content_type='application/json',
        )
    return web.Response(text=json.dumps({'ok': True}), content_type='application/json')


SERVICES = [
    "claude-bot", "terminal-server", "website", "1998",
    "temporal", "temporal-worker", "cloudflared", "discord-bridge"
]

async def system_status_handler(request):
    nodes = []
    for svc in SERVICES:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", svc],
            capture_output=True, text=True,
            env={**os.environ, 'XDG_RUNTIME_DIR': '/run/user/1001'},
            timeout=5,
        )
        status = result.stdout.strip()  # "active", "inactive", "failed"
        nodes.append({"id": svc, "status": status})

    # Also check Docker containers
    try:
        docker = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Status}}"],
            capture_output=True, text=True, timeout=10
        )
        for line in docker.stdout.strip().split('\n'):
            if '|' in line:
                name, status = line.split('|', 1)
                nodes.append({
                    "id": name.strip(),
                    "status": "active" if "Up" in status else "down",
                    "type": "docker"
                })
    except Exception:
        pass

    # Define edges (relationships/dependencies)
    edges = [
        {"from": "claude-bot", "to": "terminal-server", "label": "streams to"},
        {"from": "claude-bot", "to": "cloudflared", "label": "via"},
        {"from": "terminal-server", "to": "docker-graphiti-mcp-1", "label": "queries"},
        {"from": "docker-graphiti-mcp-1", "to": "docker-falkordb-1", "label": "stores in"},
        {"from": "temporal-worker", "to": "temporal", "label": "connects to"},
        {"from": "temporal-worker", "to": "discord-bridge", "label": "posts via"},
        {"from": "cloudflared", "to": "terminal-server", "label": "terminal.clung.us"},
        {"from": "cloudflared", "to": "website", "label": "hello.clung.us"},
        {"from": "cloudflared", "to": "temporal", "label": "temporal.clung.us"},
    ]

    return web.Response(
        text=json.dumps({"nodes": nodes, "edges": edges}),
        content_type='application/json',
        headers={'Cache-Control': 'no-cache'},
    )


async def topology_page_handler(request):
    topology_html_path = os.path.join(os.path.dirname(__file__), 'topology.html')
    with open(topology_html_path, 'r') as f:
        content = f.read()
    return web.Response(text=content, content_type='text/html')


async def gamecube_sounds_handler(request):
    path = os.path.join(os.path.dirname(__file__), 'gamecube-sounds.js')
    with open(path) as f:
        return web.Response(text=f.read(), content_type='application/javascript')


async def ingestion_status_handler(request):
    """Return discord_history ingestion progress stats from FalkorDB."""
    TOTAL_EPISODES = 141
    try:
        r = _fdb.FalkorDB(host='localhost', port=6379)
        g = r.select_graph('discord_history')
        episodes = g.query("MATCH (e:Episodic) RETURN count(e) as cnt").result_set[0][0]
        nodes    = g.query("MATCH (n:Entity) RETURN count(n) as cnt").result_set[0][0]
        edges    = g.query("MATCH ()-[r]->() RETURN count(r) as cnt").result_set[0][0]
    except Exception as exc:
        return web.Response(
            text=json.dumps({'error': str(exc)}),
            content_type='application/json',
            status=503,
        )
    try:
        result = subprocess.run(
            'ps aux | grep scrape_discord | grep -v grep | wc -l',
            shell=True, capture_output=True, text=True, timeout=5,
        )
        workers_running = int(result.stdout.strip())
    except Exception:
        workers_running = 0
    pct = round(episodes / TOTAL_EPISODES * 100, 1) if TOTAL_EPISODES else 0
    return web.Response(
        text=json.dumps({
            'episodes': episodes,
            'total_episodes': TOTAL_EPISODES,
            'entities': nodes,
            'edges': edges,
            'workers_running': workers_running,
            'pct': pct,
        }),
        content_type='application/json',
    )


app = web.Application(middlewares=[auth_middleware])
app.router.add_get('/login', login_handler)
app.router.add_post('/login', login_handler)
app.router.add_get('/', index)
app.router.add_get('/health', health_handler)
app.router.add_get('/graph-data', graph_data_handler)
app.router.add_get('/graph', graph_page_handler)
app.router.add_get('/ingestion-status', ingestion_status_handler)
app.router.add_get('/ws', websocket_handler)
app.router.add_get('/tasks', tasks_handler)
app.router.add_get('/task-output/{agentId}', task_output_handler)
app.router.add_post('/meta/{agentId}', meta_handler)
app.router.add_post('/restart-bot', restart_bot_handler)
app.router.add_get('/cost-data', cost_data_handler)
app.router.add_get('/system-status', system_status_handler)
app.router.add_get('/topology', topology_page_handler)
app.router.add_get('/gamecube-sounds.js', gamecube_sounds_handler)

_JSONL_DIR = '/home/clungus/.claude/projects/-mnt-data'


def _requester_from_jsonl(task_ctime: float) -> str:
    """Scan session JSONLs for the most recent Discord message sent before task_ctime."""
    jsonl_files = sorted(glob.glob(f'{_JSONL_DIR}/*.jsonl'), key=os.path.getmtime, reverse=True)
    best_user, best_ts = '', 0.0
    for jsonl_path in jsonl_files[:2]:
        try:
            content = open(jsonl_path).read()
        except OSError:
            continue
        # Discord channel tags are stored char-by-char in JSONL; in the raw file they
        # appear with escaped quotes: user=\\"username\\" ... ts=\\"2026-...Z\\"
        for m in re.finditer(
            r'user=\\"([^\\"]+)\\"[^>]*ts=\\"(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\\"',
            content
        ):
            try:
                ts = datetime.fromisoformat(m.group(2).replace('Z', '+00:00')).timestamp()
            except ValueError:
                continue
            if ts < task_ctime and ts > best_ts:
                best_ts, best_user = ts, m.group(1)
    return best_user


async def _auto_meta_loop():
    """Background task: auto-create .meta.json for tasks that lack a requester."""
    await asyncio.sleep(10)  # Let the server start first
    while True:
        try:
            for fname in os.listdir(TASKS_DIR):
                if not fname.endswith('.output'):
                    continue
                agent_id = fname[:-7]
                meta_path = os.path.join(TASKS_DIR, agent_id + '.meta.json')
                if os.path.exists(meta_path):
                    try:
                        data = json.load(open(meta_path))
                        if data.get('requester'):
                            continue  # Already has a requester
                    except (OSError, json.JSONDecodeError):
                        pass
                ctime = os.path.getctime(os.path.join(TASKS_DIR, fname))
                requester = _requester_from_jsonl(ctime)
                if not requester:
                    continue
                existing_desc = ''
                try:
                    existing_desc = json.load(open(meta_path)).get('description', '')
                except (OSError, json.JSONDecodeError):
                    pass
                with open(meta_path, 'w') as f:
                    json.dump({'description': existing_desc, 'requester': requester}, f)
        except Exception as exc:
            print(f'[auto_meta] error: {exc}')
        await asyncio.sleep(30)


async def _start_background_tasks(app):
    app['auto_meta'] = asyncio.ensure_future(_auto_meta_loop())


async def _stop_background_tasks(app):
    app['auto_meta'].cancel()
    await asyncio.gather(app['auto_meta'], return_exceptions=True)


app.on_startup.append(_start_background_tasks)
app.on_cleanup.append(_stop_background_tasks)

if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=7682)
