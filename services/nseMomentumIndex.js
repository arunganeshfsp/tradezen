const axios = require('axios');
const fs    = require('fs');
const path  = require('path');

const CACHE_FILE = path.join(__dirname, '../cache/momentum-index.json');
const TTL_MS     = 24 * 60 * 60 * 1000;

const INDEX_CONFIG = {
  NIFTY200_MOMENTUM_30: {
    csvUrl: 'https://www.niftyindices.com/IndexConstituents/ind_nifty200momentum30list.csv',
    nseParam: 'NIFTY200%20MOMENTUM%2030',
    label: 'NIFTY200 Momentum 30',
  },
  NIFTY500_MOMENTUM_50: {
    csvUrl: 'https://www.niftyindices.com/IndexConstituents/ind_nifty500Momentum50_list.csv',
    nseParam: 'NIFTY500%20MOMENTUM%2050',
    label: 'NIFTY500 Momentum 50',
  },
  NIFTYMIDCAP150_MOMENTUM_50: {
    csvUrl: 'https://www.niftyindices.com/IndexConstituents/ind_niftymidcap150Momentum50list.csv',
    nseParam: 'NIFTYMIDCAP150%20MOMENTUM%2050',
    label: 'NiftyMidcap150 Momentum 50',
  },
};

const BROWSER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,*/*',
  'Accept-Language': 'en-US,en;q=0.9',
};

class NseMomentumIndex {
  constructor() {
    this._mem        = {};
    this._diskLoaded = false;
  }

  _loadDisk() {
    if (this._diskLoaded) return;
    this._diskLoaded = true;
    try {
      const raw = JSON.parse(fs.readFileSync(CACHE_FILE, 'utf8'));
      for (const [k, v] of Object.entries(raw)) this._mem[k] = v;
    } catch { /* first run or corrupt cache — ignore */ }
  }

  _saveDisk() {
    try {
      fs.mkdirSync(path.dirname(CACHE_FILE), { recursive: true });
      fs.writeFileSync(CACHE_FILE, JSON.stringify(this._mem), 'utf8');
    } catch { /* non-fatal */ }
  }

  _parseCsv(csvText) {
    const lines = csvText.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) return null;
    const header  = lines[0].split(',').map(h => h.trim().replace(/"/g, ''));
    const symIdx  = header.findIndex(h => h.toLowerCase() === 'symbol');
    const nameIdx = header.findIndex(h => h.toLowerCase().includes('company'));
    if (symIdx === -1) return null;
    const stocks = [];
    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].split(',');
      const sym  = parts[symIdx]?.replace(/"/g, '').trim();
      const name = nameIdx !== -1 ? parts[nameIdx]?.replace(/^"|"$/g, '').trim() : '';
      if (sym && /^[A-Z][A-Z0-9\-&.]{1,19}$/.test(sym)) stocks.push({ symbol: sym, name });
    }
    return stocks.length ? stocks : null;
  }

  async _fetchFromNiftyindices(indexName) {
    const cfg  = INDEX_CONFIG[indexName];
    const resp = await axios.get(cfg.csvUrl, {
      headers: { ...BROWSER_HEADERS, Referer: 'https://www.niftyindices.com/' },
      timeout: 15000,
      responseType: 'text',
    });
    return this._parseCsv(resp.data);
  }

  async _fetchFromNSE(indexName) {
    const cfg      = INDEX_CONFIG[indexName];
    const homeResp = await axios.get('https://www.nseindia.com', {
      headers: BROWSER_HEADERS,
      timeout: 15000,
    });
    const cookies = (homeResp.headers['set-cookie'] || []).map(c => c.split(';')[0]).join('; ');
    const apiResp = await axios.get(
      `https://www.nseindia.com/api/equity-stockIndices?index=${cfg.nseParam}`,
      { headers: { ...BROWSER_HEADERS, Referer: 'https://www.nseindia.com/', Cookie: cookies }, timeout: 15000 }
    );
    const data = apiResp.data?.data;
    if (!Array.isArray(data) || !data.length) return null;
    return data
      .filter(r => r.symbol && /^[A-Z][A-Z0-9\-&.]{1,19}$/.test(r.symbol))
      .map(r => ({ symbol: r.symbol, name: r.meta?.companyName || '' }));
  }

  async getConstituents(indexName) {
    this._loadDisk();
    const cfg = INDEX_CONFIG[indexName];
    if (!cfg) throw new Error(`Unknown index: ${indexName}`);

    const cached = this._mem[indexName];
    if (cached && Date.now() - cached.fetchedAt < TTL_MS) {
      return { stocks: cached.stocks, stale: false, lastUpdated: cached.fetchedAt, label: cfg.label };
    }

    let stocks = null;
    try { stocks = await this._fetchFromNiftyindices(indexName); } catch { /* try fallback */ }
    if (!stocks) {
      try { stocks = await this._fetchFromNSE(indexName); } catch { /* both failed */ }
    }

    if (stocks) {
      this._mem[indexName] = { stocks, fetchedAt: Date.now() };
      this._saveDisk();
      return { stocks, stale: false, lastUpdated: this._mem[indexName].fetchedAt, label: cfg.label };
    }

    if (cached) return { stocks: cached.stocks, stale: true, lastUpdated: cached.fetchedAt, label: cfg.label };
    return { stocks: [], stale: true, lastUpdated: null, label: cfg.label };
  }
}

module.exports = new NseMomentumIndex();
