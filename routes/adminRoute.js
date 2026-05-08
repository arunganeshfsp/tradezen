const express = require('express');
const { exec } = require('child_process');
const router  = express.Router();

// ── Token auth ────────────────────────────────────────────────────────────────
function auth(req, res, next) {
  const token = process.env.ADMIN_TOKEN;
  if (!token) return res.status(503).json({ error: 'ADMIN_TOKEN not set on server' });
  const sent = (req.headers['x-admin-token'] || '').trim();
  if (sent !== token) return res.status(401).json({ error: 'Invalid token' });
  next();
}

// ── PM2 process names ─────────────────────────────────────────────────────────
const PM2_NAME = {
  python: 'tradezen-python',
  node:   'tradezen-node',
};

// Ensure /usr/local/bin is in PATH so pm2 is found when Node exec's a shell command
const EXEC_ENV = { ...process.env, PATH: `/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ''}` };

function run(cmd) {
  return new Promise((resolve) => {
    exec(cmd, { timeout: 15000, env: EXEC_ENV }, (err, stdout, stderr) => {
      resolve({ ok: !err, out: (stdout || '') + (stderr || ''), err: err?.message });
    });
  });
}

// ── Status (pm2 jlist) ────────────────────────────────────────────────────────
router.get('/status', auth, async (req, res) => {
  const { ok, out } = await run('pm2 jlist');
  if (!ok) return res.status(500).json({ error: 'pm2 jlist failed', detail: out });
  try {
    const list   = JSON.parse(out);
    const status = {};
    for (const [key, name] of Object.entries(PM2_NAME)) {
      const proc = list.find((p) => p.name === name);
      status[key] = proc
        ? { online: proc.pm2_env?.status === 'online', status: proc.pm2_env?.status, pid: proc.pid }
        : { online: false, status: 'not found', pid: null };
    }
    res.json(status);
  } catch {
    res.status(500).json({ error: 'Could not parse pm2 output' });
  }
});

// ── Logs ──────────────────────────────────────────────────────────────────────
router.get('/logs/:srv', auth, async (req, res) => {
  const name = PM2_NAME[req.params.srv];
  if (!name) return res.status(400).json({ error: 'unknown server' });
  const { out } = await run(`pm2 logs ${name} --nostream --lines 80 --no-color`);
  const lines = out.split('\n').filter(Boolean).slice(-80);
  res.json({ logs: lines });
});

// ── Start / Stop / Restart ────────────────────────────────────────────────────
router.post('/start/:srv', auth, async (req, res) => {
  const name = PM2_NAME[req.params.srv];
  if (!name) return res.status(400).json({ error: 'unknown server' });
  const { ok, out } = await run(`pm2 start ${name}`);
  res.json({ ok, detail: out });
});

router.post('/stop/:srv', auth, async (req, res) => {
  const name = PM2_NAME[req.params.srv];
  if (!name) return res.status(400).json({ error: 'unknown server' });
  const { ok, out } = await run(`pm2 stop ${name}`);
  res.json({ ok, detail: out });
});

// /restart/all MUST be defined before /restart/:srv — otherwise Express matches 'all' as :srv param
router.post('/restart/all', auth, async (req, res) => {
  res.json({ ok: true, detail: 'Restarting all…' });
  run(`pm2 restart tradezen-python`);
  setTimeout(() => run(`pm2 restart tradezen-node`), 3000);
});

router.post('/restart/:srv', auth, async (req, res) => {
  const name = PM2_NAME[req.params.srv];
  if (!name) return res.status(400).json({ error: 'unknown server' });
  res.json({ ok: true, detail: `Restarting ${name}…` }); // respond first
  run(`pm2 restart ${name}`);                             // then restart (non-blocking for node self-restart)
});

module.exports = router;
