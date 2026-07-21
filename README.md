# TraderSuko v1.5.0

Bot de trading cuantitativo para Binance Futures + Dashboard de monitoreo en tiempo real.

## Estructura

```
tradersuko/
├── frontend/        ← React + Vite + TypeScript
│   └── src/
│       ├── components/   ← Dashboard widgets
│       ├── services/     ← API client
│       └── types.ts      ← TypeScript interfaces
├── backend/         ← Python API + bot
│   ├── hermes_api.py     ← FastAPI REST
│   ├── hermes_brain.py   ← Lógica de señales
│   ├── hermes_executor.py← Ejecutor de órdenes
│   ├── hermes_ingest.py  ← Ingesta de datos
│   ├── core/             ← tradersuko-core (librería compartida)
│   └── requirements.txt
├── package.json
└── README.md
```

## v1.5.0 — Cambios

- **Unificación frontend + backend** en un solo repo monorepo
- **Fusión de widgets**: Executor y Position Management ahora son un solo panel
- **Datos en vivo desde Binance**: leverage, mark price, PnL y margen vía API directa
- **Eliminados** campos confusos: R-Múltiple, RIESGO, DIST. SL, R. Consumido
- **5 cuadritos de trades diarios** con sombreado automático
- **Sin dropdown de modo**: los cambios de configuración los gestiona Hermes

## Tecnologías

| Capa | Stack |
|---|---|
| Frontend | React 19, Vite 8, TypeScript 6, Tailwind 4 |
| Backend | Python 3.11, FastAPI, psycopg2, ccxt |
| DB | PostgreSQL 15 (Docker) |
| Exchange | Binance Futures API |
