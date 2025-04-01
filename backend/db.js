const { Pool } = require('pg');

const pool = new Pool({
  user: 'postgres',
  host: 'localhost',
  database: 'unifiedems',
  password: '11928240@mK',  // Replace with your PostgreSQL password
  port: 5432,
});

module.exports = pool;