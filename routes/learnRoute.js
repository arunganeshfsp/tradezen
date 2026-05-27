const express = require('express');
const fs      = require('fs');
const path    = require('path');
const { query } = require('../db/db');
const router  = express.Router();

const STATIC_CATALOG = path.join(__dirname, '../public/learn/catalog.json');
const STATIC_LESSONS = path.join(__dirname, '../public/learn/lessons');

// Normalize a DB title field (may be a plain string or already a {en,ta} object)
// into the canonical {en, ta} shape the client renderer expects.
function toLocObj(v) {
  if (v && typeof v === 'object') return v;
  const s = String(v || '');
  return { en: s, ta: s };
}

// ── GET /api/learn/catalog ──────────────────────────────────────────────────
// Single JOIN query — fetches all categories + modules + chapters in one round trip.
router.get('/catalog', async (_req, res) => {
  try {
    const { rows } = await query(`
      SELECT
        cat.slug            AS cat_slug,
        cat.title           AS cat_title,
        cat.icon            AS cat_icon,
        cat.display_order   AS cat_order,
        m.slug              AS mod_slug,
        m.title             AS mod_title,
        m.display_order     AS mod_order,
        ch.slug             AS ch_id,
        ch.title            AS ch_title,
        ch.emoji            AS ch_emoji,
        ch.status           AS ch_status,
        ch.xp_reward        AS ch_xp,
        ch.duration_min     AS ch_dur,
        ch.display_order    AS ch_order,
        dl.slug             AS ch_level,
        COUNT(cq.question_id)::int AS quiz_count
      FROM   categories cat
      LEFT JOIN modules m
             ON m.category_id = cat.category_id
            AND m.deleted_at IS NULL AND m.status = 'published'
      LEFT JOIN chapters ch
             ON ch.module_id = m.module_id
            AND ch.deleted_at IS NULL
      LEFT JOIN difficulty_levels dl
             ON dl.difficulty_id = ch.difficulty_id
      LEFT JOIN chapter_questions cq
             ON cq.chapter_id = ch.chapter_id
      WHERE  cat.deleted_at IS NULL AND cat.status = 'published'
      GROUP  BY cat.slug, cat.title, cat.icon, cat.display_order,
                m.slug, m.title, m.display_order,
                ch.slug, ch.title, ch.emoji, ch.status,
                ch.xp_reward, ch.duration_min, ch.display_order, dl.slug
      ORDER  BY cat.display_order, m.display_order, ch.display_order
    `);

    // Assemble flat rows into nested category → module → lesson tree
    const catMap = new Map();
    rows.forEach(r => {
      if (!catMap.has(r.cat_slug)) {
        catMap.set(r.cat_slug, {
          id:      r.cat_slug,
          icon:    r.cat_icon,
          title:   toLocObj(r.cat_title),
          modMap:  new Map(),
        });
      }
      const cat = catMap.get(r.cat_slug);
      if (!r.mod_slug) return;
      if (!cat.modMap.has(r.mod_slug)) {
        cat.modMap.set(r.mod_slug, {
          id:      r.mod_slug,
          title:   toLocObj(r.mod_title),
          lessons: [],
        });
      }
      const mod = cat.modMap.get(r.mod_slug);
      if (!r.ch_id) return;
      mod.lessons.push({
        id:           r.ch_id,
        order:        r.ch_order,
        status:       r.ch_status,
        level:        r.ch_level || 'beginner',
        xp:           r.ch_xp,
        duration_min: r.ch_dur,
        quiz_count:   r.quiz_count,
        emoji:        r.ch_emoji,
        title:        toLocObj(r.ch_title),
      });
    });

    const subjects = Array.from(catMap.values()).map(cat => ({
      id:      cat.id,
      icon:    cat.icon,
      title:   cat.title,
      modules: Array.from(cat.modMap.values()),
    }));

    console.log('[learnRoute] catalog: rows=%d subjects=%d', rows.length, subjects.length);
    res.json({ version: '2', subjects });
  } catch (err) {
    console.error('[learnRoute] catalog error — falling back to static:', err.message);
    if (fs.existsSync(STATIC_CATALOG)) {
      return res.json(JSON.parse(fs.readFileSync(STATIC_CATALOG, 'utf8')));
    }
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

    if (!chRows.length) {
      const staticLesson = path.join(STATIC_LESSONS, `${slug}.json`);
      if (fs.existsSync(staticLesson)) {
        return res.json(JSON.parse(fs.readFileSync(staticLesson, 'utf8')));
      }
      return res.status(404).json({ error: 'lesson not found' });
    }
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
      lesson_label: {
        en: `LESSON ${ch.order} · ${allCards.length} CARDS`,
        ta: `பாடம் ${ch.order} · ${allCards.length} கார்டுகள்`,
      },
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
    const staticLesson = path.join(STATIC_LESSONS, `${slug}.json`);
    if (fs.existsSync(staticLesson)) {
      return res.json(JSON.parse(fs.readFileSync(staticLesson, 'utf8')));
    }
    res.status(500).json({ error: 'lesson unavailable' });
  }
});

module.exports = router;
