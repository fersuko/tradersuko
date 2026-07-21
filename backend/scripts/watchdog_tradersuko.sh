#!/bin/bash
# Watchdog TraderSuko — verifica integridad del sistema cada hora
# Detects: duplicate executors, service failures, config drift

TRADING_DIR="/home/hermes/hermes_trading"
LOG_FILE="$TRADING_DIR/watchdog.log"
ALERTS=0
MESSAGES=""

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

# ── 1. Verificar que SOLO haya un executor de BTC REAL ──
EXECUTOR_COUNT=$(ps aux | grep "hermes_executor.py" | grep -v grep | wc -l)
if [ "$EXECUTOR_COUNT" -gt 1 ]; then
    ALERTS=$((ALERTS + 1))
    MSG="⚠️ DUPLICADO: $EXECUTOR_COUNT ejecutores de hermes_executor.py corriendo"
    MESSAGES="$MESSAGES\n$MSG"
    log "🔴 $MSG"
    # Matar todos los ejecutores y reiniciar el correcto
    pkill -f "hermes_executor.py" 2>/dev/null
    sleep 2
    sudo systemctl restart tradersuko_binance_real 2>/dev/null
    log "🔄 Ejecutores eliminados, tradersuko_binance_real reiniciado"
elif [ "$EXECUTOR_COUNT" -eq 0 ]; then
    ALERTS=$((ALERTS + 1))
    MSG="🔴 SIN EXECUTOR: No hay hermes_executor.py corriendo"
    MESSAGES="$MESSAGES\n$MSG"
    log "🔴 $MSG"
    sudo systemctl start tradersuko_binance_real 2>/dev/null
    log "🔄 tradersuko_binance_real iniciado"
else
    log "✅ 1 executor activo — OK"
fi

# ── 2. Verificar servicios systemd esenciales ──
for svc in tradersuko_binance_real hermes_trading_brain hermes_trading_ingest hermes_trading_api; do
    if ! systemctl is-active --quiet "$svc" 2>/dev/null; then
        ALERTS=$((ALERTS + 1))
        MSG="🔴 SERVICIO CAÍDO: $svc no está activo"
        MESSAGES="$MESSAGES\n$MSG"
        log "🔴 $MSG"
        sudo systemctl restart "$svc" 2>/dev/null
        log "🔄 $svc reiniciado"
    fi
done
log "✅ Servicios systemd — OK"

# ── 3. Verificar que NO exista el servicio duplicado viejo ──
if [ -f /etc/systemd/system/hermes_trading_executor.service ]; then
    ALERTS=$((ALERTS + 1))
    MSG="⚠️ SERVICIO VIEJO: hermes_trading_executor.service aún existe"
    MESSAGES="$MESSAGES\n$MSG"
    log "🔴 $MSG"
fi
log "✅ Sin servicios huérfanos — OK"

# ── 4. Verificar constantes brain vs executor ──
BRAIN_SL=$(grep "^SLIPPAGE_SL_PCT" "$TRADING_DIR/hermes_brain.py" | grep -oP '=\s*\K[0-9.]+')
EXECUTOR_SL=$(grep "SLIPPAGE_SL_PCT" "$TRADING_DIR/hermes_executor.py" | grep -oP 'Decimal\("\K[0-9.]+')
if [ "$BRAIN_SL" != "0.005" ] || [ "$EXECUTOR_SL" != "0.005" ]; then
    ALERTS=$((ALERTS + 1))
    MSG="⚠️ CONFIG DRIFT: brain SL=$BRAIN_SL, executor SL=$EXECUTOR_SL (esperado: 0.005)"
    MESSAGES="$MESSAGES\n$MSG"
    log "🔴 $MSG"
fi

BRAIN_TIMEOUT=$(grep "^MAX_POSITION_HOURS" "$TRADING_DIR/hermes_brain.py" | grep -oP '=\s*\K[0-9]+')
EXECUTOR_TIMEOUT=$(grep "^MAX_POSITION_HOURS" "$TRADING_DIR/hermes_executor.py" | grep -oP '=\s*\K[0-9]+')
if [ "$BRAIN_TIMEOUT" != "8" ] || [ "$EXECUTOR_TIMEOUT" != "8" ]; then
    ALERTS=$((ALERTS + 1))
    MSG="⚠️ CONFIG DRIFT: brain timeout=$BRAIN_TIMEOUT, executor timeout=$EXECUTOR_TIMEOUT (esperado: 8)"
    MESSAGES="$MESSAGES\n$MSG"
    log "🔴 $MSG"
fi
log "✅ Constantes sincronizadas — OK"

# ── 5. Verificar posición actual y balance ──
# (opcional, por ahora solo log)
log "✅ Watchdog completado — $ALERTS alerta(s)"
log "──────────────────────────────────────────"

# Mostrar resumen stdout para el cron (solo si hay alertas)
if [ "$ALERTS" -gt 0 ]; then
    echo -e "🚨 Watchdog TraderSuko — $ALERTS alerta(s) detectadas:$MESSAGES"
fi
