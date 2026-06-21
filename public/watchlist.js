// Global watchlist — persists in localStorage across all TradeZen pages
const _WL_KEY = 'tz_watchlist';

window.WL = {
  get() {
    try { return JSON.parse(localStorage.getItem(_WL_KEY) || '[]'); } catch { return []; }
  },
  add(sym) {
    const l = this.get();
    if (!l.includes(sym)) {
      l.push(sym);
      localStorage.setItem(_WL_KEY, JSON.stringify(l));
      document.dispatchEvent(new CustomEvent('tz-wl-change', { detail: { symbol: sym, action: 'add' } }));
    }
  },
  remove(sym) {
    const l = this.get().filter(s => s !== sym);
    localStorage.setItem(_WL_KEY, JSON.stringify(l));
    document.dispatchEvent(new CustomEvent('tz-wl-change', { detail: { symbol: sym, action: 'remove' } }));
  },
  toggle(sym) { this.has(sym) ? this.remove(sym) : this.add(sym); },
  has(sym) { return this.get().includes(sym); },
  count() { return this.get().length; },
};
