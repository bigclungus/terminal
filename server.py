#!/usr/bin/env python3
"""
Live terminal stream server — streams /tmp/screenlog.txt to websocket clients,
served alongside an xterm.js HTML page.
"""
import asyncio
import json
import os
import subprocess
import time
import urllib.request
from aiohttp import web

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

LOGFILE = "/tmp/screenlog.txt"
TASKS_DIR = "/tmp/claude-1001/-home-clungus-work/bb9407c6-0d39-400c-af71-7c6765df2c69/tasks"

HTML = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="icon" type="image/png" href="https://hello.clung.us/favicon.png">
  <title>BigClungus Live Terminal</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css" />
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
  </style>
</head>
<body>
  <div id="header">
    <span>&#x1F916; BigClungus Live Session</span>
    <span id="status" class="disconnected">&#x25CF; disconnected</span>
    <a id="graph-link" href="/graph" target="_blank">&#x238B; Knowledge Graph</a>
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
        const desc = task.description ? `<div class="task-description">${task.description}</div>` : '';
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

        tasks.append({
            'id': agent_id,
            'status': status,
            'summary': summary,
            'description': description,
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
    meta_path = os.path.join(TASKS_DIR, agent_id + '.meta.json')
    try:
        os.makedirs(TASKS_DIR, exist_ok=True)
        with open(meta_path, 'w') as f:
            json.dump({'description': description}, f)
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


GRAPHITI_GRAPHS = ['discord', 'infrastructure', 'discord-history']
FALKORDB_CONTAINER = 'graphiti-mcp'


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


async def graph_data_handler(request):
    """Query all Graphiti FalkorDB graphs and return nodes + edges for vis.js."""
    loop = asyncio.get_event_loop()

    nodes_map = {}   # uuid -> {id, label, group, title}
    edges_list = []  # {from, to, label, title}
    edge_set = set()

    for graph in GRAPHITI_GRAPHS:
        # --- Nodes (Entity only, skip Episodic) ---
        node_raw = await loop.run_in_executor(
            None,
            _run_falkordb_query,
            graph,
            "MATCH (n) WHERE NOT 'Episodic' IN labels(n) RETURN n.uuid, n.name, labels(n)"
        )
        node_rows = _parse_falkordb_table(node_raw, 3)
        for row in node_rows:
            uuid_val, name_val, labels_val = row
            if not uuid_val:
                continue
            # labels_val looks like "[Entity, Organization]"
            clean = labels_val.strip('[]')
            parts = [p.strip() for p in clean.split(',')]
            new_groups = [p for p in parts if p not in ('Entity', '')]
            if uuid_val not in nodes_map:
                nodes_map[uuid_val] = {
                    'id': uuid_val,
                    'label': name_val,
                    'groups': new_groups,
                    '_graphs': [graph],
                }
            else:
                # Same UUID seen in another graph — union the type labels.
                existing = nodes_map[uuid_val]
                for g in new_groups:
                    if g not in existing['groups']:
                        existing['groups'].append(g)
                if graph not in existing['_graphs']:
                    existing['_graphs'].append(graph)

        # --- Edges (RELATES_TO relationships) ---
        edge_raw = await loop.run_in_executor(
            None,
            _run_falkordb_query,
            graph,
            "MATCH (a)-[r:RELATES_TO]->(b) RETURN a.uuid, a.name, r.name, r.fact, b.uuid, b.name"
        )
        edge_rows = _parse_falkordb_table(edge_raw, 6)
        for row in edge_rows:
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

    # Second deduplication pass: merge nodes with the same name (case-insensitive).
    # Different graph groups assign different UUIDs to the same real-world entity,
    # so we keep the first UUID seen as canonical and remap edges to it.
    name_to_canonical = {}   # normalised name -> canonical uuid
    uuid_remap = {}          # duplicate uuid -> canonical uuid
    for uuid_val, node in list(nodes_map.items()):
        key = (node.get('label') or '').strip().lower()
        if not key:
            continue
        if key not in name_to_canonical:
            name_to_canonical[key] = uuid_val
        else:
            canonical_uuid = name_to_canonical[key]
            canonical_node = nodes_map[canonical_uuid]
            # Union the groups and source-graph lists from the duplicate.
            for g in node.get('groups', []):
                if g not in canonical_node['groups']:
                    canonical_node['groups'].append(g)
            for gr in node.get('_graphs', []):
                if gr not in canonical_node['_graphs']:
                    canonical_node['_graphs'].append(gr)
            uuid_remap[uuid_val] = canonical_uuid
            del nodes_map[uuid_val]

    # Finalise vis.js fields: pick best group label and build title tooltip.
    for node in nodes_map.values():
        groups = node.pop('groups', [])
        graphs = node.pop('_graphs', [])
        # Pick most specific type for vis.js colouring.
        specific = [g for g in groups if g not in ('Organization', 'Entity')]
        if specific:
            vis_group = specific[0]
        elif groups:
            vis_group = groups[0]
        else:
            vis_group = 'Entity'
        node['group'] = vis_group
        node['groups'] = groups  # keep for tooltip / client use
        graphs_str = ', '.join(graphs)
        groups_str = ', '.join(groups) if groups else 'Entity'
        node['title'] = f"{node['label']} [{groups_str}] ({graphs_str})"

    # Remap edge endpoints and drop any self-loops that result from the merge.
    remapped_edges = []
    remapped_edge_set = set()
    for edge in edges_list:
        src = uuid_remap.get(edge['from'], edge['from'])
        dst = uuid_remap.get(edge['to'], edge['to'])
        if src == dst:
            continue
        key = (src, dst, edge.get('label'))
        if key in remapped_edge_set:
            continue
        remapped_edge_set.add(key)
        remapped_edges.append({**edge, 'from': src, 'to': dst})

    payload = {
        'nodes': list(nodes_map.values()),
        'edges': remapped_edges,
        '_dedup_removed': len(uuid_remap),
    }
    return web.Response(
        text=json.dumps(payload),
        content_type='application/json',
        headers={'Cache-Control': 'no-cache'},
    )


app = web.Application()
app.router.add_get('/', index)
app.router.add_get('/health', health_handler)
app.router.add_get('/graph-data', graph_data_handler)
app.router.add_get('/graph', graph_page_handler)
app.router.add_get('/ws', websocket_handler)
app.router.add_get('/tasks', tasks_handler)
app.router.add_get('/task-output/{agentId}', task_output_handler)
app.router.add_post('/meta/{agentId}', meta_handler)

if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=7682)
