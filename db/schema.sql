-- TradeZen Learning System — Schema v2
-- Engine: PostgreSQL 15+
-- Run via db/init.js on every server start (CREATE TABLE IF NOT EXISTS = safe to repeat)

-- gen_random_uuid() is built-in from PostgreSQL 13+ — no extension needed

-- ─── LOOKUP TABLES ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS difficulty_levels (
  difficulty_id   SERIAL PRIMARY KEY,
  slug            TEXT UNIQUE NOT NULL,
  label           JSONB NOT NULL,
  color_token     TEXT,
  icon            TEXT,
  display_order   INTEGER DEFAULT 0,
  xp_multiplier   NUMERIC(3,2) DEFAULT 1.00
);

CREATE TABLE IF NOT EXISTS admin_roles (
  role_id     SERIAL PRIMARY KEY,
  slug        TEXT UNIQUE NOT NULL,
  name        TEXT NOT NULL,
  permissions JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- ─── ADMIN USERS ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS admin_users (
  user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name  TEXT,
  role_id       INTEGER REFERENCES admin_roles(role_id),
  is_active     BOOLEAN DEFAULT TRUE,
  last_login_at TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now(),
  deleted_at    TIMESTAMPTZ DEFAULT NULL
);

-- ─── CONTENT HIERARCHY ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS categories (
  category_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          TEXT UNIQUE NOT NULL,
  title         JSONB NOT NULL,
  description   JSONB,
  icon          TEXT,
  display_order INTEGER DEFAULT 0,
  weightage     NUMERIC(4,2) DEFAULT 1.00,
  status        TEXT DEFAULT 'published' CHECK (status IN ('draft','published','archived')),
  created_by    UUID REFERENCES admin_users(user_id),
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now(),
  deleted_at    TIMESTAMPTZ DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS modules (
  module_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  category_id   UUID REFERENCES categories(category_id),
  slug          TEXT UNIQUE NOT NULL,
  title         JSONB NOT NULL,
  description   JSONB,
  thumbnail_url TEXT,
  display_order INTEGER DEFAULT 0,
  difficulty_id INTEGER REFERENCES difficulty_levels(difficulty_id),
  weightage     NUMERIC(4,2) DEFAULT 1.00,
  status        TEXT DEFAULT 'draft' CHECK (status IN ('draft','in_review','approved','scheduled','published','archived')),
  publish_at    TIMESTAMPTZ DEFAULT NULL,
  created_by    UUID REFERENCES admin_users(user_id),
  updated_by    UUID REFERENCES admin_users(user_id),
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now(),
  deleted_at    TIMESTAMPTZ DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
  chapter_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  module_id           UUID REFERENCES modules(module_id),
  slug                TEXT UNIQUE NOT NULL,
  title               JSONB NOT NULL,
  description         JSONB,
  emoji               TEXT,
  duration_min        INTEGER DEFAULT 4,
  display_order       INTEGER DEFAULT 0,
  difficulty_id       INTEGER REFERENCES difficulty_levels(difficulty_id),
  xp_reward           INTEGER DEFAULT 40,
  weightage           NUMERIC(4,2) DEFAULT 1.00,
  status              TEXT DEFAULT 'draft' CHECK (status IN ('draft','in_review','approved','scheduled','published','archived')),
  publish_at          TIMESTAMPTZ DEFAULT NULL,
  languages_available TEXT[]   DEFAULT '{en}',
  learning_objectives JSONB    DEFAULT '[]',
  created_by          UUID REFERENCES admin_users(user_id),
  updated_by          UUID REFERENCES admin_users(user_id),
  reviewed_by         UUID REFERENCES admin_users(user_id),
  approved_by         UUID REFERENCES admin_users(user_id),
  created_at          TIMESTAMPTZ DEFAULT now(),
  updated_at          TIMESTAMPTZ DEFAULT now(),
  deleted_at          TIMESTAMPTZ DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS chapter_prerequisites (
  chapter_id          UUID REFERENCES chapters(chapter_id) ON DELETE CASCADE,
  requires_chapter_id UUID REFERENCES chapters(chapter_id) ON DELETE CASCADE,
  PRIMARY KEY (chapter_id, requires_chapter_id)
);

-- ─── CONTENT ───────────────────────────────────────────────────────────────

-- Cover, Content, Result cards only. Quiz cards assembled at serve time.
CREATE TABLE IF NOT EXISTS chapter_cards (
  card_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chapter_id UUID UNIQUE REFERENCES chapters(chapter_id) ON DELETE CASCADE,
  cards_json JSONB NOT NULL DEFAULT '[]',
  version    INTEGER DEFAULT 1,
  updated_by UUID REFERENCES admin_users(user_id),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS question_bank (
  question_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  question          JSONB NOT NULL,
  quiz_type         TEXT NOT NULL CHECK (quiz_type IN ('tf','mcq','scenario')),
  options           JSONB,
  correct_index     INTEGER,
  explanation       JSONB,
  difficulty_id     INTEGER REFERENCES difficulty_levels(difficulty_id),
  weightage         NUMERIC(4,2) DEFAULT 1.00,
  tags              TEXT[] DEFAULT '{}',
  source_chapter_id UUID REFERENCES chapters(chapter_id),
  created_by        UUID REFERENCES admin_users(user_id),
  created_at        TIMESTAMPTZ DEFAULT now(),
  updated_at        TIMESTAMPTZ DEFAULT now(),
  deleted_at        TIMESTAMPTZ DEFAULT NULL
);

-- Which questions appear in which chapter and at what card position
CREATE TABLE IF NOT EXISTS chapter_questions (
  chapter_id    UUID REFERENCES chapters(chapter_id) ON DELETE CASCADE,
  question_id   UUID REFERENCES question_bank(question_id) ON DELETE CASCADE,
  display_order INTEGER NOT NULL,
  is_required   BOOLEAN DEFAULT TRUE,
  PRIMARY KEY (chapter_id, question_id)
);

-- ─── ENRICHMENT ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tags (
  tag_id SERIAL PRIMARY KEY,
  slug   TEXT UNIQUE NOT NULL,
  label  JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS chapter_tags (
  chapter_id UUID REFERENCES chapters(chapter_id) ON DELETE CASCADE,
  tag_id     INTEGER REFERENCES tags(tag_id) ON DELETE CASCADE,
  PRIMARY KEY (chapter_id, tag_id)
);

CREATE TABLE IF NOT EXISTS glossary_terms (
  term_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chapter_id UUID REFERENCES chapters(chapter_id) ON DELETE SET NULL,
  term       JSONB NOT NULL,
  definition JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assets (
  asset_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chapter_id  UUID REFERENCES chapters(chapter_id) ON DELETE SET NULL,
  asset_type  TEXT NOT NULL CHECK (asset_type IN ('image','video','audio','pdf')),
  url         TEXT NOT NULL,
  cdn_key     TEXT,
  filename    TEXT,
  size_bytes  BIGINT,
  mime_type   TEXT,
  alt_text    JSONB,
  uploaded_by UUID REFERENCES admin_users(user_id),
  created_at  TIMESTAMPTZ DEFAULT now(),
  deleted_at  TIMESTAMPTZ DEFAULT NULL
);

-- ─── LEARNING PATHS ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS learning_paths (
  path_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug            TEXT UNIQUE NOT NULL,
  title           JSONB NOT NULL,
  description     JSONB,
  target_audience TEXT,
  icon            TEXT,
  estimated_hours NUMERIC(5,1),
  status          TEXT DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
  created_by      UUID REFERENCES admin_users(user_id),
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now(),
  deleted_at      TIMESTAMPTZ DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS path_chapters (
  path_id       UUID REFERENCES learning_paths(path_id) ON DELETE CASCADE,
  chapter_id    UUID REFERENCES chapters(chapter_id) ON DELETE CASCADE,
  display_order INTEGER NOT NULL,
  is_optional   BOOLEAN DEFAULT FALSE,
  PRIMARY KEY (path_id, chapter_id)
);

-- ─── GAMIFICATION ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS level_thresholds (
  level_id    SERIAL PRIMARY KEY,
  level_num   INTEGER UNIQUE NOT NULL,
  name        JSONB NOT NULL,
  xp_required INTEGER NOT NULL,
  icon        TEXT,
  color_token TEXT,
  unlocks     JSONB DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS badges (
  badge_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug            TEXT UNIQUE NOT NULL,
  name            JSONB NOT NULL,
  description     JSONB,
  icon            TEXT,
  condition_type  TEXT NOT NULL,
  condition_value JSONB NOT NULL,
  xp_bonus        INTEGER DEFAULT 0,
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- ─── AUDIT ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS content_versions (
  version_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type    TEXT NOT NULL,
  entity_id      UUID NOT NULL,
  change_type    TEXT NOT NULL,
  previous_value JSONB,
  new_value      JSONB,
  changed_by     UUID REFERENCES admin_users(user_id),
  changed_at     TIMESTAMPTZ DEFAULT now()
);

-- ─── INDEXES ───────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_modules_category    ON modules(category_id)        WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_modules_status      ON modules(status)              WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chapters_module     ON chapters(module_id)          WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chapters_status     ON chapters(status)             WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_chapters_publish    ON chapters(publish_at)         WHERE status = 'scheduled';
CREATE INDEX IF NOT EXISTS idx_chapter_questions   ON chapter_questions(chapter_id);
CREATE INDEX IF NOT EXISTS idx_qbank_difficulty    ON question_bank(difficulty_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_qbank_tags          ON question_bank USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_assets_chapter      ON assets(chapter_id)           WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_versions_entity     ON content_versions(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_versions_time       ON content_versions(changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_chapters_title      ON chapters USING GIN(title);
CREATE INDEX IF NOT EXISTS idx_qbank_question      ON question_bank USING GIN(question);

-- ─── USER AUTH & PROGRESS ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
  user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name  TEXT,
  avatar_url    TEXT,
  xp_total      INTEGER DEFAULT 0,
  streak_days   INTEGER DEFAULT 0,
  last_active   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_progress (
  progress_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  chapter_id   UUID NOT NULL REFERENCES chapters(chapter_id) ON DELETE CASCADE,
  status       TEXT DEFAULT 'started' CHECK (status IN ('started','completed')),
  xp_earned    INTEGER DEFAULT 0,
  completed_at TIMESTAMPTZ,
  started_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, chapter_id)
);

CREATE TABLE IF NOT EXISTS user_quiz_attempts (
  attempt_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  question_id  UUID NOT NULL REFERENCES question_bank(question_id) ON DELETE CASCADE,
  chapter_id   UUID NOT NULL REFERENCES chapters(chapter_id) ON DELETE CASCADE,
  answer_index INTEGER,
  is_correct   BOOLEAN,
  attempted_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_progress_user    ON user_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_user_progress_chapter ON user_progress(chapter_id);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user    ON user_quiz_attempts(user_id);
