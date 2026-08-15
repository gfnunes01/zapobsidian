// ecosystem.config.js - COMPLETO COM REDIS
module.exports = {
  apps: [
    // ============================================
    // 1. ZAP OBSIDIAN BACKEND (app.py)
    // ============================================
    {
      name: 'zap-obsidian',
      script: 'app.py',
      interpreter: 'C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python315\\python.exe',
      cwd: 'C:\\Users\\Administrator\\Desktop\\api evolution\\evolution-backend',
      env: {
        PORT: 5000,
        PUBLIC_URL: 'https://painel.pdsolucoesdigital.online',
        EVO_SERVER: 'http://localhost:8080',
        EVO_API_KEY: '4MOJO6ARCAP0EIRA',
        SECRET_KEY: 'zap_obsidian_secret_2024',
        JWT_SECRET_KEY: 'zap_obsidian_jwt_secret_2024',
        GROQ_API_KEY: ''
      },
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      error_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\zap-error.log',
      out_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\zap-out.log',
      time: true
    },

    // ============================================
    // 2. EVOLUTION API
    // ============================================
    {
      name: 'evolution-api',
      script: 'node',
      args: 'dist/main.js',
      cwd: 'C:\\Users\\Administrator\\Desktop\\api evolution\\evolution-api',
      interpreter: 'none',
      env: {
        NODE_ENV: 'production',
        PORT: 8080
      },
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      error_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\evo-error.log',
      out_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\evo-out.log',
      time: true
    },

    // ============================================
    // 3. REDIS
    // ============================================
    {
      name: 'redis',
      script: 'redis-server.exe',
      args: 'redis.windows.conf',
      cwd: 'C:\\Redis',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      error_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\redis-error.log',
      out_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\redis-out.log',
      time: true
    },

    // ============================================
    // 4. NGROK
    // ============================================
    {
      name: 'ngrok',
      script: 'C:\\Users\\Administrator\\Desktop\\api evolution\\tools\\ngrok.exe',
      args: 'http 5000 --domain=uselessly-ravioli-upon.ngrok-free.dev',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      error_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\ngrok-error.log',
      out_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\ngrok-out.log',
      time: true
    },

    // ============================================
    // 5. CADDY (HTTPS automático)
    // ============================================
    {
      name: 'caddy',
      script: 'C:\\Users\\Administrator\\Desktop\\api evolution\\caddy.exe',
      args: 'run --config Caddyfile --adapter caddyfile',
      cwd: 'C:\\Users\\Administrator\\Desktop\\api evolution',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      error_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\caddy-error.log',
      out_file: 'C:\\Users\\Administrator\\Desktop\\api evolution\\logs\\caddy-out.log',
      time: true
    }
  ]
};