const express   = require('express');
const basicAuth = require('express-basic-auth');
const { spawn, exec } = require('child_process');
const http = require('http');
const path = require('path');

const app = express();

// ── Basic auth (set LAUNCHER_USER / LAUNCHER_PASS env vars in production) ────
const LAUNCHER_USER = process.env.LAUNCHER_USER || 'admin';
const LAUNCHER_PASS = process.env.LAUNCHER_PASS || 'TradeZen@local';

app.use(basicAuth({
  users: { [LAUNCHER_USER]: LAUNCHER_PASS },
  challenge: true,
  realm: 'TradeZen Launcher',
}));

app.use(express.json());

// ── Platform ─────────────────────────────────────────────────────────────────
const IS_WIN = process.platform === 'win32';
const PYTHON  = IS_WIN ? 'python' : 'python3';

const BASE_DIR   = __dirname;
const PYTHON_DIR = path.join(BASE_DIR, 'ai_engine');

const PORTS  = { python: 8000, node: 3000 };
const LAUNCH = process.env.LAUNCHER_PORT || 9999;

let processes = { python: null, node: null };
const logs    = { python: [], node: [] };
const MAX_LOG = 300;

function ts() {
  return new Date().toLocaleTimeString('en-IN', { hour12: false });
}

function appendLog(srv, line) {
  logs[srv].push(`[${ts()}] ${line}`);
  if (logs[srv].length > MAX_LOG) logs[srv].shift();
}

// ── Port check (cross-platform: plain HTTP probe) ─────────────────────────────
function checkPort(port) {
  return new Promise((resolve) => {
    const req = http.get({ hostname: '127.0.0.1', port, path: '/', timeout: 1200 }, () => {
      resolve(true);
      req.destroy();
    });
    req.on('error',   () => resolve(false));
    req.on('timeout', () => { resolve(false); req.destroy(); });
  });
}

// ── Find PID by port ──────────────────────────────────────────────────────────
function getPidByPort(port) {
  return new Promise((resolve) => {
    if (IS_WIN) {
      exec(`netstat -ano | findstr :${port}`, (err, stdout) => {
        if (err || !stdout) return resolve(null);
        for (const line of stdout.trim().split('\n')) {
          const t = line.trim();
          if (t.includes(`0.0.0.0:${port} `) || t.includes(`127.0.0.1:${port} `) || t.includes(`[::]:${port} `)) {
            const parts = t.split(/\s+/);
            const pid = parseInt(parts[parts.length - 1]);
            if (!isNaN(pid) && pid > 0) return resolve(pid);
          }
        }
        resolve(null);
      });
    } else {
      // lsof -ti outputs just the PID(s), one per line
      exec(`lsof -ti :${port}`, (err, stdout) => {
        if (err || !stdout) return resolve(null);
        const pid = parseInt(stdout.trim().split('\n')[0]);
        resolve(isNaN(pid) ? null : pid);
      });
    }
  });
}

// ── Kill PID ──────────────────────────────────────────────────────────────────
function killPid(pid) {
  const cmd = IS_WIN ? `taskkill /PID ${pid} /F /T` : `kill -9 ${pid}`;
  return new Promise((resolve) => exec(cmd, () => resolve()));
}

// ── Start process ─────────────────────────────────────────────────────────────
function startProcess(srv) {
  if (processes[srv]) {
    appendLog(srv, 'Already running (tracked process exists).');
    return;
  }
  appendLog(srv, `Starting ${srv} server…`);

  const opts =
    srv === 'python'
      ? { cmd: PYTHON, args: ['-X', 'utf8', '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'], cwd: PYTHON_DIR }
      : { cmd: 'node', args: ['server.js'], cwd: BASE_DIR };

  const proc = spawn(opts.cmd, opts.args, {
    cwd: opts.cwd,
    shell: true,
    env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', NO_COLOR: '1' },
  });
  processes[srv] = proc;

  const onData = (d) => d.toString().split('\n').filter(Boolean).forEach((l) => appendLog(srv, l));
  proc.stdout.on('data', onData);
  proc.stderr.on('data', onData);
  proc.on('exit', (code) => {
    appendLog(srv, `Process exited (code ${code ?? '?'})`);
    processes[srv] = null;
  });
}

// ── Stop process ──────────────────────────────────────────────────────────────
async function stopProcess(srv) {
  const proc = processes[srv];
  if (proc) {
    try { proc.kill('SIGTERM'); } catch (_) {}
    processes[srv] = null;
  }
  const pid = await getPidByPort(PORTS[srv]);
  if (pid) {
    await killPid(pid);
    appendLog(srv, `Killed external process PID ${pid}.`);
  }
  appendLog(srv, 'Server stopped.');
}

async function waitUntilUp(port, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await checkPort(port)) return true;
    await new Promise((r) => setTimeout(r, 1500));
  }
  return false;
}

// ── API ───────────────────────────────────────────────────────────────────────

app.get('/api/status', async (req, res) => {
  const [python, node] = await Promise.all([checkPort(PORTS.python), checkPort(PORTS.node)]);
  res.json({ python, node });
});

app.get('/api/logs/:srv', (req, res) => {
  const { srv } = req.params;
  if (!logs[srv]) return res.status(400).json({ error: 'unknown server' });
  res.json({ logs: logs[srv] });
});

app.post('/api/start/python', (req, res) => { startProcess('python'); res.json({ ok: true }); });
app.post('/api/start/node',   (req, res) => { startProcess('node');   res.json({ ok: true }); });

app.post('/api/start/all', (req, res) => {
  res.json({ ok: true });
  (async () => {
    startProcess('python');
    appendLog('node', 'Waiting for Python to be ready before starting Node…');
    const ready = await waitUntilUp(PORTS.python);
    if (ready) {
      appendLog('node', 'Python is up. Starting Node now.');
      startProcess('node');
    } else {
      appendLog('node', 'Python did not come up in 30 s. Node not started.');
    }
  })();
});

app.post('/api/stop/python', async (req, res) => { await stopProcess('python'); res.json({ ok: true }); });
app.post('/api/stop/node',   async (req, res) => { await stopProcess('node');   res.json({ ok: true }); });

app.post('/api/stop/all', async (req, res) => {
  await stopProcess('node');
  await stopProcess('python');
  res.json({ ok: true });
});

app.post('/api/restart/python', async (req, res) => {
  res.json({ ok: true });
  await stopProcess('python');
  await new Promise((r) => setTimeout(r, 1500));
  startProcess('python');
});

app.post('/api/restart/node', async (req, res) => {
  res.json({ ok: true });
  await stopProcess('node');
  await new Promise((r) => setTimeout(r, 1500));
  startProcess('node');
});

// ── Dashboard ─────────────────────────────────────────────────────────────────

app.get('/', (req, res) => res.sendFile(path.join(BASE_DIR, 'public', 'launcher.html')));

app.listen(LAUNCH, '127.0.0.1', () =>
  console.log(`TradeZen Launcher → http://127.0.0.1:${LAUNCH}  (user: ${LAUNCHER_USER})`)
);
