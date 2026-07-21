#!/usr/bin/env python3
"""
hermes_brain.py — Cerebro Analítico Cuantitativo.
Lee metricas_btc cada 5s, analiza señales en tiempo real
y genera alertas. Los umbrales se leen desde hermes_config
para permitir ajuste en tiempo real desde el frontend.

Incluye módulo de Gestión de Posiciones:
  • Break-Even (1R): mueve SL a entrada cuando precio llega a +1R
  • Trailing Stop (Swing Lows): SL dinámico siguiendo mínimos de velas 5min
  • Time-Out (2h): cierre forzado si la posición expira
"""

import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from dotenv import load_dotenv
import psycopg2
import psycopg2.extras

# ── Cargar variables de entorno ────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Configuración desde entorno ────────────────────────────────
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "hermes_trading"),
    "user": os.getenv("DB_USER", "hermes_trader"),
    "password": os.getenv("DB_PASS", "H3rm3s_Tr4d1ng_S3cur3_P4ss_2026!"),
}

ANALYSIS_INTERVAL = 5  # segundos entre ciclos
WINDOW_MINUTES = 5     # ventana retrospectiva para tendencias
FUNDING_EXTREME = 0.001  # 0.1% funding rate = extremo
PRESION_COMPRA_ALTA = 60   # >60% = presión compra dominante (equiv. a bids 1.5x asks)
PRESION_COMPRA_BAJA = 40   # <40% = presión venta dominante (equiv. a asks 1.5x bids)

# ── Gestión de Posiciones ──────────────────────────────────────
POSITION_MGMT_INTERVAL = 30  # segundos entre ciclos de gestión (cada 6 ciclos del brain)
SLIPPAGE_SL_PCT = 0.010      # 1.0% del precio de entrada para stop-loss (sync con executor)
TP_RATIO = 2.0               # ratio de take profit (2.0 → 0.2%)
MAX_POSITION_HOURS = 8       # horas máximas antes de cierre forzado (sync con executor)
SWING_LOOKBACK = 12           # velas a revisar para swing low/high (antes 3)
CANDLE_MINUTES = 5           # tamaño de vela para swing analysis

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hermes_brain")


class BrainAnalyzer:
    """Analiza los datos de metricas_btc y genera señales."""

    def __init__(self, db_config):
        self.conn = None
        self.db_config = db_config
        self.last_alert_time = {}
        self.alert_cooldown = 30

        # ── Valores dinámicos (se cargan desde DB) ───────────
        self.umbral_liquidaciones = 300000.0
        self.delta_cvd_confirmacion = 500000.0
        self.apalancamiento = 5
        self.margen_operacion = 2.0
        self.modo_sistema = "SIMULACION"

        # ── Estado de gestión de posiciones ──────────────────
        self.position_state = {
            "trade_id": None,        # ID del trade que estamos gestionando
            "entry_price": 0.0,      # Precio de entrada
            "initial_sl": 0.0,       # Precio del SL inicial (1R abajo/arriba)
            "current_sl": 0.0,       # Precio del SL actual (puede moverse)
            "r_distance": 0.0,       # Distancia R en USD
            "breakeven_activated": False,  # ¿Ya movimos SL a BE?
            "trailing_activated": False,   # ¿Ya estamos en trailing?
            "last_swing_low": 0.0,   # Último swing low registrado
            "last_swing_high": 0.0,  # Último swing high registrado
            "position_side": None,   # "LONG" o "SHORT"
            "position_open_time": None,  # datetime de apertura
            "cycle_count": 0,        # Contador para intervalo de gestión
        }

    def connect(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(**self.db_config)
            self.conn.autocommit = False
            log.info("✅ Cerebro conectado a PostgreSQL")

    # ── Persistencia de alertas ──────────────────────────────
    def insert_alerta(self, tipo: str, mensaje: str):
        """Inserta un evento en la tabla hermes_alertas."""
        try:
            if self.conn is None or self.conn.closed:
                self.connect()
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO hermes_alertas (tipo, mensaje) VALUES (%s, %s)",
                    (tipo, mensaje),
                )
            self.conn.commit()
        except Exception as e:
            log.warning(f"⚠️  No se pudo insertar alerta en DB: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass

    def update_trade_sl_db(self, trade_id: int, sl_price: float):
        """Persiste el SL actual en la tabla hermes_trades."""
        try:
            if self.conn is None or self.conn.closed:
                self.connect()
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE hermes_trades SET stop_loss = %s WHERE id = %s",
                    (sl_price, trade_id),
                )
            self.conn.commit()
        except Exception as e:
            log.warning(f"⚠️ No se pudo actualizar SL #{trade_id} en BD: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass

    # ── Carga de configuración dinámica ──────────────────────
    def load_config(self):
        """Lee la configuración desde hermes_config y actualiza atributos."""
        try:
            if self.conn is None or self.conn.closed:
                self.connect()

            with self.conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute("SELECT * FROM hermes_config WHERE id = 1")
                row = cur.fetchone()

            if row:
                self.umbral_liquidaciones = float(
                    row.get("umbral_liquidaciones", 200000.0)
                )
                self.delta_cvd_confirmacion = float(
                    row.get("delta_cvd_confirmacion", 500000.0)
                )
                self.apalancamiento = int(
                    row.get("apalancamiento", 10)
                )
                self.margen_operacion = float(
                    row.get("margen_operacion", 2.0)
                )
                self.modo_sistema = str(
                    row.get("modo_sistema", "SIMULACION")
                )

                log.debug(
                    f"⚙️  Config cargada: liq={self.umbral_liquidaciones:.0f} "
                    f"cvd={self.delta_cvd_confirmacion:.0f} "
                    f"apal={self.apalancamiento}x "
                    f"margen={self.margen_operacion:.1f}% "
                    f"modo={self.modo_sistema}"
                )
        except Exception as e:
            log.warning(f"⚠️  No se pudo cargar config desde DB: {e}")

    # ── Lectura de métricas ───────────────────────────────────
    def get_recent_data(self, minutes=WINDOW_MINUTES):
        """Obtiene los registros de los últimos N minutos."""
        try:
            if self.conn is None or self.conn.closed:
                self.connect()

            with self.conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    """
                    SELECT * FROM metricas_btc
                    WHERE timestamp > %s
                    ORDER BY timestamp DESC
                    """,
                    (
                        datetime.now(timezone.utc)
                        - timedelta(minutes=minutes),
                    ),
                )
                return cur.fetchall()
        except Exception as e:
            log.error(f"❌ Error leyendo DB: {e}")
            self.conn.rollback()
            return []

    # ── Lectura de posición abierta ──────────────────────────
    def get_open_position(self):
        """
        Lee el último trade EJECUTADO de hermes_trades.
        Si el trade no tiene balance_despues, consideramos que sigue abierto.
        Retorna el registro o None.
        """
        try:
            if self.conn is None or self.conn.closed:
                self.connect()
            with self.conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    """
                    SELECT * FROM hermes_trades
                    WHERE estado = 'EJECUTADO'
                    AND balance_despues IS NULL
                    ORDER BY timestamp DESC LIMIT 1
                    """
                )
                return cur.fetchone()
        except Exception as e:
            log.warning(f"⚠️  Error leyendo posición abierta: {e}")
            return None

    # ── Cálculo de Swing Lows / Highs ────────────────────────
    def get_swing_levels(self, rows, lookback=SWING_LOOKBACK):
        """
        De los registros de metricas_btc (ordenados DESC), toma los últimos
        `lookback` puntos como si fueran velas de CANDLE_MINUTES min.
        Retorna (swing_low, swing_high).
        """
        if not rows or len(rows) < lookback:
            return None, None

        # rows vienen ordenados DESC (más recent first)
        # Nos interesan los últimos `lookback` registros
        relevant = rows[:lookback]
        prices = [float(r["precio"]) for r in relevant if r.get("precio")]

        if len(prices) < lookback:
            return None, None

        swing_low = min(prices)
        swing_high = max(prices)
        return swing_low, swing_high

    # ── Gestión de Posiciones ────────────────────────────────
    def manage_positions(self, rows):
        """
        Evalúa posiciones abiertas y genera alertas de gestión:
        1. Break-Even (1R)
        2. Trailing Stop (Swing Lows)
        3. Time-Out (2h)
        """
        mgmt_alerts = []
        if not rows:
            return mgmt_alerts

        latest = rows[0]
        current_price = float(latest["precio"]) if latest.get("precio") else 0
        if current_price <= 0:
            return mgmt_alerts

        # 1. Obtener posición abierta
        position = self.get_open_position()
        if not position:
            # No hay posición abierta — resetear estado
            if self.position_state["trade_id"] is not None:
                log.info("🧹 Posición cerrada — reseteando estado de gestión")
                self.position_state = {
                    "trade_id": None,
                    "entry_price": 0.0,
                    "initial_sl": 0.0,
                    "current_sl": 0.0,
                    "r_distance": 0.0,
                    "breakeven_activated": False,
                    "trailing_activated": False,
                    "last_swing_low": 0.0,
                    "last_swing_high": 0.0,
                    "position_side": None,
                    "position_open_time": None,
                    "cycle_count": 0,
                }
            return mgmt_alerts

        trade_id = position["id"]
        side = position["lado"]
        entry = float(position["precio_entrada"])
        open_time = position["timestamp"]

        # ── ¿Es una posición nueva? → Inicializar estado ────
        if self.position_state["trade_id"] != trade_id:
            r_dist = entry * SLIPPAGE_SL_PCT  # 0.1% del entry
            if side == "LONG":
                init_sl = entry - r_dist
            else:
                init_sl = entry + r_dist

            self.position_state = {
                "trade_id": trade_id,
                "entry_price": entry,
                "initial_sl": init_sl,
                "current_sl": init_sl,
                "r_distance": r_dist,
                "breakeven_activated": False,
                "trailing_activated": False,
                "last_swing_low": 0.0,
                "last_swing_high": 0.0,
                "position_side": side,
                "position_open_time": open_time,
                "cycle_count": 0,
            }
            log.info(
                f"📌 Nueva posición detectada: #{trade_id} {side} @ ${entry:.2f} "
                f"| R=${r_dist:.0f} | SL inicial=${init_sl:.2f}"
            )
            self.insert_alerta(
                "POSITION_OPEN",
                f"📌 Posición #{trade_id} {side} @ ${entry:.2f} "
                f"| R=${r_dist:.0f} | SL=${init_sl:.2f}",
            )

        # Incrementar contador de gestión
        self.position_state["cycle_count"] += 1

        # ── 2. Calcular swing levels ──────────────────────────
        swing_low, swing_high = self.get_swing_levels(rows)
        self.position_state["last_swing_low"] = swing_low or self.position_state["last_swing_low"]
        self.position_state["last_swing_high"] = swing_high or self.position_state["last_swing_high"]

        # ── 3. Evaluar reglas ────────────────────────────────

        # Calcular P&L actual en USD y en R
        if side == "LONG":
            profit_usd = current_price - entry
            profit_r = profit_usd / self.position_state["r_distance"] if self.position_state["r_distance"] > 0 else 0
        else:
            profit_usd = entry - current_price
            profit_r = profit_usd / self.position_state["r_distance"] if self.position_state["r_distance"] > 0 else 0

        side_emoji = "🟢" if side == "LONG" else "🔴"
        prefix = "[DRY RUN]" if self.modo_sistema == "SIMULACION" else "[LIVE]"

        # ── REGLA 1: BREAK-EVEN (a 2.5R) ───────────────────────
        if not self.position_state["breakeven_activated"] and profit_r >= 2.5:
            be_sl = entry  # Mover SL al precio de entrada
            self.position_state["current_sl"] = be_sl
            self.position_state["breakeven_activated"] = True
            msg = (
                f"{prefix} 🎯 BREAK-EVEN ACTIVADO #{trade_id} {side}: "
                f"Precio alcanzó +1R (${profit_usd:.2f}) → "
                f"SL movido a ENTRY ${be_sl:.2f}"
            )
            log.info(f"🟢 {msg}")
            self.insert_alerta("MGMT_BREAK_EVEN", msg)
            mgmt_alerts.append({"type": "MGMT_BREAK_EVEN", "severity": "INFO", "message": msg})
            self.update_trade_sl_db(trade_id, be_sl)

        # ── REGLA 2: TRAILING STOP (después de 1R) ───────────
        elif self.position_state["breakeven_activated"] and swing_low is not None:
            if side == "LONG":
                # Trailing LONG: SL por debajo del swing low con buffer mínimo
                min_buffer = max(swing_low * 0.001, 30.0)  # 0.1% o $30, lo que sea mayor
                new_sl = swing_low - min_buffer
                # Solo mover si el nuevo SL es MÁS ALTO que el actual (protege ganancias)
                if new_sl > self.position_state["current_sl"]:
                    old_sl = self.position_state["current_sl"]
                    self.position_state["current_sl"] = new_sl
                    self.position_state["trailing_activated"] = True
                    msg = (
                        f"{prefix} 🏁 TRAILING SL #{trade_id} {side}: "
                        f"${old_sl:.2f} → ${new_sl:.2f} "
                        f"(swing low=${swing_low:.2f}, profit=${profit_usd:.2f})"
                    )
                    log.info(f"🔷 {msg}")
                    self.insert_alerta("MGMT_TRAILING_SL", msg)
                    mgmt_alerts.append({"type": "MGMT_TRAILING_SL", "severity": "INFO", "message": msg})
                    self.update_trade_sl_db(trade_id, new_sl)
            else:
                # Trailing SHORT: SL por encima del swing high con buffer mínimo
                min_buffer = max(swing_high * 0.001, 30.0)  # 0.1% o $30, lo que sea mayor
                new_sl = swing_high + min_buffer
                if new_sl < self.position_state["current_sl"] or self.position_state["current_sl"] == self.position_state["initial_sl"]:
                    if new_sl < self.position_state["current_sl"]:
                        old_sl = self.position_state["current_sl"]
                        self.position_state["current_sl"] = new_sl
                        self.position_state["trailing_activated"] = True
                        msg = (
                            f"{prefix} 🏁 TRAILING SL #{trade_id} {side}: "
                            f"${old_sl:.2f} → ${new_sl:.2f} "
                            f"(swing high=${swing_high:.2f}, profit=${profit_usd:.2f})"
                        )
                        log.info(f"🔷 {msg}")
                        self.insert_alerta("MGMT_TRAILING_SL", msg)
                        mgmt_alerts.append({"type": "MGMT_TRAILING_SL", "severity": "INFO", "message": msg})
                        self.update_trade_sl_db(trade_id, new_sl)

        # ── REGLA 3: TIME-OUT (2h) ───────────────────────────
        if open_time:
            elapsed = datetime.now(timezone.utc) - open_time
            elapsed_hours = elapsed.total_seconds() / 3600
            if elapsed_hours >= MAX_POSITION_HOURS:
                msg = (
                    f"{prefix} ⏰ TIME-OUT #{trade_id} {side}: "
                    f"Posición abierta por {elapsed_hours:.1f}h "
                    f"(límite: {MAX_POSITION_HOURS}h) → "
                    f"Ejecutar Market Close forzado"
                )
                log.warning(f"⚠️ {msg}")
                self.insert_alerta("MGMT_TIME_OUT", msg)
                mgmt_alerts.append({"type": "MGMT_TIME_OUT", "severity": "WARNING", "message": msg})

        # ── Log de estado periódico ──────────────────────────
        if self.position_state["cycle_count"] % 6 == 0:  # Cada ~30s
            estado_sl = "INICIAL" if not self.position_state["breakeven_activated"] else \
                        "BREAK-EVEN" if not self.position_state["trailing_activated"] else \
                        "TRAILING"
            log.info(
                f"{prefix} 📊 #{trade_id} {side_emoji} "
                f"Entry=${entry:.2f} | "
                f"Now=${current_price:.2f} | "
                f"P&L=${profit_usd:+.2f} ({profit_r:+.1f}R) | "
                f"SL={estado_sl} @ ${self.position_state['current_sl']:.2f}"
            )

        return mgmt_alerts

    # ── Análisis ──────────────────────────────────────────────
    def analyze(self, rows):
        """Ejecuta análisis sobre los datos y retorna alertas."""
        alerts = []
        if not rows:
            return alerts

        latest = rows[0]
        prev = rows[1] if len(rows) > 1 else None

        precio = float(latest["precio"])
        cvd = float(latest["cvd_binance"])
        presion = float(latest["presion_compra"])

        # ── 1. CVD (presión compradora/vendedora) ──────────────
        if prev and prev["cvd_binance"]:
            cvd_prev = float(prev["cvd_binance"])
            cvd_change = (
                (cvd - cvd_prev) / abs(cvd_prev) if cvd_prev != 0 else 0
            )

            cvd_window = sum(
                float(r["cvd_binance"])
                for r in rows
                if r["cvd_binance"]
            )
            cvd_trades = sum(
                1
                for r in rows
                if r["cvd_binance"] and float(r["cvd_binance"]) > 0
            )

            # delta_cvd_confirmacion como % de cambio para señal
            cvd_pct_threshold = (
                self.delta_cvd_confirmacion / 1_000_000
            )  # Escala: 500k → 0.5%

            if abs(cvd) > self.delta_cvd_confirmacion:
                direction = "↑ BULLISH" if cvd > 0 else "↓ BEARISH"
                alerts.append({
                    "type": "CVD_SIGNAL",
                    "severity": "INFO",
                    "message": (
                        f"CVD {direction} — "
                        f"CVD acumulado: ${abs(cvd):,.2f} "
                        f"(umbral: ${self.delta_cvd_confirmacion:,.0f})"
                    ),
                })

        # ── 2. Presión de compra (order book) ──────────────────
        if presion > PRESION_COMPRA_ALTA:
            alerts.append({
                "type": "BUY_PRESSURE_HIGH",
                "severity": "WARNING",
                "message": (
                    f"Presión de compra dominante: {presion:.1f}% "
                    f"— Bid side del order book muy cargado"
                ),
            })
        elif presion < PRESION_COMPRA_BAJA:
            alerts.append({
                "type": "SELL_PRESSURE_HIGH",
                "severity": "WARNING",
                "message": (
                    f"Presión de venta dominante: {presion:.1f}% "
                    f"— Ask side del order book muy cargado"
                ),
            })

        # ── 3. Liquidaciones con FILTRO DE MUROS (TRDR) ──────
        liq_longs = float(latest["liquidaciones_longs"])
        liq_shorts = float(latest["liquidaciones_shorts"])
        total_liq = liq_longs + liq_shorts
        depth_buyer = float(latest["orderbook_depth_buyer"])
        depth_seller = float(latest["orderbook_depth_seller"])

        if total_liq > self.umbral_liquidaciones:
            if liq_longs > liq_shorts:
                # 🔴 LIQUIDACIÓN DE LONGS
                # Verificar muro de soporte: depth_buyer debe ser 1.5x depth_seller
                if depth_buyer >= depth_seller * 1.5:
                    alerts.append({
                        "type": "LIQUIDATION_LONGS",
                        "severity": "CRITICAL",
                        "message": (
                            f"🔥 LIQUIDACIÓN LONGS: ${total_liq:,.0f} "
                            f"(umbral: ${self.umbral_liquidaciones:,.0f}) "
                            f"| ✅ MURO SOPORTE: Bids ${depth_buyer:,.0f} "
                            f"> 1.5x Asks ${depth_seller:,.0f}"
                        ),
                    })
                else:
                    # Muro insuficiente → cancelar señal
                    alerts.append({
                        "type": "MURO_FILTER_BLOCK",
                        "severity": "WARNING",
                        "message": (
                            f"🚫 MURO FILTER BLOQUEÓ LIQUIDACIÓN LONGS: "
                            f"Bids ${depth_buyer:,.0f} NO es ≥ 1.5x "
                            f"Asks ${depth_seller:,.0f} — "
                            f"Riesgo de falso rompimiento"
                        ),
                    })
            else:
                # 🔴 LIQUIDACIÓN DE SHORTS
                # Verificar muro de resistencia: depth_seller debe ser 1.5x depth_buyer
                if depth_seller >= depth_buyer * 1.5:
                    alerts.append({
                        "type": "LIQUIDATION_SHORTS",
                        "severity": "CRITICAL",
                        "message": (
                            f"🔥 LIQUIDACIÓN SHORTS: ${total_liq:,.0f} "
                            f"(umbral: ${self.umbral_liquidaciones:,.0f}) "
                            f"| ✅ MURO RESISTENCIA: Asks ${depth_seller:,.0f} "
                            f"> 1.5x Bids ${depth_buyer:,.0f}"
                        ),
                    })
                else:
                    alerts.append({
                        "type": "MURO_FILTER_BLOCK",
                        "severity": "WARNING",
                        "message": (
                            f"🚫 MURO FILTER BLOQUEÓ LIQUIDACIÓN SHORTS: "
                            f"Asks ${depth_seller:,.0f} NO es ≥ 1.5x "
                            f"Bids ${depth_buyer:,.0f} — "
                            f"Riesgo de falso rompimiento"
                        ),
                    })

        # ── 4. Funding Rate ────────────────────────────────────
        fr = (
            float(latest["funding_rate"])
            if latest["funding_rate"]
            else 0
        )
        if abs(fr) > FUNDING_EXTREME:
            direction = (
                "positiva (Longs pagan)"
                if fr > 0
                else "negativa (Shorts pagan)"
            )
            alerts.append({
                "type": "FUNDING_EXTREME",
                "severity": "WARNING",
                "message": (
                    f"Funding Rate extremo: {fr*100:.4f}% ({direction})"
                ),
            })

        return alerts

    def should_alert(self, alert_type):
        now = time.time()
        if alert_type in self.last_alert_time:
            if (
                now - self.last_alert_time[alert_type]
                < self.alert_cooldown
            ):
                return False
        self.last_alert_time[alert_type] = now
        return True

    def log_alerts(self, alerts, precio):
        for alert in alerts:
            if self.should_alert(alert["type"]):
                level = alert["severity"]
                msg = alert["message"]
                prefix = "[DRY RUN]" if self.modo_sistema == "SIMULACION" else "[LIVE]"

                # Mapear severity a tipo para la DB
                tipo_map = {
                    "CRITICAL": "WARNING",
                    "WARNING": "WARNING",
                    "INFO": "INFO",
                }
                alert_type = alert.get("type", "INFO")
                tipo_db = alert_type

                # Persistir en DB
                self.insert_alerta(tipo_db, f"{prefix} {msg}")

                # Consola
                if level == "CRITICAL":
                    log.warning(f"🚨 {prefix} {msg}")
                elif level == "WARNING":
                    log.warning(f"⚠️  {prefix} {msg}")
                else:
                    log.info(f"ℹ️  {prefix} {msg}")

    def log_heartbeat(self, precio, n_registros, alerts_count, depth_buyer=0, depth_seller=0):
        frases = [
            "🧠 Cerebro analítico latiendo",
            "📡 Escaneando metricas_btc",
            "🔍 Analizando señales de mercado",
        ]
        frase = frases[int(time.time()) % len(frases)]
        estado = (
            "🟢 Sin señales"
            if alerts_count == 0
            else f"🔴 {alerts_count} señal(es)"
        )
        modo = f"[{self.modo_sistema}]"
        msg = (
            f"{frase} {modo} | BTC ${precio:,.2f} | "
            f"Registros: {n_registros} | "
            f"Bids: ${depth_buyer:,.0f} | "
            f"Asks: ${depth_seller:,.0f} | "
            f"Liq Umbral: ${self.umbral_liquidaciones:,.0f} | "
            f"{estado}"
        )
        # Persistir heartbeat como evento INFO
        self.insert_alerta("HEARTBEAT", msg)
        log.info(msg)

    def log_position_heartbeat(self):
        """Log periódico del estado de la posición gestionada."""
        ps = self.position_state
        if ps["trade_id"] is None:
            return

        modo = f"[{self.modo_sistema}]"
        side = ps["position_side"]
        estado_sl = "INICIAL"
        if ps["breakeven_activated"]:
            estado_sl = "BREAK-EVEN"
        if ps["trailing_activated"]:
            estado_sl = "TRAILING"

        msg = (
            f"{modo} 📊 Posición #{ps['trade_id']} {side} "
            f"Entry=${ps['entry_price']:.2f} "
            f"SL={estado_sl} @ ${ps['current_sl']:.2f}"
        )
        self.insert_alerta("POSITION_HEARTBEAT", msg)
        log.info(msg)


def main():
    log.info("🧠 Hermes Brain — Cerebro Analítico Cuantitativo")
    log.info("⚙️  Umbrales dinámicos desde hermes_config (DB)")
    log.info("📊 Ventana de análisis: %d min | Ciclo: %ds", WINDOW_MINUTES, ANALYSIS_INTERVAL)
    log.info("🛡️  Gestión de Posiciones: BE@2.5R | Trailing Swing Lows | Time-Out@%dh", MAX_POSITION_HOURS)
    log.info("─────────────────────────────────────────────")

    brain = BrainAnalyzer(DB_CONFIG)
    brain.connect()
    brain.load_config()
    brain.insert_alerta("SYS_START", "🧠 Hermes Brain iniciado — Modo: " + brain.modo_sistema +
                         " | Gestión: BE@2.5R, Trailing, TimeOut@" + str(MAX_POSITION_HOURS) + "h")
    cycle_count = 0

    while True:
        try:
            cycle_count += 1

            # Paso 1: Cargar configuración dinámica desde DB
            brain.load_config()

            # Paso 2: Leer métricas recientes
            rows = brain.get_recent_data()

            if rows:
                latest = rows[0]
                precio = float(latest["precio"])

                # Paso 3: Ejecutar análisis usando umbrales dinámicos
                alerts = brain.analyze(rows)

                # Paso 4: Loggear alertas
                brain.log_alerts(alerts, precio)

                # Paso 5: Gestión de Posiciones (cada POSITION_MGMT_INTERVAL)
                if cycle_count % (POSITION_MGMT_INTERVAL // ANALYSIS_INTERVAL) == 0:
                    mgmt_alerts = brain.manage_positions(rows)
                    if mgmt_alerts:
                        brain.log_alerts(mgmt_alerts, precio)
                    elif brain.position_state["trade_id"] is not None:
                        # Si hay posición abierta pero no hay alertas nuevas, log heartbeat
                        brain.log_position_heartbeat()

                # Heartbeat cada ~15s
                if cycle_count % 3 == 0:
                    db = float(latest["orderbook_depth_buyer"]) if latest.get("orderbook_depth_buyer") else 0
                    ds = float(latest["orderbook_depth_seller"]) if latest.get("orderbook_depth_seller") else 0
                    brain.log_heartbeat(
                        precio, len(rows), len(alerts), db, ds
                    )

            else:
                log.warning(
                    "⚠️  No hay datos en metricas_btc — "
                    "¿el ingestor corre?"
                )

            time.sleep(ANALYSIS_INTERVAL)

        except KeyboardInterrupt:
            log.info("👋 Hermes Brain detenido por el usuario")
            break
        except Exception as e:
            log.error(f"❌ Error en ciclo de análisis: {e}")
            time.sleep(ANALYSIS_INTERVAL)


if __name__ == "__main__":
    main()
