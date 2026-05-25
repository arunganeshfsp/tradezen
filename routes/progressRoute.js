const express = require('express');
const { query } = require('../db/db');
const { requireAuth } = require('../middleware/auth');
const router = express.Router();

router.use(requireAuth);

// ── Mark chapter started / completed ─────────────────────────────────────────
router.post('/progress', async (req, res) => {
  const { chapter_slug, status } = req.body;
  if (!chapter_slug || !['started', 'completed'].includes(status))
    return res.status(400).json({ error: 'chapter_slug and status (started|completed) required' });

  try {
    const { rows: chRows } = await query(
      `SELECT chapter_id, xp_reward FROM chapters WHERE slug = $1 AND deleted_at IS NULL`,
      [chapter_slug]
    );
    if (!chRows.length) return res.status(404).json({ error: 'chapter not found' });
    const { chapter_id, xp_reward } = chRows[0];

    if (status === 'started') {
      await query(`
        INSERT INTO user_progress (user_id, chapter_id, status)
        VALUES ($1, $2, 'started')
        ON CONFLICT (user_id, chapter_id) DO NOTHING
      `, [req.user.user_id, chapter_id]);
      return res.json({ ok: true });
    }

    // completed — only award XP once
    const { rows: existing } = await query(
      `SELECT status FROM user_progress WHERE user_id = $1 AND chapter_id = $2`,
      [req.user.user_id, chapter_id]
    );

    if (!existing.length) {
      await query(`
        INSERT INTO user_progress (user_id, chapter_id, status, xp_earned, completed_at)
        VALUES ($1, $2, 'completed', $3, now())
      `, [req.user.user_id, chapter_id, xp_reward]);
      await query(
        `UPDATE users SET xp_total = xp_total + $1, updated_at = now() WHERE user_id = $2`,
        [xp_reward, req.user.user_id]
      );
    } else if (existing[0].status !== 'completed') {
      await query(`
        UPDATE user_progress
        SET status = 'completed', xp_earned = $1, completed_at = now()
        WHERE user_id = $2 AND chapter_id = $3
      `, [xp_reward, req.user.user_id, chapter_id]);
      await query(
        `UPDATE users SET xp_total = xp_total + $1, updated_at = now() WHERE user_id = $2`,
        [xp_reward, req.user.user_id]
      );
    }

    res.json({ ok: true, xp_earned: xp_reward });
  } catch (err) {
    console.error('[progress]:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Save quiz attempt ─────────────────────────────────────────────────────────
router.post('/quiz-attempt', async (req, res) => {
  const { chapter_slug, question_id, answer_index, is_correct } = req.body;
  if (!chapter_slug || !question_id)
    return res.status(400).json({ error: 'chapter_slug and question_id required' });

  try {
    const { rows } = await query(
      `SELECT chapter_id FROM chapters WHERE slug = $1 AND deleted_at IS NULL`, [chapter_slug]
    );
    if (!rows.length) return res.status(404).json({ error: 'chapter not found' });

    await query(`
      INSERT INTO user_quiz_attempts (user_id, question_id, chapter_id, answer_index, is_correct)
      VALUES ($1, $2, $3, $4, $5)
    `, [req.user.user_id, question_id, rows[0].chapter_id, answer_index ?? null, is_correct ?? null]);

    res.json({ ok: true });
  } catch (err) {
    console.error('[quiz-attempt]:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Get user's full progress ──────────────────────────────────────────────────
router.get('/my-progress', async (req, res) => {
  try {
    const { rows } = await query(`
      SELECT up.chapter_id, ch.slug, ch.title, up.status, up.xp_earned,
             up.completed_at, up.started_at
      FROM   user_progress up
      JOIN   chapters ch ON ch.chapter_id = up.chapter_id
      WHERE  up.user_id = $1
      ORDER  BY up.started_at DESC
    `, [req.user.user_id]);
    res.json({ progress: rows });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
