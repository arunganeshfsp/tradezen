require('dotenv').config();
const { Pool } = require('pg');

const pool = new Pool({
  host:     process.env.PG_HOST     || 'localhost',
  port:     parseInt(process.env.PG_PORT || '5432'),
  database: process.env.PG_DATABASE || 'tradezen_learn',
  user:     process.env.PG_USER     || 'postgres',
  password: process.env.PG_PASSWORD || '',
  ssl:      process.env.PG_SSL === 'true' ? { rejectUnauthorized: false } : false,
  max: 10,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

pool.on('error', (err) => {
  console.error('[db] Unexpected pool error:', err.message);
});

const query = (text, params) => pool.query(text, params);

module.exports = { pool, query };
