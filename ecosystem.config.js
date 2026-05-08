module.exports = {
  apps: [
    {
      name: 'tradezen-node',
      script: 'server.js',
      cwd: '/opt/tradezen',
      watch: false,
      autorestart: true,
      max_restarts: 10,
      env_production: {
        NODE_ENV: 'production',
        PORT: '3000',
        ADMIN_TOKEN: 'TZ2026-Admin',
      },
    },
    {
      name: 'tradezen-python',
      script: '/opt/tradezen/venv/bin/uvicorn',
      args: 'main:app --host 127.0.0.1 --port 8000',
      cwd: '/opt/tradezen/ai_engine',
      interpreter: 'none',
      watch: false,
      autorestart: true,
      max_restarts: 10,
      env_production: {
        NODE_ENV: 'production',
        ADMIN_TOKEN: 'TZ2026-Admin',
      },
    },
  ],
};
