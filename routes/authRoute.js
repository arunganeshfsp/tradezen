const express  = require('express');
const bcrypt   = require('bcrypt');
const jwt      = require('jsonwebtoken');
const { query } = require('../db/db');
const router   = express.Router();

const SALT_ROUNDS = 10;

function signToken(user) {
  return jwt.sign(
    { user_id: user.user_id, email: user.email, display_name: user.display_name },
    process.env.JWT_SECRET,
    { expiresIn: '7d' }
  );
}

// ── Register ──────────────────────────────────────────────────────────────────
router.post('/register', async (req, res) => {
  const { email, password, display_name } = req.body;
  if (!email || !password)
    return res.status(400).json({ error: 'email and password required' });
  if (password.length < 6)
    return res.status(400).json({ error: 'Password must be at least 6 characters' });

  try {
    const { rows: existing } = await query(
      'SELECT 1 FROM users WHERE email = $1', [email.toLowerCase()]
    );
    if (existing.length) return res.status(409).json({ error: 'Email already registered' });

    const password_hash = await bcrypt.hash(password, SALT_ROUNDS);
    const name = display_name?.trim() || email.split('@')[0];

    const { rows } = await query(`
      INSERT INTO users (email, password_hash, display_name, last_active)
      VALUES ($1, $2, $3, now())
      RETURNING user_id, email, display_name, xp_total, streak_days, created_at
    `, [email.toLowerCase(), password_hash, name]);

    res.status(201).json({ token: signToken(rows[0]), user: rows[0] });
  } catch (err) {
    console.error('[auth] register:', err.message);
    res.status(500).json({ error: 'Registration failed' });
  }
});

// ── Login ─────────────────────────────────────────────────────────────────────
router.post('/login', async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password)
    return res.status(400).json({ error: 'email and password required' });

  try {
    const { rows } = await query(`
      SELECT user_id, email, display_name, password_hash, xp_total, streak_days
      FROM users WHERE email = $1
    `, [email.toLowerCase()]);

    if (!rows.length) return res.status(401).json({ error: 'Invalid email or password' });
    const user = rows[0];

    const valid = await bcrypt.compare(password, user.password_hash);
    if (!valid) return res.status(401).json({ error: 'Invalid email or password' });

    await query('UPDATE users SET last_active = now(), updated_at = now() WHERE user_id = $1', [user.user_id]);

    const { password_hash, ...safeUser } = user;
    res.json({ token: signToken(user), user: safeUser });
  } catch (err) {
    console.error('[auth] login:', err.message);
    res.status(500).json({ error: 'Login failed' });
  }
});

// ── Me ────────────────────────────────────────────────────────────────────────
router.get('/me', async (req, res) => {
  const header = req.headers.authorization;
  if (!header?.startsWith('Bearer ')) return res.status(401).json({ error: 'Not authenticated' });
  try {
    const payload = jwt.verify(header.slice(7), process.env.JWT_SECRET);
    const { rows } = await query(`
      SELECT user_id, email, display_name, xp_total, streak_days, last_active, created_at
      FROM users WHERE user_id = $1
    `, [payload.user_id]);
    if (!rows.length) return res.status(404).json({ error: 'User not found' });
    res.json({ user: rows[0] });
  } catch {
    res.status(401).json({ error: 'Invalid or expired token' });
  }
});

module.exports = router;
