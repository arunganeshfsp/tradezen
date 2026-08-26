# Strategy Lab → Angel One Auto-Execution ("Algo Mode") — Design

**Status:** DOCUMENTED, NOT IMPLEMENTED (user decision 2026-08-25 — build in a future session)
**Scope:** Personal use only. Never link in public nav; never expose to other TradeZen users.

## Goal

Make the Strategy Lab engine (`public/strategy_lab.html` + ORB simulator loop in
`ai_engine/main.py`) place **real Angel One MIS orders automatically** when paper triggers fire,
using **two Angel One accounts simultaneously**:

| Strategy tab | Session key | Account |
|---|---|---|
| 09:18 Breakout & Reversal (`day_range_reversal`) | `strat_day_range_reversal` | Account A |
| 10:15 Breakout (`day_range_breakout_1015`) | `strat_day_range_breakout_1015` | Account B |

## 1. Already-built foundation (reuse, don't rebuild)

- **Login/session:** `_get_smart()` `ai_engine/main.py:1186` (TOTP via `config/credentials.py`,
  8h TTL, `_smart_lock`) + second account `_get_live_smart()` `main.py:1207` (`LIVE_*` env vars).
  Two *different* client IDs can hold concurrent sessions in one process — the duplicate-session
  caveat only applies to the same client+key.
- **Order placement:** `_live_place_order_sync(symbol, token, side, prefer_live)` `main.py:9136` —
  MIS market orders, BUY and SELL, session-error re-auth. Endpoint `POST /simulator/live-order`
  `main.py:9260`; Node route `routes/stockRoute.js:1198`. Proven by the manual Place Order button
  on `stock_intraday.html` (see `agent-artifacts/context/stock-intraday-live.md`).
- Each account needs its own **Trading-type** SmartAPI app key + TOTP secret.

## 2. Static-IP architecture (the blocker, resolved on paper)

Angel One enforces **one static IP per client account** (SEBI retail-algo framework, in force
Aug 2025). Observed: the tradeze.in droplet IP is registered to account A; registering it for
account B is rejected with "IP already registered". DigitalOcean Reserved IPs are inbound-only —
outbound calls always leave from the droplet's primary IPv4 — so they can't provide a second IP.

**Chosen design — second egress IP via proxy droplet (~$4–6/mo):**

```
droplet 1 (tradeze.in, IP-A → account A)
  ├── engine + data feed + account A orders  (direct)
  └── account B orders ──HTTPS──▶ droplet 2 (tinyproxy/squid, IP-B → account B) ──▶ Angel One
```

- Droplet 2 runs nothing but a forward proxy, firewalled to accept connections only from droplet 1.
- Route **only account B's smartapi session** through the proxy by attaching `proxies` to that
  instance's underlying `requests` usage (per-session patch). Do NOT use global `HTTPS_PROXY` —
  it would drag account A and the market-data feed through the proxy too.
- Consequence: the live loop is IP-bound and must run on droplet 1, not the local Windows box.
  Paper simulation can keep running anywhere.

## 3. Engine hook points (where real orders get wired)

Per-strategy account mapping = new key in the `_STRATEGIES` registry (`main.py:7877`), e.g.
`live_account: "A" | "B"`, resolved to the right session at order time.

| Engine event | Location | Live action |
|---|---|---|
| Breakout fill | `main.py:8399` (`orb_insert_trade` in `_orb_trigger_poll_sync`) | entry order |
| Reversal leg | `main.py:8488` (`_orb_outcome_poll_sync`) | TWO orders: exit leg-1 + enter opposite |
| SL / target / auto square-off | `main.py:8572` (`orb_update_trade`) | opposite-side exit order |
| Manual square-off | `main.py:9008` (`simulator_square_off`) | opposite-side exit order |

## 4. Pre-implementation fixes (required before any live wiring)

1. **Order serializer / rate limiter** — none exists today; the only order call site is
   `main.py:9194`. Angel One limits ≈10 orders/sec and 1/sec per symbol; a scan can trigger many
   candidates inside one 5s poll. Add a queue that serializes and paces placements.
2. **Bug `main.py:9232`** — session-refresh retry uses route key `'order.place'` instead of
   `'api.order.place'`; retries after re-auth fail. (Also `_smart_auth_ts` is assigned as a local
   there, so the TTL clock isn't refreshed.)
3. **Persist broker order ids** — `orb_stock_trades` (sqlite_store.py:79-108) has no order-id
   column; duplicate protection is in-memory only and dies on restart. Add column via the
   migration pattern (sqlite_store.py:140-190) + the explicit column list in `orb_insert_trade`
   (:350-370). `orb_update_trade` (:396) is dynamic and needs no change.
4. **Sizing** — live path hardcodes `qty = int(10000 / ltp)` (`main.py:9173`) while paper sizes at
   ₹1L via `_orb_pos_size`. Make per-strategy configurable and independent of paper sizing.
5. **Square-off timing** — broker force-squares MIS ≈15:20; app square-off is 15:30. Live exits
   must complete by ≈15:15.

## 5. Safety rails (required before arming)

- Master **"armed" toggle per strategy**, default OFF, engine-managed (NOT in
  `_STRATEGY_USER_KEYS` `main.py:7934` → a `pm2 restart tradezen-python` disarms everything).
- **Max concurrent live positions** cap + per-trade capital setting. Paper allows 50 slots × ₹1L;
  live margin must be capped far below that.
- 09:18 tab runs `default_sl_basis NONE` — live trades there would have **no stop loss**. Decide
  an SL policy before that tab is ever armed.
- Kill switch: disarm endpoint + manual square-off (both already exist in part).

## 6. Open decisions (settle at implementation time)

1. Mirror exits with real orders (SL/target/square-off/reversal)? **Recommended: yes** — entries-only
   leaves naked live positions (stock_intraday's entries-only choice doesn't scale to an algo).
2. Capital per live order and max live positions per strategy — numbers not chosen.
3. Fully automatic once armed (no per-order confirm) — implied by "algo", not explicitly confirmed.

## 7. Regulatory notes

- Self-built API algo on one's **own** accounts, below the exchange order-rate threshold, via the
  broker's API with whitelisted static IPs = the permitted retail category under SEBI's framework.
- Same IP for two accounts is blocked by Angel One (observed) — hence the proxy-droplet design.
- Keep the page off public nav (like `stock_intraday.html`). Offering auto-trading to other users
  would make TradeZen an unregistered algo provider. SEBI language rules apply to all UI copy;
  the standard educational disclaimer stays on the page.
