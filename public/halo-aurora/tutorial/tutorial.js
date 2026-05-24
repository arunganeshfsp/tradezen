/* ============================================================
   HALO AURORA · Tutorial — shared interaction engine
   Wires:
     · MCQ + True/False clicks (.q-option)
     · Tap-the-image hotspots (.tap-target)
     · Confetti burst on correct
     · Progress rail across the page
     · Score tracking + result card render
   Each tutorial layout reuses these primitives but composes
   them differently in its HTML.
   ============================================================ */
(function () {
  'use strict';

  const TZ = window.TZTutor = window.TZTutor || {};

  // ── Confetti ──────────────────────────────────────────────
  TZ.confetti = function (count) {
    const root = document.createElement('div');
    root.className = 'confetti';
    document.body.appendChild(root);
    const palette = ['#7c6af7', '#5b8af5', '#34d399', '#f0f1f8', '#fbbf24'];
    const n = count || 60;
    for (let i = 0; i < n; i++) {
      const s = document.createElement('span');
      s.style.left = (Math.random() * 100) + '%';
      s.style.background = palette[i % palette.length];
      s.style.setProperty('--dx', ((Math.random() - 0.5) * 200) + 'px');
      s.style.animationDelay = (Math.random() * 0.4) + 's';
      s.style.animationDuration = (1.8 + Math.random() * 1.2) + 's';
      s.style.borderRadius = Math.random() > 0.5 ? '2px' : '50%';
      root.appendChild(s);
    }
    setTimeout(() => root.remove(), 3200);
  };

  // ── Score book ────────────────────────────────────────────
  TZ.scoreBook = {
    questions: 0,
    correct: 0,
    answered: new Set(),
    reset() { this.questions = 0; this.correct = 0; this.answered = new Set(); },
    register(id) {
      if (this.answered.has(id)) return;
      this.questions++;
    },
    answer(id, correct) {
      if (this.answered.has(id)) return false;
      this.answered.add(id);
      if (correct) this.correct++;
      TZ.updateProgress();
      return true;
    },
    pct() { return this.questions === 0 ? 0 : Math.round((this.correct / this.questions) * 100); },
  };

  // ── Question wiring (MCQ + True/False share .q-option) ────
  function setupQuestions() {
    document.querySelectorAll('[data-q]').forEach(q => {
      const id = q.dataset.q;
      TZ.scoreBook.register(id);

      const opts = q.querySelectorAll('.q-option');
      const fb = q.querySelector('.q-feedback');

      opts.forEach(opt => {
        opt.addEventListener('click', () => {
          if (q.dataset.locked) return;
          q.dataset.locked = '1';

          const correct = opt.dataset.correct === '1';
          opts.forEach(o => {
            o.setAttribute('data-locked', '1');
            if (o === opt) o.setAttribute('data-state', correct ? 'correct' : 'wrong');
            else if (o.dataset.correct === '1' && !correct) o.setAttribute('data-state', 'correct');
          });

          TZ.scoreBook.answer(id, correct);

          if (fb) {
            fb.classList.add('is-shown');
            fb.classList.toggle('is-correct', correct);
            fb.classList.toggle('is-wrong', !correct);
            const head = fb.querySelector('.head');
            if (head) {
              const okEn = head.dataset.okEn || 'Correct';
              const noEn = head.dataset.noEn || 'Not quite';
              const okTa = head.dataset.okTa || 'சரி';
              const noTa = head.dataset.noTa || 'தவறு';
              const lang = document.documentElement.getAttribute('lang') || 'en';
              head.textContent = correct
                ? (lang === 'ta' ? okTa : okEn)
                : (lang === 'ta' ? noTa : noEn);
            }
          }

          if (correct) TZ.confetti(36);
          document.dispatchEvent(new CustomEvent('tz-answered', { detail: { id, correct } }));
        });
      });
    });
  }

  // ── Tap-the-image wiring ──────────────────────────────────
  function setupTapTargets() {
    document.querySelectorAll('[data-tap]').forEach(t => {
      const id = t.dataset.tap;
      TZ.scoreBook.register(id);

      const marker = t.querySelector('.tap-marker');
      const fb = t.parentElement && t.parentElement.querySelector('.q-feedback');
      const hotspots = t.querySelectorAll('.tap-hotspot');

      let answered = false;

      t.addEventListener('click', e => {
        if (answered) return;
        const rect = t.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        let hit = null;
        hotspots.forEach(h => {
          const hr = h.getBoundingClientRect();
          if (e.clientX >= hr.left && e.clientX <= hr.right && e.clientY >= hr.top && e.clientY <= hr.bottom) hit = h;
        });

        const correct = hit && hit.dataset.correct === '1';
        if (marker) {
          marker.style.left = x + 'px';
          marker.style.top  = y + 'px';
          marker.classList.add('is-shown');
          marker.classList.toggle('is-wrong', !correct);
          marker.textContent = correct ? '✓' : '✕';
        }

        if (!correct) {
          const right = t.querySelector('.tap-hotspot[data-correct="1"]');
          if (right) {
            const rr = right.getBoundingClientRect();
            const cx = rr.left - rect.left + rr.width / 2;
            const cy = rr.top - rect.top + rr.height / 2;
            const ghost = document.createElement('div');
            ghost.className = 'tap-marker is-shown';
            ghost.style.left = cx + 'px';
            ghost.style.top  = cy + 'px';
            ghost.textContent = '✓';
            t.appendChild(ghost);
          }
        }

        answered = true;
        TZ.scoreBook.answer(id, !!correct);

        if (fb) {
          fb.classList.add('is-shown');
          fb.classList.toggle('is-correct', !!correct);
          fb.classList.toggle('is-wrong', !correct);
          const head = fb.querySelector('.head');
          if (head) {
            const lang = document.documentElement.getAttribute('lang') || 'en';
            head.textContent = correct
              ? (lang === 'ta' ? 'சரியான இடம்' : 'Right spot')
              : (lang === 'ta' ? 'அருகில்' : 'Close, here\'s the spot');
          }
        }

        if (correct) TZ.confetti(36);
        document.dispatchEvent(new CustomEvent('tz-answered', { detail: { id, correct: !!correct } }));
      });
    });
  }

  // ── Progress rail ─────────────────────────────────────────
  TZ.updateProgress = function () {
    const pct = TZ.scoreBook.questions
      ? Math.round((TZ.scoreBook.answered.size / TZ.scoreBook.questions) * 100)
      : 0;
    document.querySelectorAll('.progress-rail .fill').forEach(el => {
      el.style.width = pct + '%';
    });
    document.querySelectorAll('[data-progress-pct]').forEach(el => {
      el.textContent = pct + '%';
    });
    document.querySelectorAll('[data-progress-count]').forEach(el => {
      el.textContent = TZ.scoreBook.answered.size + ' / ' + TZ.scoreBook.questions;
    });
  };

  // ── Result render ────────────────────────────────────────
  TZ.renderResult = function (selector) {
    const card = document.querySelector(selector);
    if (!card) return;
    const scoreEl = card.querySelector('[data-score]');
    const totalEl = card.querySelector('[data-total]');
    const pctEl   = card.querySelector('[data-pct]');
    const xpEl    = card.querySelector('[data-xp]');

    if (scoreEl) scoreEl.textContent = TZ.scoreBook.correct;
    if (totalEl) totalEl.textContent = TZ.scoreBook.questions;
    if (pctEl)   pctEl.textContent = TZ.scoreBook.pct() + '%';
    if (xpEl)    xpEl.textContent = (TZ.scoreBook.correct * 10) + ' XP';

    const blurb = card.querySelector('[data-blurb]');
    if (blurb) {
      const lang = document.documentElement.getAttribute('lang') || 'en';
      const pct = TZ.scoreBook.pct();
      let key = 'pass';
      if (pct === 100) key = 'perfect';
      else if (pct >= 67) key = 'good';
      else key = 'retry';
      const map = {
        perfect: ['Flawless. You read the market.', 'களம் அறிந்தீர்கள்.'],
        good:    ['Solid. Calm trader in the making.', 'நல்ல தொடக்கம், நிதானமான வர்த்தகர்.'],
        pass:    ['Got the basics. Keep going.', 'அடிப்படைகள் சரி. தொடரவும்.'],
        retry:   ['Review the section, then retry.', 'மீண்டும் ஒரு முறை படியுங்கள்.'],
      };
      blurb.textContent = lang === 'ta' ? map[key][1] : map[key][0];
    }

    card.classList.add('is-shown');
    if (TZ.scoreBook.pct() >= 67) TZ.confetti(100);

    // Persist XP to localStorage guest session
    const earned = TZ.scoreBook.correct * 10;
    if (earned > 0) {
      try {
        const store = JSON.parse(localStorage.getItem('tz_learn') || '{}');
        store.xp = (store.xp || 0) + earned;
        localStorage.setItem('tz_learn', JSON.stringify(store));
      } catch (_) {}
    }
  };

  // ── Boot ─────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    setupQuestions();
    setupTapTargets();
    TZ.updateProgress();
  });
})();
