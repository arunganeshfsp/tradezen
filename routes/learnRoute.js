const express = require('express');
const { query } = require('../db/db');
const router  = express.Router();

// ── GET /api/learn/catalog ──────────────────────────────────────────────────
// Returns category → module → chapter tree (published only, no card content).
// Shape is backwards-compatible with the old catalog.json format.
router.get('/catalog', async (_req, res) => {
  try {
    const { rows: categories } = await query(`
      SELECT category_id, slug, title, icon, display_order
      FROM   categories
      WHERE  deleted_at IS NULL AND status = 'published'
      ORDER  BY display_order
    `);

    const subjects = await Promise.all(categories.map(async cat => {
      const { rows: mods } = await query(`
        SELECT module_id, slug, title, display_order
        FROM   modules
        WHERE  category_id = $1 AND deleted_at IS NULL AND status = 'published'
        ORDER  BY display_order
      `, [cat.category_id]);

      const modules = await Promise.all(mods.map(async mod => {
        const { rows: chs } = await query(`
          SELECT
            ch.slug              AS id,
            ch.title,
            ch.emoji,
            ch.status,
            ch.xp_reward         AS xp,
            ch.duration_min,
            ch.display_order     AS "order",
            dl.slug              AS level,
            (SELECT COUNT(*)::int
               FROM chapter_questions cq
              WHERE cq.chapter_id = ch.chapter_id) AS quiz_count
          FROM   chapters ch
          LEFT JOIN difficulty_levels dl ON dl.difficulty_id = ch.difficulty_id
          WHERE  ch.module_id = $1 AND ch.deleted_at IS NULL
          ORDER  BY ch.display_order
        `, [mod.module_id]);

        return {
          id:      mod.slug,
          title:   mod.title,
          lessons: chs.map(ch => ({
            id:           ch.id,
            order:        ch.order,
            status:       ch.status,
            level:        ch.level   || 'beginner',
            xp:           ch.xp,
            duration_min: ch.duration_min,
            quiz_count:   ch.quiz_count,
            emoji:        ch.emoji,
            title:        ch.title,
          })),
        };
      }));

      return {
        id:      cat.slug,
        icon:    cat.icon,
        title:   cat.title,
        modules,
      };
    }));

    res.json({ version: '2', subjects });
  } catch (err) {
    console.error('[learnRoute] catalog error:', err.message);
    res.status(500).json({ error: 'catalog unavailable' });
  }
});

// ── GET /api/learn/lesson/:id ───────────────────────────────────────────────
// Returns a full lesson: metadata + assembled cards (non-quiz + quiz interleaved).
// Shape is backwards-compatible with the old lesson JSON format.
// Pass ?preview_token=TOKEN (admin token) to bypass the published-only filter.
router.get('/lesson/:id', async (req, res) => {
  const slug         = req.params.id.replace(/[^a-z0-9]/gi, '');
  const adminToken   = process.env.ADMIN_TOKEN;
  const isPreview    = adminToken && req.query.preview_token === adminToken;
  const statusClause = isPreview ? '' : `AND ch.status = 'published'`;

  try {
    // Chapter metadata
    const { rows: chRows } = await query(`
      SELECT
        ch.chapter_id, ch.slug, ch.title, ch.emoji,
        ch.xp_reward   AS xp,
        ch.duration_min,
        ch.display_order AS "order",
        dl.slug        AS level,
        m.slug         AS module_slug,
        m.title        AS module_title
      FROM   chapters ch
      LEFT JOIN difficulty_levels dl ON dl.difficulty_id = ch.difficulty_id
      LEFT JOIN modules m            ON m.module_id      = ch.module_id
      WHERE  ch.slug = $1 AND ch.deleted_at IS NULL ${statusClause}
    `, [slug]);

    if (!chRows.length) return res.status(404).json({ error: 'lesson not found' });
    const ch = chRows[0];

    // Non-quiz cards
    const { rows: cardRows } = await query(`
      SELECT cards_json FROM chapter_cards WHERE chapter_id = $1
    `, [ch.chapter_id]);
    const nonQuizCards = cardRows.length ? cardRows[0].cards_json : [];

    // Quiz questions with their card position
    const { rows: qRows } = await query(`
      SELECT
        cq.display_order,
        cq.is_required,
        qb.question_id,
        qb.question,
        qb.quiz_type,
        qb.options,
        qb.correct_index,
        qb.explanation,
        qb.weightage
      FROM   chapter_questions cq
      JOIN   question_bank qb ON qb.question_id = cq.question_id
      WHERE  cq.chapter_id = $1 AND qb.deleted_at IS NULL
      ORDER  BY cq.display_order
    `, [ch.chapter_id]);

    // Assemble quiz cards in the same shape the renderer expects
    const quizCards = qRows.map((q, idx) => ({
      id:          `q${idx + 1}`,
      type:        'quiz',
      gate:        q.is_required,
      check_label: { en: `QUICK CHECK · ${idx + 1} of ${qRows.length}`, ta: `விரைவு சோதனை · ${idx + 1} / ${qRows.length}` },
      q_id:        q.question_id,
      _insertAt:   q.display_order,
      question: {
        kind:    q.quiz_type === 'tf' ? 'true-false' : 'mcq',
        xp:      Math.round(ch.xp / (qRows.length || 1)),
        text:    q.question,
        options: (q.options || []).map((o, i) => ({
          key:     String.fromCharCode(65 + i),
          text:    { en: o.en, ta: o.ta },
          correct: i === q.correct_index,
        })),
        feedback: {
          shared: true,
          text:   q.explanation,
        },
      },
    }));

    // Interleave quiz cards at their original positions
    const allCards = [...nonQuizCards];
    for (const qCard of quizCards.sort((a, b) => a._insertAt - b._insertAt)) {
      const pos = Math.min(qCard._insertAt, allCards.length);
      allCards.splice(pos, 0, qCard);
    }
    // Clean up internal field
    allCards.forEach(c => delete c._insertAt);

    // Build outline (left-rail card list) from assembled cards
    const outline = [];
    allCards.forEach((card, idx) => {
      if (card.type === 'quiz') {
        if (outline.length && !outline[outline.length - 1].sep)
          outline.push({ sep: true });
        return;
      }
      let label = { en: '', ta: '' };
      if (card.type === 'cover') {
        const t = card.title || card.heading || {};
        if (Array.isArray(t)) label = { en: t.map(s => s.text?.en||'').join(''), ta: t.map(s => s.text?.ta||'').join('') };
        else                   label = { en: t.en||'', ta: t.ta||'' };
      } else if (card.type === 'content') {
        const pill = card.pill;
        if (pill && (pill.en || pill.ta)) { label = { en: pill.en||'', ta: pill.ta||'' }; }
        else {
          const t = card.title || {};
          if (Array.isArray(t)) label = { en: t.map(s => s.text?.en||'').join(''), ta: t.map(s => s.text?.ta||'').join('') };
          else                   label = { en: t.en||'', ta: t.ta||'' };
        }
      } else if (card.type === 'result') {
        label = { en: 'Complete', ta: 'முடிந்தது' };
      }
      outline.push({ card: idx + 1, label });
    });

    // Next chapter (next published chapter in same module by display_order)
    const { rows: nextRows } = await query(`
      SELECT slug, title, emoji
      FROM   chapters
      WHERE  module_id = (SELECT module_id FROM chapters WHERE slug = $1)
        AND  display_order > $2
        AND  status = 'published'
        AND  deleted_at IS NULL
      ORDER  BY display_order
      LIMIT  1
    `, [slug, ch.order]);
    const nextChapter = nextRows[0] || null;

    res.json({
      id:           ch.slug,
      version:      '2',
      subject_id:   null,
      module_id:    ch.module_slug,
      module_label: ch.module_title,
      order:        ch.order,
      level:        ch.level || 'beginner',
      xp:           ch.xp,
      duration_min: ch.duration_min,
      emoji:        ch.emoji,
      title:        ch.title,
      next_lesson:  nextChapter ? { id: nextChapter.slug, title: nextChapter.title, emoji: nextChapter.emoji } : null,
      cards:        allCards,
      outline,
    });
  } catch (err) {
    console.error('[learnRoute] lesson error:', err.message);
    res.status(500).json({ error: 'lesson unavailable' });
  }
});

module.exports = router;
