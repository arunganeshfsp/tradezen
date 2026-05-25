const fs   = require('fs');
const path = require('path');
const { query } = require('./db');

const LESSONS_DIR = path.join(__dirname, '../public/learn/lessons');

// Splits a raw lesson JSON into chapter_cards rows and question_bank rows.
// Returns { nonQuizCards, questions }
function splitCards(rawCards) {
  const nonQuizCards = [];
  const questions    = [];

  rawCards.forEach((card, idx) => {
    if (card.type !== 'quiz') {
      nonQuizCards.push({ ...card, _originalIndex: idx });
    } else {
      const q = card.question;
      // Map old quiz card → question_bank row
      const isTF = q.kind === 'true-false';
      questions.push({
        _originalIndex: idx,
        q_id:          card.q_id,
        quiz_type:     isTF ? 'tf' : 'mcq',
        question:      q.text,   // {en, ta}
        options:       (q.options || []).map(o => ({ en: o.text?.en, ta: o.text?.ta, key: o.key })),
        correct_index: (q.options || []).findIndex(o => o.correct === true),
        explanation:   q.feedback?.shared
          ? q.feedback.text
          : { en: q.feedback?.correct?.en || '', ta: q.feedback?.correct?.ta || '' },
        xp: q.xp || 10,
      });
    }
  });

  return { nonQuizCards, questions };
}

async function migrateLesson(slug) {
  const file = path.join(LESSONS_DIR, `${slug}.json`);
  if (!fs.existsSync(file)) {
    console.warn(`[migrate] ${slug}.json not found — skipping`);
    return;
  }

  const lesson = JSON.parse(fs.readFileSync(file, 'utf8'));

  // Check if chapter_cards already populated for this slug
  const { rows: existing } = await query(`
    SELECT cc.card_id
    FROM chapter_cards cc
    JOIN chapters ch ON ch.chapter_id = cc.chapter_id
    WHERE ch.slug = $1
  `, [slug]);
  if (existing.length > 0) {
    console.log(`[migrate] ${slug} already migrated — skipping`);
    return;
  }

  // Get chapter UUID
  const { rows: chRows } = await query(`SELECT chapter_id FROM chapters WHERE slug = $1`, [slug]);
  if (!chRows.length) {
    console.warn(`[migrate] Chapter slug ${slug} not in DB — run seed first`);
    return;
  }
  const chapterId = chRows[0].chapter_id;

  const { nonQuizCards, questions } = splitCards(lesson.cards || []);

  // Insert chapter_cards (non-quiz cards)
  await query(`
    INSERT INTO chapter_cards (chapter_id, cards_json, version)
    VALUES ($1, $2, 1)
    ON CONFLICT (chapter_id) DO NOTHING
  `, [chapterId, JSON.stringify(nonQuizCards)]);

  // Insert questions into question_bank + chapter_questions
  for (const q of questions) {
    const { rows: qRows } = await query(`
      INSERT INTO question_bank
        (question, quiz_type, options, correct_index, explanation, source_chapter_id)
      VALUES ($1, $2, $3, $4, $5, $6)
      RETURNING question_id
    `, [q.question, q.quiz_type, JSON.stringify(q.options), q.correct_index, q.explanation, chapterId]);

    const questionId = qRows[0].question_id;

    await query(`
      INSERT INTO chapter_questions (chapter_id, question_id, display_order)
      VALUES ($1, $2, $3)
      ON CONFLICT DO NOTHING
    `, [chapterId, questionId, q._originalIndex]);
  }

  // Mark chapter as published and set languages_available
  await query(`
    UPDATE chapters
    SET status = 'published', languages_available = '{en,ta}', updated_at = now()
    WHERE chapter_id = $1
  `, [chapterId]);

  console.log(`[migrate] ${slug} ✓ (${nonQuizCards.length} cards, ${questions.length} questions)`);
}

async function migrate() {
  // All lesson JSON files that currently exist
  const existingFiles = fs.existsSync(LESSONS_DIR)
    ? fs.readdirSync(LESSONS_DIR).filter(f => f.endsWith('.json')).map(f => f.replace('.json', ''))
    : [];

  for (const slug of existingFiles) {
    await migrateLesson(slug);
  }

  console.log('[migrate] Done.');
}

module.exports = { migrate };
