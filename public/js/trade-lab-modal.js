/* Trade Lab Modal — reusable paper trade popup for any page.
 * Usage: tradeLabModal.open({ symbol, name, price })
 */
(function () {
  'use strict';

  const CSS = `
    #tlm-backdrop{position:fixed;inset:0;z-index:9990;background:rgba(5,7,18,0.82);
      backdrop-filter:blur(5px);display:none;align-items:center;justify-content:center;padding:16px}
    #tlm-card{background:linear-gradient(145deg,#111829 0%,#0e1220 50%,#121728 100%);
      border:1px solid #323868;border-radius:14px;padding:28px;width:100%;max-width:400px;
      font-family:'DM Sans',sans-serif;position:relative;
      box-shadow:0 24px 64px rgba(0,0,0,0.6),0 0 0 1px rgba(124,106,247,0.08)}
    .tlm-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:20px}
    .tlm-badge{display:inline-flex;align-items:center;gap:6px;font-family:'JetBrains Mono',monospace;
      font-size:10px;letter-spacing:1.5px;text-transform:uppercase;
      color:#00d4ff;background:rgba(0,212,255,0.08);border:1px solid rgba(0,212,255,0.2);
      padding:3px 10px;border-radius:12px;margin-bottom:8px}
    .tlm-company{font-family:'Syne',sans-serif;font-size:18px;font-weight:700;color:#fff;line-height:1.2}
    .tlm-symbol{font-family:'JetBrains Mono',monospace;font-size:11px;color:#7b84a8;margin-top:3px}
    .tlm-close{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
      border-radius:8px;color:#9ba3bf;cursor:pointer;font-size:16px;line-height:1;
      padding:5px 9px;transition:all .15s;flex-shrink:0}
    .tlm-close:hover{background:rgba(255,255,255,0.12);color:#fff}
    .tlm-price-block{background:rgba(255,255,255,0.03);border:1px solid #252a44;
      border-radius:10px;padding:14px 18px;margin-bottom:20px;display:flex;align-items:baseline;gap:10px}
    .tlm-price-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;
      text-transform:uppercase;color:#7b84a8;flex-shrink:0}
    .tlm-price-val{font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:700;color:#e8ecf4}
    .tlm-qty-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;
      text-transform:uppercase;color:#7b84a8;margin-bottom:8px}
    .tlm-qty-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
    .tlm-qty-btn{background:rgba(255,255,255,0.06);border:1px solid #323868;border-radius:8px;
      color:#e8ecf4;cursor:pointer;font-size:18px;font-family:'JetBrains Mono',monospace;
      line-height:1;padding:6px 14px;transition:all .15s;font-weight:600}
    .tlm-qty-btn:hover{background:rgba(124,106,247,0.15);border-color:#7c6af7}
    #tlm-qty{flex:1;background:#0e1220;border:1px solid #323868;border-radius:8px;
      color:#fff;font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:600;
      padding:8px 12px;text-align:center;outline:none;-moz-appearance:textfield}
    #tlm-qty::-webkit-inner-spin-button,#tlm-qty::-webkit-outer-spin-button{-webkit-appearance:none}
    #tlm-qty:focus{border-color:#7c6af7}
    .tlm-est{font-family:'JetBrains Mono',monospace;font-size:11px;color:#7b84a8;
      margin-bottom:20px;text-align:center}
    #tlm-actions{display:flex;gap:10px}
    .tlm-long{flex:1;padding:13px;border-radius:10px;font-family:'Syne',sans-serif;font-size:14px;
      font-weight:700;cursor:pointer;border:1px solid rgba(46,204,113,0.35);
      background:rgba(46,204,113,0.1);color:#2ecc71;transition:all .15s;letter-spacing:.3px}
    .tlm-long:hover:not(:disabled){background:rgba(46,204,113,0.2);border-color:rgba(46,204,113,0.6)}
    .tlm-long:disabled{opacity:.4;cursor:not-allowed}
    .tlm-short{flex:1;padding:13px;border-radius:10px;font-family:'Syne',sans-serif;font-size:14px;
      font-weight:700;cursor:pointer;border:1px solid rgba(231,76,60,0.35);
      background:rgba(231,76,60,0.1);color:#e74c3c;transition:all .15s;letter-spacing:.3px}
    .tlm-short:hover:not(:disabled){background:rgba(231,76,60,0.2);border-color:rgba(231,76,60,0.6)}
    .tlm-short:disabled{opacity:.4;cursor:not-allowed}
    #tlm-signin{display:block;width:100%;padding:12px;border-radius:10px;text-align:center;
      font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;text-decoration:none;
      color:#7c6af7;border:1px solid rgba(124,106,247,0.35);background:rgba(124,106,247,0.08);
      transition:all .15s}
    #tlm-signin:hover{background:rgba(124,106,247,0.16)}
    .tlm-hint{font-family:'JetBrains Mono',monospace;font-size:10px;color:#7b84a8;
      text-align:center;margin-top:14px;line-height:1.5}
    .tlm-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
      padding:12px 22px;border-radius:10px;font-family:'JetBrains Mono',monospace;font-size:12px;
      z-index:10000;display:none;max-width:92vw;text-align:center;line-height:1.6;
      backdrop-filter:blur(10px)}
    .tlm-toast.ok{background:rgba(14,18,38,0.95);border:1px solid rgba(52,211,153,0.45);color:#2ecc71}
    .tlm-toast.err{background:rgba(14,18,38,0.95);border:1px solid rgba(248,113,113,0.45);color:#e74c3c}
    .tlm-toast a{display:inline-block;margin-top:6px;color:#fff;font-weight:600;font-size:11px;
      letter-spacing:.5px;text-decoration:none;background:rgba(255,255,255,0.12);
      border:1px solid rgba(255,255,255,0.2);padding:4px 14px;border-radius:20px;transition:background .15s}
    .tlm-toast a:hover{background:rgba(255,255,255,0.2)}
    @media(max-width:480px){
      #tlm-card{padding:20px;border-radius:16px 16px 0 0;position:fixed;bottom:0;left:0;right:0;max-width:100%}
      #tlm-backdrop{align-items:flex-end;padding:0}
    }
  `;

  const HTML = `
    <div id="tlm-backdrop">
      <div id="tlm-card">
        <div class="tlm-header">
          <div>
            <div class="tlm-badge">⚗ Trade Lab · Simulated</div>
            <div class="tlm-company" id="tlm-company">—</div>
            <div class="tlm-symbol" id="tlm-symbol">NSE</div>
          </div>
          <button class="tlm-close" id="tlm-close" aria-label="Close">✕</button>
        </div>
        <div class="tlm-price-block">
          <span class="tlm-price-lbl">Live Price</span>
          <span class="tlm-price-val" id="tlm-price">—</span>
        </div>
        <div class="tlm-qty-lbl">Quantity (shares)</div>
        <div class="tlm-qty-row">
          <button class="tlm-qty-btn" id="tlm-minus">−</button>
          <input type="number" id="tlm-qty" value="1" min="1">
          <button class="tlm-qty-btn" id="tlm-plus">+</button>
        </div>
        <div class="tlm-est" id="tlm-est">Estimated value: —</div>
        <div id="tlm-actions">
          <button class="tlm-long" id="tlm-long">▲ LONG</button>
          <button class="tlm-short" id="tlm-short">▼ SHORT</button>
        </div>
        <a id="tlm-signin" href="#" style="display:none">Sign in to use Trade Lab</a>
        <div class="tlm-hint">Virtual money only · No real orders are placed<br>For educational purposes only. Not investment advice.</div>
      </div>
    </div>
    <div class="tlm-toast" id="tlm-toast"></div>
  `;

  let _inited = false;
  let _sym = '', _price = 0;

  function _inject() {
    if (_inited) return;
    _inited = true;
    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);
    const wrap = document.createElement('div');
    wrap.innerHTML = HTML;
    while (wrap.firstChild) document.body.appendChild(wrap.firstChild);

    document.getElementById('tlm-backdrop').addEventListener('click', e => {
      if (e.target.id === 'tlm-backdrop') _close();
    });
    document.getElementById('tlm-close').addEventListener('click', _close);
    document.getElementById('tlm-minus').addEventListener('click', () => _adjustQty(-1));
    document.getElementById('tlm-plus').addEventListener('click', () => _adjustQty(1));
    document.getElementById('tlm-qty').addEventListener('input', _updateEst);
    document.getElementById('tlm-long').addEventListener('click', () => _trade('BUY'));
    document.getElementById('tlm-short').addEventListener('click', () => _trade('SELL'));
    document.addEventListener('keydown', e => { if (e.key === 'Escape') _close(); });
  }

  function _close() {
    document.getElementById('tlm-backdrop').style.display = 'none';
  }

  function _adjustQty(delta) {
    const inp = document.getElementById('tlm-qty');
    inp.value = Math.max(1, (parseInt(inp.value) || 1) + delta);
    _updateEst();
  }

  function _fmt(n) {
    return '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  }

  function _updateEst() {
    const qty = Math.max(1, parseInt(document.getElementById('tlm-qty').value) || 1);
    document.getElementById('tlm-est').textContent = `Estimated value: ${_fmt(qty * _price)}`;
  }

  function _authHdr() {
    const t = localStorage.getItem('tz_learn_token');
    return t ? { 'Authorization': 'Bearer ' + t } : {};
  }

  function _toast(msg, ok, dur) {
    const t = document.getElementById('tlm-toast');
    t.innerHTML = msg;
    t.className = 'tlm-toast ' + (ok ? 'ok' : 'err');
    t.style.display = 'block';
    clearTimeout(t._timer);
    t._timer = setTimeout(() => { t.style.display = 'none'; }, dur || (ok ? 5000 : 4000));
  }

  async function _trade(side) {
    const token = localStorage.getItem('tz_learn_token');
    if (!token) {
      window.location.href = '/learn/auth.html?next=' + encodeURIComponent(window.location.pathname);
      return;
    }
    const qty = Math.max(1, parseInt(document.getElementById('tlm-qty').value) || 1);
    const longBtn  = document.getElementById('tlm-long');
    const shortBtn = document.getElementById('tlm-short');
    longBtn.disabled = true;
    shortBtn.disabled = true;

    try {
      const r = await fetch('/api/paper/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ..._authHdr() },
        body: JSON.stringify({ instrument: 'STOCK', symbol: _sym, side, qty, price: _price }),
      });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error || d.detail || 'Order failed');
      _close();
      _toast(
        `Paper ${side} · ${_sym} × ${qty} share${qty > 1 ? 's' : ''} @ ${_fmt(_price)}<br>` +
        `<a href="/paper_trading.html">→ View Trade Lab</a>`,
        true
      );
    } catch (e) {
      _toast(e.message, false);
      longBtn.disabled = false;
      shortBtn.disabled = false;
    }
  }

  function open({ symbol, name, price }) {
    _inject();
    _sym   = symbol || '';
    _price = price  || 0;

    document.getElementById('tlm-company').textContent = name || symbol || '—';
    document.getElementById('tlm-symbol').textContent  = 'NSE · ' + (symbol || '');
    document.getElementById('tlm-price').textContent   = _fmt(_price);
    document.getElementById('tlm-qty').value = 1;
    _updateEst();

    const loggedIn = !!localStorage.getItem('tz_learn_token');
    document.getElementById('tlm-actions').style.display  = loggedIn ? 'flex' : 'none';
    const si = document.getElementById('tlm-signin');
    si.style.display = loggedIn ? 'none' : 'block';
    si.href = '/learn/auth.html?next=' + encodeURIComponent(window.location.pathname);

    document.getElementById('tlm-long').disabled  = false;
    document.getElementById('tlm-short').disabled = false;

    document.getElementById('tlm-backdrop').style.display = 'flex';
  }

  window.tradeLabModal = { open };
})();
