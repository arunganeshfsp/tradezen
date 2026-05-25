const express = require('express');
const { query } = require('../db/db');
const router  = express.Router();

function auth(req, res, next) {
  const token = process.env.ADMIN_TOKEN;
  if (!token) return res.status(503).json({ error: 'ADMIN_TOKEN not set' });
  if ((req.headers['x-admin-token'] || '').trim() !== token)
    return res.status(401).json({ error: 'Invalid token' });
  next();
}

router.use(auth);

// ── Tree (all statuses) ──────────────────────────────────────────────────────
router.get('/tree', async (_req, res) => {
  try {
    const { rows: cats } = await query(`
      SELECT category_id, slug, title, icon, display_order, status
      FROM categories WHERE deleted_at IS NULL ORDER BY display_order
    `);
    const { rows: mods } = await query(`
      SELECT module_id, category_id, slug, title, display_order, status, difficulty_id
      FROM modules WHERE deleted_at IS NULL ORDER BY display_order
    `);
    const { rows: chs } = await query(`
      SELECT ch.chapter_id, ch.module_id, ch.slug, ch.title, ch.emoji,
             ch.status, ch.xp_reward, ch.duration_min, ch.display_order,
             dl.slug AS level,
             (SELECT COUNT(*)::int FROM chapter_questions cq WHERE cq.chapter_id = ch.chapter_id) AS quiz_count,
             (SELECT COUNT(*)::int FROM chapter_cards cc WHERE cc.chapter_id = ch.chapter_id) AS has_cards
      FROM chapters ch
      LEFT JOIN difficulty_levels dl ON dl.difficulty_id = ch.difficulty_id
      WHERE ch.deleted_at IS NULL ORDER BY ch.display_order
    `);

    const modMap = {};
    mods.forEach(m => {
      modMap[m.module_id] = { ...m, chapters: [] };
    });
    chs.forEach(c => {
      if (modMap[c.module_id]) modMap[c.module_id].chapters.push(c);
    });

    const tree = cats.map(cat => ({
      ...cat,
      modules: mods
        .filter(m => String(m.category_id) === String(cat.category_id))
        .map(m => modMap[m.module_id]),
    }));

    res.json(tree);
  } catch (err) {
    console.error('[adminLearn] tree:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Chapter detail (metadata + cards + questions) ────────────────────────────
router.get('/chapter/:slug', async (req, res) => {
  try {
    const { rows } = await query(`
      SELECT ch.*, dl.slug AS level_slug,
             m.slug AS module_slug, m.title AS module_title,
             cat.slug AS category_slug
      FROM chapters ch
      LEFT JOIN difficulty_levels dl  ON dl.difficulty_id  = ch.difficulty_id
      LEFT JOIN modules m             ON m.module_id       = ch.module_id
      LEFT JOIN categories cat        ON cat.category_id   = m.category_id
      WHERE ch.slug = $1 AND ch.deleted_at IS NULL
    `, [req.params.slug]);
    if (!rows.length) return res.status(404).json({ error: 'not found' });
    const ch = rows[0];

    const { rows: cardRows } = await query(
      `SELECT cards_json, version, updated_at FROM chapter_cards WHERE chapter_id = $1`,
      [ch.chapter_id]
    );

    const { rows: qRows } = await query(`
      SELECT cq.display_order, cq.is_required,
             qb.question_id, qb.question, qb.quiz_type, qb.options,
             qb.correct_index, qb.explanation, qb.weightage, qb.tags
      FROM chapter_questions cq
      JOIN question_bank qb ON qb.question_id = cq.question_id
      WHERE cq.chapter_id = $1 AND qb.deleted_at IS NULL
      ORDER BY cq.display_order
    `, [ch.chapter_id]);

    res.json({
      chapter:   ch,
      cards:     cardRows[0]?.cards_json || [],
      cards_version: cardRows[0]?.version || 0,
      questions: qRows,
    });
  } catch (err) {
    console.error('[adminLearn] chapter detail:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Update chapter metadata ──────────────────────────────────────────────────
router.patch('/chapter/:slug', async (req, res) => {
  const { title, description, emoji, duration_min, xp_reward, difficulty_id,
          learning_objectives, languages_available } = req.body;
  try {
    const { rows } = await query(
      `SELECT chapter_id FROM chapters WHERE slug = $1 AND deleted_at IS NULL`,
      [req.params.slug]
    );
    if (!rows.length) return res.status(404).json({ error: 'not found' });
    await query(`
      UPDATE chapters SET
        title               = COALESCE($1, title),
        description         = COALESCE($2, description),
        emoji               = COALESCE($3, emoji),
        duration_min        = COALESCE($4, duration_min),
        xp_reward           = COALESCE($5, xp_reward),
        difficulty_id       = COALESCE($6, difficulty_id),
        learning_objectives = COALESCE($7, learning_objectives),
        languages_available = COALESCE($8, languages_available),
        updated_at          = now()
      WHERE chapter_id = $9
    `, [title, description, emoji, duration_min, xp_reward, difficulty_id,
        learning_objectives ? JSON.stringify(learning_objectives) : null,
        languages_available,
        rows[0].chapter_id]);
    res.json({ ok: true });
  } catch (err) {
    console.error('[adminLearn] patch chapter:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Save cards (upsert) ──────────────────────────────────────────────────────
router.put('/chapter/:slug/cards', async (req, res) => {
  const { cards } = req.body;
  if (!Array.isArray(cards)) return res.status(400).json({ error: 'cards must be array' });
  try {
    const { rows } = await query(
      `SELECT chapter_id FROM chapters WHERE slug = $1 AND deleted_at IS NULL`,
      [req.params.slug]
    );
    if (!rows.length) return res.status(404).json({ error: 'not found' });
    const chapterId = rows[0].chapter_id;
    await query(`
      INSERT INTO chapter_cards (chapter_id, cards_json, version, updated_at)
      VALUES ($1, $2, 1, now())
      ON CONFLICT (chapter_id) DO UPDATE
        SET cards_json = EXCLUDED.cards_json,
            version    = chapter_cards.version + 1,
            updated_at = now()
    `, [chapterId, JSON.stringify(cards)]);
    res.json({ ok: true });
  } catch (err) {
    console.error('[adminLearn] save cards:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Save questions (replace all for chapter) ─────────────────────────────────
router.put('/chapter/:slug/questions', async (req, res) => {
  const { questions } = req.body; // [{question,quiz_type,options,correct_index,explanation,display_order,is_required}]
  if (!Array.isArray(questions)) return res.status(400).json({ error: 'questions must be array' });
  try {
    const { rows } = await query(
      `SELECT chapter_id FROM chapters WHERE slug = $1 AND deleted_at IS NULL`,
      [req.params.slug]
    );
    if (!rows.length) return res.status(404).json({ error: 'not found' });
    const chapterId = rows[0].chapter_id;

    // Delete existing chapter_questions links (keep question_bank rows for reuse)
    await query(`DELETE FROM chapter_questions WHERE chapter_id = $1`, [chapterId]);

    for (const q of questions) {
      // Upsert into question_bank
      let qId;
      if (q.question_id) {
        await query(`
          UPDATE question_bank SET question=$1, quiz_type=$2, options=$3,
            correct_index=$4, explanation=$5, updated_at=now()
          WHERE question_id=$6
        `, [q.question, q.quiz_type, JSON.stringify(q.options), q.correct_index,
            JSON.stringify(q.explanation), q.question_id]);
        qId = q.question_id;
      } else {
        const { rows: ins } = await query(`
          INSERT INTO question_bank (question, quiz_type, options, correct_index, explanation, source_chapter_id)
          VALUES ($1,$2,$3,$4,$5,$6) RETURNING question_id
        `, [q.question, q.quiz_type, JSON.stringify(q.options), q.correct_index,
            JSON.stringify(q.explanation), chapterId]);
        qId = ins[0].question_id;
      }
      await query(`
        INSERT INTO chapter_questions (chapter_id, question_id, display_order, is_required)
        VALUES ($1,$2,$3,$4)
      `, [chapterId, qId, q.display_order, q.is_required !== false]);
    }
    res.json({ ok: true });
  } catch (err) {
    console.error('[adminLearn] save questions:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Workflow transition ──────────────────────────────────────────────────────
const VALID_TRANSITIONS = {
  draft:      ['in_review'],
  in_review:  ['draft', 'approved'],
  approved:   ['in_review', 'scheduled', 'published'],
  scheduled:  ['approved', 'published'],
  published:  ['archived'],
  archived:   ['draft'],
};

router.post('/chapter/:slug/status', async (req, res) => {
  const { status } = req.body;
  try {
    const { rows } = await query(
      `SELECT chapter_id, status AS current FROM chapters WHERE slug=$1 AND deleted_at IS NULL`,
      [req.params.slug]
    );
    if (!rows.length) return res.status(404).json({ error: 'not found' });
    const { chapter_id, current } = rows[0];
    const allowed = VALID_TRANSITIONS[current] || [];
    if (!allowed.includes(status))
      return res.status(400).json({ error: `Cannot transition ${current} → ${status}` });

    await query(
      `UPDATE chapters SET status=$1, updated_at=now() WHERE chapter_id=$2`,
      [status, chapter_id]
    );
    res.json({ ok: true, status });
  } catch (err) {
    console.error('[adminLearn] status transition:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── Lookup data (for dropdowns) ──────────────────────────────────────────────
router.get('/lookups', async (_req, res) => {
  try {
    const { rows: difficulties } = await query(
      `SELECT difficulty_id, slug, label, color_token, icon FROM difficulty_levels ORDER BY display_order`
    );
    const { rows: modules } = await query(
      `SELECT module_id, slug, title FROM modules WHERE deleted_at IS NULL ORDER BY display_order`
    );
    res.json({ difficulties, modules });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
