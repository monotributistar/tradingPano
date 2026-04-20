# Trading Bot — Roadmap & Implementation Plan

> **Última actualización:** 2026-04-16  
> **Estado actual:** Phase 3 completada ✅

---

## Diagnóstico de gaps (audit 2026-04-17)

### 🔴 Críticos — bloquean operación segura en VPS

| # | Gap | Riesgo | Esfuerzo |
|---|-----|--------|----------|
| C1 | API sin autenticación — cualquier persona en red puede arrancar/parar el bot | CRÍTICO | 4 h |
| C2 | Credenciales de exchange hardcodeadas en `config.yaml` | CRÍTICO | 1 h |
| C3 | El bot no resume posiciones al reiniciar — puede duplicar órdenes o ignorar posiciones vivas | CRÍTICO | 1 día |
| C4 | Sin watchdog — si el thread muere, nadie lo detecta | Alto | 4 h |
| C5 | Log sin rotation — `bot.log` crece infinito, crashea disco en VPS | Alto | 1 h |

### 🟡 Importantes — necesarios para day trading real

| # | Gap | Riesgo | Esfuerzo |
|---|-----|--------|----------|
| D1 | Sin notificaciones — no hay alerta de trades, halts, crashes | Operacional | 2 días |
| D2 | Live trading solo spot — no hay shorts reales (derivados) | Estratégico | 1 día |
| D3 | Sin circuit breakers avanzados — max_daily_trades, blackout_hours | Riesgo | 4 h |
| D4 | UI polling — la frontend hace requests cada 5s, no es real-time | UX | 2 días |
| D5 | Sin SSL / HTTPS en VPS — tráfico de credenciales en claro | Seguridad | 2 h |

### 🟢 Mejoras — para operación profesional mensual/anual

| # | Gap | Valor | Esfuerzo |
|---|-----|-------|----------|
| P1 | Multi-strategy portfolio — múltiples estrategias con capital asignado | Alto | 1 semana |
| P2 | WebSocket push — UI en tiempo real | Medio | 2 días |
| P3 | Shorts reales Bybit perpetuals | Medio | 1 día |
| P4 | Métricas de sistema en UI — CPU, RAM, uptime, disco | Medio | 1 día |
| P5 | Audit trail completo — IP, versión de código, quién hizo qué | Medio | 1 día |
| P6 | Alertas de anomalías — slippage excesivo, precio desviado, balance drop | Medio | 1 día |

---

## Phases

### ✅ Pre-Phase — Infraestructura (completada)

- [x] 19 estrategias implementadas con metadata
- [x] Backtester con walk-forward, Monte Carlo, métricas
- [x] Paper trading + Live trading (spot, ccxt)
- [x] FastAPI REST API completa
- [x] React UI con Market Scanner, Dashboard, Backtests, Trades
- [x] Docker workflow (prod + dev compose)
- [x] Documentación: architecture, api-contracts, strategies, docker

---

### 🔄 Phase 1 — Seguridad y estabilidad para VPS (en curso)

**Objetivo:** Bot se puede deployar en VPS de forma segura y sobrevive reinicios sin intervención manual.

#### 1.1 API Authentication (`api/auth.py`)

Todos los endpoints protegidos con `X-API-Key` header.

```
X-API-Key: <BOT_API_SECRET>
```

- `BOT_API_SECRET` leído de variable de entorno
- Excepciones: `GET /api/health` (para healthchecks de Docker/nginx)
- Frontend envía el header desde localStorage (ingresado en Settings)
- CORS actualizado para permitir dominio del VPS

**Archivos:** `api/auth.py`, `api/main.py`, `api/routers/*`

#### 1.2 Credenciales por env vars

`config.yaml` solo tiene configuración de estrategias, nunca credenciales.

```yaml
# ANTES (peligroso)
api_key: HjmypteJjKTQLvHsh8...
secret: swReysjv9hd9c...

# DESPUÉS (config.yaml limpio — credenciales solo en .env)
# api_key y secret se leen de EXCHANGE_API_KEY / EXCHANGE_API_SECRET
```

**Archivos:** `crypto_bot/config.yaml`, `.env.example`

#### 1.3 Position resume al reiniciar (`api/bot_manager.py`)

Al llamar `POST /api/bot/start` con `"restore": true`, el bot:

1. Lee el último `BotState` activo de la DB
2. Restaura `positions` y `strategy_state`
3. Reconcilia con el exchange (verifica balance real)
4. Continúa el loop desde el estado guardado

```python
# Flujo de resume
last_state = db.query(BotState).filter_by(is_active=True).first()
if restore and last_state:
    positions = last_state.positions          # {pair: {side, qty, avg_cost, ...}}
    strategy.load_state(last_state.strategy_state)
    # Verificar que el exchange confirma las posiciones
    live_balance = engine.fetch_balance()
    _reconcile_positions(positions, live_balance)
```

**Archivos:** `api/bot_manager.py`, `api/schemas/bot.py`, `api/routers/bot.py`

#### 1.4 Thread watchdog

Un segundo thread daemon monitorea el bot thread cada 30 segundos.

- Si el thread murió sin llamar a `stop()` → loguea CRITICAL + registra `BotEvent`
- Expuesto en `GET /api/bot/status` como `"crashed": true`
- Opcionalmente: auto-restart si `auto_restart: true` en config

**Archivos:** `api/bot_manager.py`, `api/db/models.py`

#### 1.5 Log rotation

```python
from logging.handlers import RotatingFileHandler
# 10 MB por archivo, 5 archivos de backup = máximo 50 MB en disco
handler = RotatingFileHandler("data/bot.log", maxBytes=10_000_000, backupCount=5)
```

**Archivos:** `api/main.py` (setup de logging en `on_startup`)

---

### ✅ Phase 2 — Telegram Bot + Real-time (completada)

**Objetivo:** Monitoreo y control desde el teléfono + UI en tiempo real.

#### 2.1 Telegram Bot (`api/telegram_bot.py`)

| Comando | Descripción |
|---------|-------------|
| `/status` | Estado del bot (modo, estrategia, posiciones) |
| `/balance` | Equity actual |
| `/stop` | Detener el bot |
| `/start [strat]` | Arrancar con estrategia |
| `/trades [n]` | Últimos N trades |
| `/pnl` | PnL del día/semana |

**Alertas automáticas:**
```
🟢 TRADE ABIERTO:  BUY BTC/USDT @ 84,200 | qty=0.012 | strat=stoch_rsi
🔴 TRADE CERRADO:  SELL BTC/USDT @ 85,500 | PnL: +$15.60 (+1.5%)
⚠️  RISK HALT:     pérdida diaria -8% alcanzada — bot pausado
❌  ERROR:          NetworkError en BTC/USDT, reintentando (2/5)...
🔄  REINICIO:       Bot reiniciado automáticamente tras crash
```

**Librería:** `python-telegram-bot>=20` (async)  
**Config:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` en `.env`

#### 2.2 WebSocket push (`api/routers/ws.py`)

Reemplaza el polling de 5s de la UI por push en tiempo real:

```typescript
// frontend/src/hooks/useBotSocket.ts
const ws = new WebSocket(`ws://${host}/api/ws/bot`);
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  // { type: "trade" | "position" | "equity" | "status", payload: {...} }
};
```

Eventos emitidos:
- `trade` — cada vez que se ejecuta un trade
- `equity` — actualización de balance cada tick
- `status` — cambio de estado del bot (start/stop/crash/halt)

#### 2.3 Circuit breakers avanzados

```yaml
risk:
  max_daily_trades: 20          # no más de N trades por día
  min_trade_interval_min: 30    # tiempo mínimo entre trades del mismo par
  max_drawdown_pct: 25          # halt total si equity cae > 25% desde peak
  blackout_hours: "22:00-06:00" # no operar en horas de baja liquidez
  max_consecutive_losses: 5     # parar tras N pérdidas seguidas
```

---

### ✅ Phase 3 — Operación profesional (completada)

#### 3.1 Multi-strategy portfolio

```yaml
# config.yaml
portfolio:
  enabled: true
  strategies:
    - name: stoch_rsi
      capital_pct: 40
      pairs: [BTC/USDT, ETH/USDT]
    - name: trend_following
      capital_pct: 30
      pairs: [SOL/USDT, NEAR/USDT]
    - name: grid_dynamic
      capital_pct: 30
      pairs: [ETH/USDT]
```

#### 3.2 Shorts reales (Bybit perpetuals)

```python
# engine/live.py
exchange = ccxt.bybit({
    "options": {"defaultType": "swap"}  # perpetual futures
})
# short_open() y short_cover() reales con margin
```

#### 3.3 System metrics en UI

- CPU, RAM, disco del VPS en tiempo real (vía endpoint o WebSocket)
- Uptime del bot y del proceso
- Número de reconexiones al exchange
- Hit rate del cache de DataFetcher

#### 3.4 Anomaly detection

- Slippage > umbral configurable → alerta Telegram
- Balance drop inesperado > X% → alerta + pause
- Precio del exchange desviado > 1% del mid → skip trade

---

## Arquitectura objetivo (VPS)

```
VPS (Ubuntu 22.04, 2 vCPU, 4 GB RAM)
│
├── Caddy / Nginx (host)
│   └── HTTPS termination (Let's Encrypt auto)
│       └── proxy → Docker frontend :80
│
└── Docker Compose
    ├── api        → FastAPI + bot thread + Telegram bot
    │              ports: 8000 (interno, no expuesto al host)
    │              volumes: ./data (SQLite + logs)
    ├── frontend   → nginx → React app
    │              ports: 80 (expuesto al host a través de Caddy)
    └── network    → app-net (bridge, aislado)

Acceso remoto:
  https://tu-vps.com          → UI React
  https://tu-vps.com/api/docs → Swagger (requiere X-API-Key)
  Telegram Bot                → control desde el teléfono
```

---

## Changelog

| Fecha | Phase | Cambio |
|-------|-------|--------|
| 2026-04-16 | Phase 3 | Multi-strategy portfolio manager, Bybit perpetuals shorts, system metrics, anomaly detection |
| 2026-04-17 | Phase 2 | Telegram bot (notifier + comandos), WebSocket real-time, circuit breakers avanzados |
| 2026-04-17 | Phase 1 | Auth API key, credenciales env vars, position resume, watchdog, log rotation |
| 2026-04-17 | Pre | Docker workflow (prod + dev compose) |
| 2026-04-16 | Pre | Market Scanner (ATR%, ADX, RSI, S/R, strategy suggestions) |
| 2026-04-16 | Pre | 19 estrategias con metadata (ideal_timeframes, market_type, etc.) |
| 2026-04-15 | Pre | Backtester: walk-forward, Monte Carlo, timeframes 15m→1w |

---

## Decisiones de diseño

| Decisión | Elección | Razón |
|----------|----------|-------|
| Auth | API key header (`X-API-Key`) | Simple, stateless, fácil de rotar, compatible con Telegram y apps móviles |
| Credenciales | Solo env vars, nunca YAML | Evita commits accidentales de secretos |
| DB | SQLite | Suficiente para 1 instancia; fácil backup con `cp trading.db` |
| Threads | Daemon thread + watchdog | Shutdown limpio; watchdog detecta crashes silenciosos |
| Log rotation | RotatingFileHandler (50 MB max) | Evita llenado de disco en VPS |
| Position resume | DB + exchange reconciliation | DB puede estar stale; siempre verificar con exchange real |
| WebSocket | Phase 2 | Complejidad innecesaria hasta tener auth y estabilidad |
| Telegram | Phase 2 | Depende de auth de Phase 1 para ser seguro |
| Portfolio manager | Slots independientes con threads propios | Aislamiento de capital; crash de un slot no afecta a los demás |
| Perpetuals (shorts) | `defaultType: "swap"` + `reduceOnly: true` | Bybit y Binance soportados; one-way mode (no hedge mode necesario en Bybit) |
| System metrics | psutil en endpoint REST | Simple, sin WebSocket extra; Dashboard refresca cada 30 s |
| Anomaly detection | Módulo standalone `AnomalyDetector` | Inyectable en bot_manager; fácil de testear unitariamente |
