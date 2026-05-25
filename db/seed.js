const { query } = require('./db');

async function seed() {
  // ── Difficulty levels ────────────────────────────────────────────────────
  const difficulties = [
    { slug: 'beginner',     label: { en: 'Beginner',     ta: 'தொடக்கநிலை',  hi: 'शुरुआती'    }, color_token: 'var(--tz-gain)',     icon: '🟢', order: 1, multiplier: 1.00 },
    { slug: 'intermediate', label: { en: 'Intermediate', ta: 'இடைநிலை',     hi: 'मध्यवर्ती'  }, color_token: 'var(--tz-warn)',     icon: '🟡', order: 2, multiplier: 1.50 },
    { slug: 'expert',       label: { en: 'Expert',       ta: 'நிபுணர் நிலை', hi: 'विशेषज्ञ'  }, color_token: 'var(--tz-accent-1)', icon: '🔴', order: 3, multiplier: 2.00 },
  ];
  for (const d of difficulties) {
    await query(`
      INSERT INTO difficulty_levels (slug, label, color_token, icon, display_order, xp_multiplier)
      VALUES ($1, $2, $3, $4, $5, $6)
      ON CONFLICT (slug) DO NOTHING
    `, [d.slug, d.label, d.color_token, d.icon, d.order, d.multiplier]);
  }

  // ── Admin roles ──────────────────────────────────────────────────────────
  const roles = [
    {
      slug: 'super_admin', name: 'Super Admin',
      permissions: { can_publish: true, can_delete: true, can_manage_users: true, category_access: null },
    },
    {
      slug: 'publisher', name: 'Publisher',
      permissions: { can_publish: true, can_delete: false, can_manage_users: false, category_access: null },
    },
    {
      slug: 'editor', name: 'Editor',
      permissions: { can_publish: false, can_delete: false, can_manage_users: false, category_access: null },
    },
    {
      slug: 'translator', name: 'Translator',
      permissions: { can_publish: false, can_delete: false, can_manage_users: false, category_access: null, translate_only: true },
    },
  ];
  for (const r of roles) {
    await query(`
      INSERT INTO admin_roles (slug, name, permissions)
      VALUES ($1, $2, $3)
      ON CONFLICT (slug) DO NOTHING
    `, [r.slug, r.name, r.permissions]);
  }

  // ── Categories ───────────────────────────────────────────────────────────
  const categories = [
    { slug: 'foundation',   title: { en: 'Foundation',           ta: 'அடிப்படை',              hi: 'आधार'         }, icon: '📚', order: 1 },
    { slug: 'fundamental',  title: { en: 'Fundamental Analysis',  ta: 'அடிப்படை பகுப்பாய்வு',  hi: 'मौलिक विश्लेषण' }, icon: '🔍', order: 2 },
    { slug: 'technical',    title: { en: 'Technical Analysis',    ta: 'தொழில்நுட்ப பகுப்பாய்வு', hi: 'तकनीकी विश्लेषण' }, icon: '📊', order: 3 },
  ];
  for (const c of categories) {
    await query(`
      INSERT INTO categories (slug, title, icon, display_order, status)
      VALUES ($1, $2, $3, $4, 'published')
      ON CONFLICT (slug) DO NOTHING
    `, [c.slug, c.title, c.icon, c.order]);
  }

  // ── Modules (full tree from product spec) ────────────────────────────────
  const { rows: cats } = await query(`SELECT category_id, slug FROM categories`);
  const catMap = Object.fromEntries(cats.map(c => [c.slug, c.category_id]));
  const { rows: diffs } = await query(`SELECT difficulty_id, slug FROM difficulty_levels`);
  const diffMap = Object.fromEntries(diffs.map(d => [d.slug, d.difficulty_id]));

  const modules = [
    // Foundation
    { slug: 'm0', category: 'foundation',  order: 1, difficulty: 'beginner',
      title: { en: 'Money Mindset & Financial Basics', ta: 'பண மனநிலை & நிதி அடிப்படைகள்', hi: 'पैसे की मानसिकता' } },
    { slug: 'm1', category: 'foundation',  order: 2, difficulty: 'beginner',
      title: { en: 'Stock Market Basics', ta: 'பங்குச்சந்தை அடிப்படைகள்', hi: 'शेयर बाजार की मूल बातें' } },
    // Fundamental Analysis
    { slug: 'm2', category: 'fundamental', order: 1, difficulty: 'beginner',
      title: { en: 'Understanding Stocks & Market', ta: 'பங்குகள் & சந்தை புரிதல்', hi: 'शेयर और बाजार को समझना' } },
    { slug: 'm3', category: 'fundamental', order: 2, difficulty: 'intermediate',
      title: { en: 'Company Analysis', ta: 'நிறுவன பகுப்பாய்வு', hi: 'कंपनी विश्लेषण' } },
    { slug: 'm4', category: 'fundamental', order: 3, difficulty: 'intermediate',
      title: { en: 'Long-Term Investing', ta: 'நீண்ட கால முதலீடு', hi: 'दीर्घकालिक निवेश' } },
    // Technical Analysis
    { slug: 'm5', category: 'technical',   order: 1, difficulty: 'intermediate',
      title: { en: 'Introduction to Charts', ta: 'சார்ட் அறிமுகம்', hi: 'चार्ट का परिचय' } },
    { slug: 'm6', category: 'technical',   order: 2, difficulty: 'intermediate',
      title: { en: 'Price Action Basics', ta: 'விலை நகர்வு அடிப்படைகள்', hi: 'प्राइस एक्शन बेसिक्स' } },
    { slug: 'm7', category: 'technical',   order: 3, difficulty: 'expert',
      title: { en: 'Trading Basics', ta: 'வர்த்தக அடிப்படைகள்', hi: 'ट्रेडिंग बेसिक्स' } },
  ];
  for (const m of modules) {
    await query(`
      INSERT INTO modules (slug, category_id, title, display_order, difficulty_id, status)
      VALUES ($1, $2, $3, $4, $5, 'published')
      ON CONFLICT (slug) DO NOTHING
    `, [m.slug, catMap[m.category], m.title, m.order, diffMap[m.difficulty]]);
  }

  // ── Chapter stubs (all chapters from product tree, content added via migrate/admin) ──
  const { rows: mods } = await query(`SELECT module_id, slug FROM modules`);
  const modMap = Object.fromEntries(mods.map(m => [m.slug, m.module_id]));

  const chapterStubs = [
    // Module 0 — Money Mindset
    { slug: 'm0c1', module: 'm0', order: 1, emoji: '💡', xp: 30, dur: 3, diff: 'beginner',
      title: { en: 'Why Money Should Grow',    ta: 'பணம் ஏன் வளர வேண்டும்' } },
    { slug: 'm0c2', module: 'm0', order: 2, emoji: '🏦', xp: 30, dur: 3, diff: 'beginner',
      title: { en: 'Saving vs Investing',       ta: 'சேமிப்பு vs முதலீடு' } },
    { slug: 'm0c3', module: 'm0', order: 3, emoji: '🔥', xp: 30, dur: 3, diff: 'beginner',
      title: { en: 'Inflation Explained Simply', ta: 'பணவீக்கம் எளிமையாக' } },
    { slug: 'm0c4', module: 'm0', order: 4, emoji: '⏰', xp: 30, dur: 3, diff: 'beginner',
      title: { en: 'Why Starting Early Matters', ta: 'ஏன் சீக்கிரம் தொடங்க வேண்டும்' } },
    { slug: 'm0c5', module: 'm0', order: 5, emoji: '⚗️', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'Power of Compounding',       ta: 'கூட்டு வட்டியின் சக்தி' } },
    { slug: 'm0c6', module: 'm0', order: 6, emoji: '🛡️', xp: 30, dur: 3, diff: 'beginner',
      title: { en: 'Emergency Fund Basics',       ta: 'அவசர நிதி அடிப்படைகள்' } },
    { slug: 'm0c7', module: 'm0', order: 7, emoji: '⚠️', xp: 30, dur: 3, diff: 'beginner',
      title: { en: 'Common Money Mistakes',       ta: 'பொதுவான பண தவறுகள்' } },

    // Module 1 — Stock Market Basics (m1l1/2/3 migrated from JSON; rest stubs)
    { slug: 'm1l1', module: 'm1', order: 1, emoji: '📈', xp: 40, dur: 4, diff: 'beginner',
      title: { en: 'What is the Stock Market?', ta: 'பங்கு சந்தை என்றால் என்ன?' } },
    { slug: 'm1l2', module: 'm1', order: 2, emoji: '💰', xp: 40, dur: 4, diff: 'beginner',
      title: { en: 'Why Do Companies Need Money?', ta: 'நிறுவனங்களுக்கு ஏன் பணம் தேவை?' } },
    { slug: 'm1l3', module: 'm1', order: 3, emoji: '🧩', xp: 30, dur: 3, diff: 'beginner',
      title: { en: 'What is a Share?', ta: 'Share என்றால் என்ன?' } },
    { slug: 'm1l4', module: 'm1', order: 4, emoji: '🛒', xp: 40, dur: 4, diff: 'beginner',
      title: { en: 'How to Buy Your First Share', ta: 'முதல் பங்கை எப்படி வாங்குவது?' } },
    { slug: 'm1c5', module: 'm1', order: 5, emoji: '📉', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'Why Price Moves?',        ta: 'விலை ஏன் மாறுகிறது?' } },
    { slug: 'm1c6', module: 'm1', order: 6, emoji: '⚖️', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'Buyers vs Sellers',       ta: 'வாங்குபவர்கள் vs விற்குபவர்கள்' } },
    { slug: 'm1c7', module: 'm1', order: 7, emoji: '💸', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'Profit & Loss Basics',    ta: 'லாப நஷ்ட அடிப்படைகள்' } },
    { slug: 'm1c8', module: 'm1', order: 8, emoji: '🎯', xp: 40, dur: 5, diff: 'beginner',
      title: { en: 'Investor vs Trader',      ta: 'முதலீட்டாளர் vs வர்த்தகர்' } },

    // Module 2 — Understanding Stocks & Market
    { slug: 'm2c1', module: 'm2', order: 1, emoji: '🏛️', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'What is NSE & BSE?',                ta: 'NSE & BSE என்றால் என்ன?' } },
    { slug: 'm2c2', module: 'm2', order: 2, emoji: '📊', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'What is a Stock Index?',            ta: 'பங்கு குறியீடு என்றால் என்ன?' } },
    { slug: 'm2c3', module: 'm2', order: 3, emoji: '🏢', xp: 40, dur: 5, diff: 'beginner',
      title: { en: 'Large Cap vs Mid Cap vs Small Cap', ta: 'Large Cap vs Mid Cap vs Small Cap' } },
    { slug: 'm2c4', module: 'm2', order: 4, emoji: '🏭', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'What is a Sector?',                ta: 'துறை என்றால் என்ன?' } },
    { slug: 'm2c5', module: 'm2', order: 5, emoji: '💼', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'What is a Portfolio?',             ta: 'போர்ட்போலியோ என்றால் என்ன?' } },
    { slug: 'm2c6', module: 'm2', order: 6, emoji: '🌍', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Retail Investor vs FII vs DII',    ta: 'சில்லறை முதலீட்டாளர் vs FII vs DII' } },
    { slug: 'm2c7', module: 'm2', order: 7, emoji: '📋', xp: 35, dur: 4, diff: 'beginner',
      title: { en: 'Basic Stock Information',          ta: 'அடிப்படை பங்கு தகவல்' } },
    { slug: 'm2c8', module: 'm2', order: 8, emoji: '📰', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Company Results Explained',        ta: 'நிறுவன முடிவுகள் விளக்கம்' } },

    // Module 3 — Company Analysis
    { slug: 'm3c1', module: 'm3', order: 1, emoji: '💹', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Revenue Explained',        ta: 'வருவாய் விளக்கம்' } },
    { slug: 'm3c2', module: 'm3', order: 2, emoji: '✅', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Profit Explained',         ta: 'லாபம் விளக்கம்' } },
    { slug: 'm3c3', module: 'm3', order: 3, emoji: '🏋️', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Debt Explained',           ta: 'கடன் விளக்கம்' } },
    { slug: 'm3c4', module: 'm3', order: 4, emoji: '📐', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'PE Ratio Explained',       ta: 'PE Ratio விளக்கம்' } },
    { slug: 'm3c5', module: 'm3', order: 5, emoji: '🧮', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'EPS Explained',            ta: 'EPS விளக்கம்' } },
    { slug: 'm3c6', module: 'm3', order: 6, emoji: '📈', xp: 50, dur: 6, diff: 'intermediate',
      title: { en: 'ROE & ROCE Basics',        ta: 'ROE & ROCE அடிப்படைகள்' } },
    { slug: 'm3c7', module: 'm3', order: 7, emoji: '💵', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Dividend Explained',       ta: 'டிவிடெண்ட் விளக்கம்' } },
    { slug: 'm3c8', module: 'm3', order: 8, emoji: '📑', xp: 50, dur: 6, diff: 'intermediate',
      title: { en: 'Reading Financial Results', ta: 'நிதி முடிவுகளை படிக்கும் முறை' } },

    // Module 4 — Long-Term Investing
    { slug: 'm4c1', module: 'm4', order: 1, emoji: '🔄', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'SIP Basics',              ta: 'SIP அடிப்படைகள்' } },
    { slug: 'm4c2', module: 'm4', order: 2, emoji: '🌈', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Diversification',         ta: 'பல்வேறுபாடு' } },
    { slug: 'm4c3', module: 'm4', order: 3, emoji: '⚖️', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'Asset Allocation',        ta: 'சொத்து ஒதுக்கீடு' } },
    { slug: 'm4c4', module: 'm4', order: 4, emoji: '🥇', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'Gold vs Stocks vs FD',    ta: 'தங்கம் vs பங்கு vs FD' } },
    { slug: 'm4c5', module: 'm4', order: 5, emoji: '🏦', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Mutual Funds Basics',     ta: 'மியூச்சுவல் ஃபண்ட் அடிப்படைகள்' } },
    { slug: 'm4c6', module: 'm4', order: 6, emoji: '🧠', xp: 35, dur: 4, diff: 'intermediate',
      title: { en: 'Wealth Building Mindset', ta: 'செல்வம் கட்டும் மனநிலை' } },
    { slug: 'm4c7', module: 'm4', order: 7, emoji: '⚗️', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'Long-Term Compounding',   ta: 'நீண்ட கால கூட்டு வட்டி' } },

    // Module 5 — Introduction to Charts
    { slug: 'm5c1', module: 'm5', order: 1, emoji: '📉', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'What is a Chart?',          ta: 'சார்ட் என்றால் என்ன?' } },
    { slug: 'm5c2', module: 'm5', order: 2, emoji: '⏱️', xp: 40, dur: 5, diff: 'intermediate',
      title: { en: 'Timeframes Explained',       ta: 'Timeframe விளக்கம்' } },
    { slug: 'm5c3', module: 'm5', order: 3, emoji: '🕯️', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'Candlestick Basics',         ta: 'Candlestick அடிப்படைகள்' } },
    { slug: 'm5c4', module: 'm5', order: 4, emoji: '🐂', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'Bullish vs Bearish Candles', ta: 'Bullish vs Bearish Candles' } },
    { slug: 'm5c5', module: 'm5', order: 5, emoji: '🧱', xp: 50, dur: 6, diff: 'intermediate',
      title: { en: 'Support & Resistance',       ta: 'ஆதரவு & எதிர்ப்பு' } },
    { slug: 'm5c6', module: 'm5', order: 6, emoji: '📐', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'Trend Basics',               ta: 'Trend அடிப்படைகள்' } },
    { slug: 'm5c7', module: 'm5', order: 7, emoji: '📢', xp: 45, dur: 5, diff: 'intermediate',
      title: { en: 'Volume Basics',              ta: 'வால்யூம் அடிப்படைகள்' } },

    // Module 6 — Price Action Basics
    { slug: 'm6c1', module: 'm6', order: 1, emoji: '🏗️', xp: 50, dur: 6, diff: 'intermediate',
      title: { en: 'Market Structure',    ta: 'சந்தை கட்டமைப்பு' } },
    { slug: 'm6c2', module: 'm6', order: 2, emoji: '💥', xp: 50, dur: 6, diff: 'intermediate',
      title: { en: 'Breakout Basics',     ta: 'Breakout அடிப்படைகள்' } },
    { slug: 'm6c3', module: 'm6', order: 3, emoji: '🎭', xp: 55, dur: 6, diff: 'intermediate',
      title: { en: 'Fake Breakouts',      ta: 'போலி Breakout' } },
    { slug: 'm6c4', module: 'm6', order: 4, emoji: '⚡', xp: 50, dur: 6, diff: 'intermediate',
      title: { en: 'Demand & Supply',     ta: 'தேவை & விநியோகம்' } },
    { slug: 'm6c5', module: 'm6', order: 5, emoji: '🚄', xp: 50, dur: 6, diff: 'intermediate',
      title: { en: 'Momentum',            ta: 'Momentum' } },
    { slug: 'm6c6', module: 'm6', order: 6, emoji: '🔄', xp: 55, dur: 6, diff: 'expert',
      title: { en: 'Trend Reversal',      ta: 'Trend திரும்புதல்' } },
    { slug: 'm6c7', module: 'm6', order: 7, emoji: '🎯', xp: 60, dur: 7, diff: 'expert',
      title: { en: 'Entry & Exit Concepts', ta: 'நுழைவு & வெளியேறுதல் கருத்துகள்' } },

    // Module 7 — Trading Basics
    { slug: 'm7c1', module: 'm7', order: 1, emoji: '⚡', xp: 55, dur: 6, diff: 'intermediate',
      title: { en: 'Intraday Basics',             ta: 'Intraday அடிப்படைகள்' } },
    { slug: 'm7c2', module: 'm7', order: 2, emoji: '📅', xp: 55, dur: 6, diff: 'intermediate',
      title: { en: 'Swing Trading Basics',        ta: 'Swing Trading அடிப்படைகள்' } },
    { slug: 'm7c3', module: 'm7', order: 3, emoji: '🛡️', xp: 60, dur: 7, diff: 'expert',
      title: { en: 'Risk Management',             ta: 'இடர் மேலாண்மை' } },
    { slug: 'm7c4', module: 'm7', order: 4, emoji: '📏', xp: 60, dur: 7, diff: 'expert',
      title: { en: 'Position Sizing',             ta: 'நிலை அளவிடல்' } },
    { slug: 'm7c5', module: 'm7', order: 5, emoji: '🛑', xp: 60, dur: 7, diff: 'expert',
      title: { en: 'Stop Loss Basics',            ta: 'Stop Loss அடிப்படைகள்' } },
    { slug: 'm7c6', module: 'm7', order: 6, emoji: '🧘', xp: 55, dur: 6, diff: 'expert',
      title: { en: 'Trading Psychology',          ta: 'வர்த்தக உளவியல்' } },
    { slug: 'm7c7', module: 'm7', order: 7, emoji: '❌', xp: 50, dur: 6, diff: 'intermediate',
      title: { en: 'Common Beginner Mistakes',    ta: 'பொதுவான தொடக்கக்கார தவறுகள்' } },
  ];

  for (const ch of chapterStubs) {
    await query(`
      INSERT INTO chapters (slug, module_id, title, emoji, duration_min, display_order, difficulty_id, xp_reward, status)
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'draft')
      ON CONFLICT (slug) DO NOTHING
    `, [ch.slug, modMap[ch.module], ch.title, ch.emoji, ch.dur, ch.order, diffMap[ch.diff], ch.xp]);
  }

  // ── Level thresholds ─────────────────────────────────────────────────────
  const levels = [
    { num: 1, xp:    0, icon: '🌱', name: { en: 'Seedling',  ta: 'விதை'         }, color: 'var(--tz-fg-3)'    },
    { num: 2, xp:  100, icon: '📗', name: { en: 'Learner',   ta: 'கற்பவர்'       }, color: 'var(--tz-gain)'   },
    { num: 3, xp:  300, icon: '📘', name: { en: 'Analyst',   ta: 'பகுப்பாய்வாளர்'}, color: 'var(--tz-accent-1)' },
    { num: 4, xp:  600, icon: '📙', name: { en: 'Trader',    ta: 'வர்த்தகர்'     }, color: 'var(--tz-warn)'   },
    { num: 5, xp: 1200, icon: '🏆', name: { en: 'Expert',    ta: 'நிபுணர்'       }, color: 'var(--tz-accent-2)' },
  ];
  for (const lv of levels) {
    await query(`
      INSERT INTO level_thresholds (level_num, name, xp_required, icon, color_token)
      VALUES ($1, $2, $3, $4, $5)
      ON CONFLICT (level_num) DO NOTHING
    `, [lv.num, lv.name, lv.xp, lv.icon, lv.color]);
  }

  // ── Badges ───────────────────────────────────────────────────────────────
  const badges = [
    { slug: 'first-chapter',   name: { en: 'First Step',    ta: 'முதல் அடி'   }, icon: '🎯',
      condition_type: 'chapters_done', condition_value: { count: 1 },  xp_bonus: 10 },
    { slug: 'five-chapters',   name: { en: 'On a Roll',     ta: 'வேகமாக'      }, icon: '🔥',
      condition_type: 'chapters_done', condition_value: { count: 5 },  xp_bonus: 25 },
    { slug: 'module-1-done',   name: { en: 'Market Ready',  ta: 'சந்தை தயார்' }, icon: '📈',
      condition_type: 'module_complete', condition_value: { module_slug: 'm1' }, xp_bonus: 50 },
    { slug: 'week-streak',     name: { en: '7-Day Streak',  ta: '7 நாள் வரிசை' }, icon: '⚡',
      condition_type: 'streak_days', condition_value: { count: 7 }, xp_bonus: 30 },
    { slug: 'perfect-quiz',    name: { en: 'Flawless',      ta: 'குறைவற்ற'     }, icon: '🥇',
      condition_type: 'perfect_quiz', condition_value: { count: 1 }, xp_bonus: 20 },
  ];
  for (const b of badges) {
    await query(`
      INSERT INTO badges (slug, name, icon, condition_type, condition_value, xp_bonus)
      VALUES ($1, $2, $3, $4, $5, $6)
      ON CONFLICT (slug) DO NOTHING
    `, [b.slug, b.name, b.icon, b.condition_type, b.condition_value, b.xp_bonus]);
  }

  console.log('[seed] Done.');
}

module.exports = { seed };
