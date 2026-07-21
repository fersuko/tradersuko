#!/bin/bash
# Monitorea cuando se completan 5 trades REALES en 24h

COUNT=$(docker exec hermes_postgres_db psql -U hermes_trader -d hermes_trading -t -A -c "
  SELECT COUNT(*) FROM hermes_trades 
  WHERE timestamp > NOW() - INTERVAL '24 hours'
  AND modo = 'REAL'
  AND estado NOT IN ('SIMULADO','CLOSED','CLOSED_FORCE','FALLIDO','CANCELADO');
" 2>/dev/null)

LAST_NOTIFIED="/tmp/tradersuko_5_notified"

if [ "$COUNT" -ge 5 ]; then
  if [ ! -f "$LAST_NOTIFIED" ]; then
    touch "$LAST_NOTIFIED"
    echo "🚀 TRADERSUKO: 5/5 trades completados en 24h. Revisa resultados en Binance o el frontend."
  fi
else
  rm -f "$LAST_NOTIFIED" 2>/dev/null
fi
