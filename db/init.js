const fs   = require('fs');
const path = require('path');
const { pool } = require('./db');
const { seed }    = require('./seed');
const { migrate } = require('./migrate');

async function initDB() {
  const client = await pool.connect();
  try {
    // 1. Run schema (idempotent — CREATE TABLE IF NOT EXISTS)
    const schema = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8');
    await client.query(schema);
    console.log('[db] Schema applied.');

    // 2. Seed reference data (ON CONFLICT DO NOTHING — safe to repeat)
    await seed();

    // 3. Migrate existing JSON lesson files into DB (skips already-migrated)
    await migrate();

    console.log('[db] Init complete.');
  } catch (err) {
    console.error('[db] Init failed:', err.message);
    throw err;
  } finally {
    client.release();
  }
}

module.exports = { initDB };
