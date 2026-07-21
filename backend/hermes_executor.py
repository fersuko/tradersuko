#!/usr/bin/env python3
"""
hermes_executor.py — Ejecutor de Trading Real.
Script independiente que corre cada 30 segundos.

FLUJO:
  1. Lee metricas_btc (última fila) + hermes_config
  2. Si modo_sistema == 'SIMULACION' → solo log, no ejecuta
  3. Si modo_sistema == 'REAL':
     a. Verifica posiciones abiertas en Binance Futures
     b. Aplica reglas de señal (CVD + Liquidaciones + Muros)
     c. Calcula tamaño (2% balance × apalancamiento)
     d. Ejecuta orden de mercado
     e. Coloca STOP_MARKET (stop-loss)
     f. Registra en hermes_trades
  4. Circuit breaker: máx 10 trades/día

SEGURIDAD:
  - Nunca ejecuta si ya hay posición abierta del mismo lado
  - Verifica balance suficiente antes de cada orden
  - Stop-loss obligatorio post-ejecución
  - Límite diario de trades
"""

import os
import sys
import time
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import ccxt.async_support as ccxt

# ── Cargar entorno (soporta TRADERSUKO_ENV para instancias) ───
_env_path = os.environ.get("TRADERSUKO_ENV")
if _env_path:
    load_dotenv(_env_path)
    print(f"[hermes_executor] 📄 Entorno cargado desde: {_env_path}")
else:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "hermes_trading"),
    "user": os.getenv("DB_USER", "hermes_trader"),
    "password": os.getenv("DB_PASS", "H3rm3s_Tr4d1ng_S3cur3_P4ss_2026!"),
}

SYMBOL = os.getenv("SYMBOL", "BTC/USDT:USDT")
EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
EXCHANGE_SECRET = os.getenv("EXCHANGE_SECRET", "")
EXCHANGE_API_KEY_DEMO = os.getenv("EXCHANGE_API_KEY_DEMO", "")
EXCHANGE_SECRET_DEMO = os.getenv("EXCHANGE_SECRET_DEMO", "")

# URLs Binance Testnet
TESTNET_URLS = {
    "api": {
        "fapiPublic": "https://testnet.binancefuture.com/fapi/v1",
        "fapiPrivate": "https://testnet.binancefuture.com/fapi/v1",
        "fapiPrivateV2": "https://testnet.binancefuture.com/fapi/v2",
    },
    "test": "https://testnet.binancefuture.com",
    "ws": "wss://testnet.binancefuture.com/ws",
}

EXECUTOR_INTERVAL = 30  # segundos entre ciclos
MAX_TRADES_PER_DAY = 5
SLIPPAGE_SL_PCT = Decimal("0.010")  # 1.0% del precio — más espacio para respirar (antes 0.5%)
SLIPPAGE_TP_RATIO = Decimal("6.0")  # Take Profit = SL distancia × ratio (6.0 → 6.0%) — reward:risk 6:1
MAX_POSITION_HOURS = 8  # horas máximas antes de cierre forzado (TP 3% necesita más tiempo)

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hermes_executor")


class Executor:
    """Motor de ejecución de trading real."""

    def __init__(self):
        self.conn = None
        self.exchange = None
        self.modo_sistema = "SIMULACION"
        self.umbral_liquidaciones = 300000.0
        self.delta_cvd_confirmacion = 500000.0
        self.apalancamiento = 5
        self.margen_operacion = 2.0
        self.last_sl_time = 0  # timestamp del último stop-loss
        self.sl_cooldown = 180  # 3 min de espera tras un stop-loss (antes 10 min)
        self.last_sim_trade_time = 0  # control duplicados en SIMULACION
        self.trend_filter_enabled = False  # Filtro VWAP desactivado — el order flow 3/3 es suficiente

    # ── Conexiones ────────────────────────────────────────────
    def connect_db(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(**DB_CONFIG)
            self.conn.autocommit = False
            log.info("✅ Executor conectado a PostgreSQL")

    async def connect_exchange(self):
        """Conecta a Binance Futures según el modo actual."""
        modo = self.modo_sistema
        api_key = None
        api_secret = None
        urls = None
        label = ""

        if modo == "REAL":
            api_key = EXCHANGE_API_KEY
            api_secret = EXCHANGE_SECRET
            label = "Binance Futures REAL"
        elif modo == "DEMO":
            api_key = EXCHANGE_API_KEY_DEMO
            api_secret = EXCHANGE_SECRET_DEMO
            label = "Binance Testnet DEMO"
            urls = TESTNET_URLS

        if not api_key or not api_secret:
            log.info(
                f"🔑 API keys para {modo} no configuradas — "
                f"modo solo simulación"
            )
            return False

        try:
            exchange_config = {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "future",
                },
            }
            if urls:
                exchange_config["urls"] = urls

            self.exchange = ccxt.binanceusdm(exchange_config)

            # Verificar conexión obteniendo balance
            balance = await self.exchange.fetch_balance()
            balance_usdt = float(
                balance.get("USDT", {}).get("free", 0)
            )
            log.info(
                f"✅ Executor conectado a {label} — "
                f"Balance USDT: ${balance_usdt:.2f}"
            )

            # Configurar apalancamiento
            try:
                await self.exchange.set_leverage(self.apalancamiento, SYMBOL)
                log.info(
                    f"⚙️  Apalancamiento configurado: "
                    f"{self.apalancamiento}x en {SYMBOL}"
                )
            except Exception as e:
                log.warning(
                    f"⚠️ Error configurando apalancamiento: {e}"
                )

            # Cancelar órdenes STOP/TP huérfanas
            await self.cancel_stale_orders()

            return True
        except Exception as e:
            log.error(f"❌ Error conectando a {label}: {e}")
            return False

    # ── Carga de configuración desde DB ───────────────────────
    def load_config(self):
        try:
            self.connect_db()
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
                self.apalancamiento = int(row.get("apalancamiento", 10))
                self.margen_operacion = float(row.get("margen_operacion", 2.0))
                self.modo_sistema = str(row.get("modo_sistema", "SIMULACION"))
                # Permitir override vía variable de entorno (para testnet)
                _modo_env = os.environ.get("TRADERSUKO_MODO")
                if _modo_env:
                    self.modo_sistema = _modo_env
                    log.info(f"🔧 Modo sobreescrito por TRADERSUKO_MODO: {_modo_env}")
        except Exception as e:
            log.warning(f"⚠️ Error cargando config: {e}")

    # ── Persistencia ──────────────────────────────────────────
    def insert_alerta(self, tipo: str, mensaje: str):
        try:
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO hermes_alertas (tipo, mensaje) VALUES (%s, %s)",
                    (tipo, mensaje),
                )
            self.conn.commit()
        except Exception as e:
            log.warning(f"⚠️ Error insertando alerta: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass

    def register_trade(self, data: dict):
        """Inserta un registro en hermes_trades."""
        try:
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hermes_trades (
                        tipo, simbolo, lado, cantidad_btc, precio_entrada,
                        valor_usd, apalancamiento_usado, margen_usado,
                        stop_loss, take_profit, estado, modo, razon, signal_tipo,
                        balance_antes
                    ) VALUES (
                        %(tipo)s, %(simbolo)s, %(lado)s, %(cantidad_btc)s,
                        %(precio_entrada)s, %(valor_usd)s,
                        %(apalancamiento_usado)s, %(margen_usado)s,
                        %(stop_loss)s, %(take_profit)s, %(estado)s, %(modo)s, %(razon)s,
                        %(signal_tipo)s, %(balance_antes)s
                    )
                    """,
                    data,
                )
            self.conn.commit()
            log.info(
                f"📝 Trade registrado: {data['lado']} "
                f"${data['valor_usd']:.2f} @ {data['precio_entrada']}"
            )
        except Exception as e:
            log.error(f"❌ Error registrando trade: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass

    # ── Lectura de métricas ───────────────────────────────────
    def get_latest_metrics(self):
        """Obtiene la última fila de metricas_btc."""
        try:
            self.connect_db()
            with self.conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    "SELECT * FROM metricas_btc ORDER BY timestamp DESC LIMIT 1"
                )
                return cur.fetchone()
        except Exception as e:
            log.error(f"❌ Error leyendo métricas: {e}")
            return None

    # ── Filtro de Tendencia (VWAP) ────────────────────────────
    def get_vwap(self, lookback_minutes=5):
        """Calcula VWAP desde la DB usando volumen real de las velas 1m.
        
        Toma las últimas N filas de metricas_btc, agrupa por minuto,
        toma la última fila de cada minuto (máximo volumen acumulado),
        y calcula VWAP = Σ(precio × volumen) / Σ(volumen).
        """
        try:
            self.connect_db()
            # Tomar ~lookback_minutes * 12 filas (insert cada ~5s) como buffer
            limit_rows = lookback_minutes * 15
            with self.conn.cursor() as cur:
                cur.execute(
                    f"SELECT precio, volumen, timestamp FROM metricas_btc "
                    f"WHERE precio > 0 AND volumen > 0 "
                    f"ORDER BY timestamp DESC LIMIT {limit_rows}"
                )
                rows = cur.fetchall()
            
            if len(rows) < 6:
                log.info(f"📊 VWAP: solo {len(rows)} filas con volumen — saltando filtro")
                return None
            
            # Agrupar por minuto y tomar la última fila de cada minuto
            minute_groups = {}
            for precio, vol, ts in rows:
                minute_key = ts.replace(second=0, microsecond=0)
                # Siempre reemplazar = nos quedamos con la última de cada minuto
                minute_groups[minute_key] = (float(precio), float(vol))
            
            if len(minute_groups) < 2:
                log.info(f"📊 VWAP: solo {len(minute_groups)} minutos con datos — saltando filtro")
                return None
            
            # Calcular VWAP: Σ(precio × volumen) / Σ(volumen)
            precio_vol_sum = 0.0
            vol_sum = 0.0
            for precio, vol in minute_groups.values():
                precio_vol_sum += precio * vol
                vol_sum += vol
            
            vwap = precio_vol_sum / vol_sum
            
            # Último precio de referencia (la fila más reciente)
            ultimo_precio = float(rows[0][0])
            
            log.info(
                f"📊 VWAP({lookback_minutes}min, {len(minute_groups)} velas): "
                f"${vwap:.2f} (precio: ${ultimo_precio:.2f}, "
                f"diff: ${ultimo_precio-vwap:+.2f}, "
                f"vol total: {vol_sum:,.0f} BTC)"
            )
            return vwap
        except Exception as e:
            log.warning(f"⚠️ Error calculando VWAP: {e}")
            return None

    # ── Evaluación de señal ───────────────────────────────────
    def get_liquidations_last_minute(self):
        """Suma liquidaciones de los últimos 60 segundos."""
        try:
            self.connect_db()
            with self.conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(liquidaciones_longs), 0) as total_longs,
                        COALESCE(SUM(liquidaciones_shorts), 0) as total_shorts
                    FROM metricas_btc
                    WHERE timestamp > NOW() - INTERVAL '1 minute'
                    """
                )
                row = cur.fetchone()
                return float(row["total_longs"]), float(row["total_shorts"])
        except Exception:
            return 0, 0

    def evaluate_signal(self, row):
        """
        Evalúa si hay señal de trading usando sistema 2-de-3 condiciones.
        Las liquidaciones se suman en ventana de 1 minuto (no solo última fila).
        Retorna (tipo_señal, razon) o (None, None).
        """
        if not row:
            return None, None

        precio = float(row.get("precio", 0))
        cvd = float(row.get("cvd_binance", 0) or 0)
        depth_b = float(row.get("orderbook_depth_buyer", 0) or 0)
        depth_s = float(row.get("orderbook_depth_seller", 0) or 0)

        # Liquidaciones: ventana de 1 minuto (acumulado)
        liq_longs_1m, liq_shorts_1m = self.get_liquidations_last_minute()
        total_liq_1m = liq_longs_1m + liq_shorts_1m

        liq_ok = total_liq_1m >= self.umbral_liquidaciones

        # Diagnóstico: mostrar condiciones actuales
        log.info(
            f"📊 Evaluando: CVD=${abs(cvd):,.0f} (umbral=${self.delta_cvd_confirmacion:,.0f}) | "
            f"Liq 1m=${total_liq_1m:,.0f} (umbral=${self.umbral_liquidaciones:,.0f}) | "
            f"Bids=${depth_b:,.0f} Asks=${depth_s:,.0f}"
        )

        # ── Filtro de Tendencia VWAP ──────────────────────
        # Si el precio está sobre el VWAP → sesgo alcista (solo LONG)
        # Si el precio está bajo el VWAP → sesgo bajista (solo SHORT)
        trend = None  # None = sin restricción, "LONG_ONLY" o "SHORT_ONLY"
        if self.trend_filter_enabled:
            vwap = self.get_vwap(lookback_minutes=5)
            if vwap is not None:
                if precio > vwap:
                    trend = "LONG_ONLY"
                    log.info(f"📈 Tendencia ALCISTA: precio ${precio:.2f} > VWAP ${vwap:.2f} — solo LONG permitido")
                elif precio < vwap:
                    trend = "SHORT_ONLY"
                    log.info(f"📉 Tendencia BAJISTA: precio ${precio:.2f} < VWAP ${vwap:.2f} — solo SHORT permitido")
                else:
                    log.info(f"📊 Tendencia NEUTRA: precio ${precio:.2f} ≈ VWAP ${vwap:.2f}")
            else:
                log.info("📊 VWAP no disponible — filtro de tendencia desactivado temporalmente")
        else:
            log.info("📊 Filtro de tendencia desactivado (trend_filter_enabled=False)")

        # ── SEÑAL LONG ────────────────────────────────────────
        # Condiciones (necesita 2 de 3):
        #  A) CVD momentum alcista (delta > umbral)
        #  B) Muro de compras domina (bids >= 1.5x asks)
        #  C) Liquidación de shorts fuerte
        condiciones_long = 0
        razones_long = []

        if cvd > 0 and abs(cvd) >= self.delta_cvd_confirmacion:
            condiciones_long += 1
            razones_long.append(f"CVD+ ${abs(cvd):,.0f}")

        if depth_b >= depth_s * 2.0 and depth_s > 0:
            condiciones_long += 1
            ratio_ob = round(depth_b / depth_s, 2) if depth_s > 0 else 0
            razones_long.append(f"Bids {ratio_ob:.1f}x Asks")

        if liq_ok and liq_shorts_1m > liq_longs_1m:
            condiciones_long += 1
            razones_long.append(f"Liq Shorts ${liq_shorts_1m:,.0f}")

        if condiciones_long >= 3:
            # Filtro de tendencia
            if trend == "SHORT_ONLY":
                log.info(
                    f"🚫 Señal LONG ({condiciones_long}/3) BLOQUEADA por tendencia bajista — "
                    f"solo SHORT permitido"
                )
                return None, None
            return "LONG", (
                f"Señal LONG ({condiciones_long}/3): "
                f"{' | '.join(razones_long)}"
            )

        # ── SEÑAL SHORT ───────────────────────────────────────
        condiciones_short = 0
        razones_short = []

        if cvd < 0 and abs(cvd) >= self.delta_cvd_confirmacion:
            condiciones_short += 1
            razones_short.append(f"CVD- ${abs(cvd):,.0f}")

        if depth_s >= depth_b * 2.0 and depth_b > 0:
            condiciones_short += 1
            ratio_ob = round(depth_s / depth_b, 2) if depth_b > 0 else 0
            razones_short.append(f"Asks {ratio_ob:.1f}x Bids")

        if liq_ok and liq_longs_1m > liq_shorts_1m:
            condiciones_short += 1
            razones_short.append(f"Liq Longs ${liq_longs_1m:,.0f}")

        if condiciones_short >= 3:
            # Filtro de tendencia
            if trend == "LONG_ONLY":
                log.info(
                    f"🚫 Señal SHORT ({condiciones_short}/3) BLOQUEADA por tendencia alcista — "
                    f"solo LONG permitido"
                )
                return None, None
            return "SHORT", (
                f"Señal SHORT ({condiciones_short}/3): "
                f"{' | '.join(razones_short)}"
            )

        return None, None

    # ── Cancelar órdenes abiertas al inicio ─────────────────
    async def cancel_stale_orders(self):
        """Cancela órdenes STOP/TP huérfanas al iniciar."""
        if not self.exchange:
            return
        try:
            orders = await self.exchange.fetch_open_orders(SYMBOL)
            if orders:
                log.warning(f"🗑️ Cancelando {len(orders)} órdenes abiertas previas...")
                for o in orders:
                    try:
                        await self.exchange.cancel_order(o["id"], SYMBOL)
                        log.info(f"   ✅ Cancelada orden #{o['id']} ({o['type']} {o['side']})")
                    except Exception as e:
                        log.warning(f"   ⚠️ No se pudo cancelar #{o['id']}: {e}")
            else:
                log.info("✅ Sin órdenes abiertas previas — limpio")
        except Exception as e:
            log.warning(f"⚠️ Error cancelando órdenes: {e}")

    # ── Verificación de posición abierta ──────────────────────
    async def has_open_position(self, side: str) -> bool:
        """
        Verifica si ya tenemos una posición abierta del lado indicado.
        Retorna True si ya hay posición.
        """
        if not self.exchange:
            return False

        try:
            # Primero: verificar en exchange
            if self.exchange:
                try:
                    positions = await self.exchange.fetch_positions([SYMBOL])
                    for pos in positions:
                        # Binance testnet usa distintos field names
                        size = float(pos.get("contracts", 0) or 
                                     pos.get("positionAmt", 0) or 
                                     pos.get("size", 0) or 0)
                        if abs(size) > 0:
                            pos_side = "long" if size > 0 else "short"
                            if pos_side == side.lower():
                                log.info(
                                    f"🔒 Posición {side.upper()} ya abierta en exchange: "
                                    f"{abs(size):.4f} BTC"
                                )
                                return True
                except Exception as e:
                    log.warning(f"⚠️ Error checkeando exchange: {e}")

            # Segundo: verificar en DB por si el exchange no reporta
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM hermes_trades
                    WHERE estado = 'EJECUTADO'
                    AND lado = %s
                """, (side.upper(),))
                count = cur.fetchone()[0]
                if count > 0:
                    log.info(f"🔒 {count} trade(s) {side} activo(s) en DB")
                    return True

            return False
        except Exception as e:
            log.warning(f"⚠️ Error verificando posiciones: {e}")
            return False  # Si falla, asumimos que no hay posición (fail safe)

    # ── Control de duplicados temporales ─────────────────────
    def has_recent_trade(self, side: str, seconds: int = 30) -> bool:
        """Verifica si ya se abrió un trade del mismo lado en los últimos N segundos.
        Previene entradas duplicadas por signals repetidas."""
        try:
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM hermes_trades
                    WHERE lado = %s
                    AND estado NOT IN ('FALLIDO', 'CANCELADO')
                    AND timestamp > NOW() - INTERVAL '%s seconds'
                """, (side.upper(), seconds))
                count = cur.fetchone()[0]
                if count > 0:
                    log.info(f"⏭️ Trade {side} reciente detectado ({count} en {seconds}s) — saltando duplicado")
                    return True
            return False
        except Exception as e:
            log.warning(f"⚠️ Error en has_recent_trade: {e}")
            return False

    # ── Circuit breaker ───────────────────────────────────────
    def circuit_breaker(self) -> bool:
        """
        Verifica si podemos ejecutar otro trade según límite diario.
        Retorna True si podemos ejecutar, False si está bloqueado.
        """
        try:
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM hermes_trades
                    WHERE timestamp > NOW() - INTERVAL '24 hours'
                    AND estado NOT IN ('SIMULADO', 'CLOSED', 'CLOSED_FORCE', 'FALLIDO', 'CANCELADO')
                    AND modo = 'REAL'
                    """
                )
                count = cur.fetchone()[0]
            if count >= MAX_TRADES_PER_DAY:
                log.warning(
                    f"🚫 Circuit breaker activo: {count}/{MAX_TRADES_PER_DAY} "
                    f"trades en 24h"
                )
                return False
            log.info(
                f"🔓 Circuit breaker OK: {count}/{MAX_TRADES_PER_DAY} trades en 24h"
            )
            return True
        except Exception as e:
            log.warning(f"⚠️ Error en circuit breaker: {e}")
            return False

    # ── Cálculo de tamaño de posición ─────────────────────────
    async def calculate_position_size(self, precio: float) -> dict:
        """
        Calcula el tamaño de posición basado en % del balance.
        Retorna {cantidad_btc, valor_usd, margen_usado, balance_antes}
        """
        balance_antes = 0
        try:
            if self.exchange:
                balance = await self.exchange.fetch_balance()
                balance_antes = float(
                    balance.get("USDT", {}).get("free", 0)
                )
            else:
                # Simulación: balance ficticio
                balance_antes = 10000.0
                log.info(f"💰 Balance simulado: ${balance_antes:.2f} USDT")

            # Margen a usar como % del balance
            margen_usd = balance_antes * (self.margen_operacion / 100)

            # Valor total de la posición con apalancamiento
            valor_usd = margen_usd * self.apalancamiento

            # Cantidad de BTC
            MIN_BTC = Decimal("0.001")
            if precio > 0:
                cantidad_btc = Decimal(str(valor_usd)) / Decimal(str(precio))
            else:
                cantidad_btc = Decimal("0")

            # Redondear a satoshi (8 decimales para futuros)
            cantidad_btc = cantidad_btc.quantize(Decimal("0.00001"))

            # Asegurar mínimo 0.001 BTC (exigencia de Binance Futures)
            if cantidad_btc < MIN_BTC and balance_antes > 0:
                cantidad_btc = MIN_BTC
                # Recalcular margen y valor real
                valor_usd = float(cantidad_btc) * precio
                margen_usd = valor_usd / self.apalancamiento
                log.info(f"📐 Ajustado a mínimo 0.001 BTC: ${valor_usd:.2f} pos | margen ${margen_usd:.2f} ({margen_usd/balance_antes*100:.1f}% del balance)")

            return {
                "cantidad_btc": float(cantidad_btc),
                "valor_usd": round(valor_usd, 2),
                "margen_usado": round(margen_usd, 2),
                "balance_antes": round(balance_antes, 2),
            }
        except Exception as e:
            log.error(f"❌ Error calculando tamaño: {e}")
            return {
                "cantidad_btc": 0.001,
                "valor_usd": 0,
                "margen_usado": 0,
                "balance_antes": round(balance_antes, 2),
            }

    # ── Ejecución de orden ────────────────────────────────────
    async def execute_order(
        self, side: str, cantidad_btc: float, precio_actual: float, razon: str
    ) -> dict:
        """
        Ejecuta orden de mercado en Binance Futures.
        Si no hay exchange conectado (simulación), solo registra.
        """
        modo = self.modo_sistema
        resultado = {
            "tipo": "SIMULACION",
            "lado": side,
            "cantidad_btc": cantidad_btc,
            "precio_entrada": precio_actual,
            "stop_loss": 0,
            "estado": "SIMULADO",
            "razon": razon,
            "signal_tipo": f"EXEC_{side}",
            "orden_id": None,
        }

        # Validar cantidad mínima antes de ejecutar
        if cantidad_btc < 0.001:
            log.warning(f"⚠️ Cantidad {cantidad_btc:.5f} BTC < mínimo 0.001 — abortando ejecución")
            resultado["estado"] = "FALLIDO"
            resultado["razon"] = f"Cantidad {cantidad_btc:.5f} BTC menor al mínimo 0.001"
            return resultado

        if modo not in ("REAL", "DEMO"):
            log.info(
                f"🧪 [SIMULACION] {side} {cantidad_btc:.5f} BTC "
                f"@ ${precio_actual:.2f} | {razon}"
            )
            self.insert_alerta(
                "SIM_EXEC",
                f"[SIMULACION] {side} {cantidad_btc:.5f} BTC "
                f"@ ${precio_actual:.2f} | {razon}",
            )
            return resultado

        # ── MODO REAL / DEMO ────────────────────────────────────
        label = "TESTNET" if modo == "DEMO" else "REAL"
        if not self.exchange:
            log.error(f"❌ Exchange no conectado — no se puede ejecutar")
            return resultado

        try:
            order_type = "market"
            order_side = "buy" if side == "LONG" else "sell"

            # ── Estrategia híbrida: LIMIT postOnly → fallback MARKET ──
            # Maker fee 0.02% vs Taker fee 0.04% — ahorro del 50%
            limit_price = None
            try:
                orderbook = await self.exchange.fetch_order_book(SYMBOL, limit=5)
                if order_side == "buy":  # LONG → comprar al ask
                    limit_price = float(orderbook["asks"][0][0]) if orderbook.get("asks") else None
                else:  # SHORT → vender al bid
                    limit_price = float(orderbook["bids"][0][0]) if orderbook.get("bids") else None
            except Exception as e:
                log.warning(f"⚠️ No se pudo obtener orderbook para LIMIT: {e}")

            if limit_price and limit_price > 0:
                # Intentar LIMIT con postOnly + IOC (maker fee ~0.02%)
                # IOC = Immediate-or-Cancel: o se llena al instante o se cancela sola
                log.info(
                    f"🔥 EJECUTANDO {side} {label} vía LIMIT IOC: "
                    f"{cantidad_btc:.5f} BTC @ ${limit_price:.2f} | Razón: {razon}"
                )
                try:
                    order = await self.exchange.create_order(
                        symbol=SYMBOL,
                        type="LIMIT",
                        side=order_side,
                        amount=cantidad_btc,
                        price=limit_price,
                        params={"timeInForce": "IOC"},
                    )
                    status = order.get("status", "")
                    filled = float(order.get("filled", 0) or 0)
                    if status == "closed" or filled >= cantidad_btc * 0.99:
                        price_filled = float(
                            order.get("average") or order.get("price") or limit_price
                        )
                        order_id = order.get("id", "unknown")
                        log.info(f"✅ LIMIT postOnly EJECUTADA ID: {order_id} @ ${price_filled:.2f} (maker fee!)")
                    else:
                        # No se llenó como maker — fallback inmediato a MARKET (sin polling)
                        log.info(f"⏳ LIMIT postOnly no llenó como maker — fallback a MARKET")
                        order = await self.exchange.create_order(
                            symbol=SYMBOL,
                            type="market",
                            side=order_side,
                            amount=cantidad_btc,
                            params={},
                        )
                        price_filled = float(
                            order.get("price") or order.get("average") or precio_actual
                        )
                        order_id = order.get("id", "unknown")
                        log.info(f"✅ FALLBACK MARKET EJECUTADA ID: {order_id} @ ${price_filled:.2f} (taker fee)")
                except Exception as limit_err:
                    # Si falla LIMIT, ir directo a MARKET
                    log.warning(f"⚠️ Falló LIMIT postOnly ({limit_err}) — fallback a MARKET")
                    order = await self.exchange.create_order(
                        symbol=SYMBOL,
                        type="market",
                        side=order_side,
                        amount=cantidad_btc,
                        params={},
                    )
                    price_filled = float(
                        order.get("price") or order.get("average") or precio_actual
                    )
                    order_id = order.get("id", "unknown")
                    log.info(f"✅ MARKET EJECUTADA ID: {order_id} @ ${price_filled:.2f} (taker fee)")
            else:
                # No hay orderbook disponible — MARKET directo
                log.info(
                    f"🔥 EJECUTANDO {side} {label} vía MARKET directo: "
                    f"{cantidad_btc:.5f} BTC @ Mercado | Razón: {razon}"
                )
                order = await self.exchange.create_order(
                    symbol=SYMBOL,
                    type="market",
                    side=order_side,
                    amount=cantidad_btc,
                    params={},
                )
                price_filled = float(
                    order.get("price") or order.get("average") or precio_actual
                )
                order_id = order.get("id", "unknown")
                log.info(f"✅ ORDEN MARKET EJECUTADA ID: {order_id} @ ${price_filled:.2f} (taker fee)")

            resultado.update({
                "tipo": "REAL",
                "precio_entrada": price_filled,
                "estado": "EJECUTADO",
                "orden_id": order_id,
            })

            log.info(f"✅ ORDEN EJECUTADA ID: {order_id} @ ${price_filled:.2f}")

            # ── Colocar STOP-LOSS ──────────────────────────────
            sl_price = await self.place_stop_loss(side, cantidad_btc, price_filled)
            resultado["stop_loss"] = sl_price

            # ── Colocar TAKE-PROFIT ────────────────────────────
            tp_price = await self.place_take_profit(side, cantidad_btc, price_filled)
            resultado["take_profit"] = tp_price

            self.insert_alerta(
                "TRADE_EXECUTED",
                f"[REAL] {side} {cantidad_btc:.5f} BTC @ ${price_filled:.2f} | "
                f"ID: {order_id} | {razon}",
            )

        except Exception as e:
            log.error(f"❌ Error ejecutando orden {side}: {e}")
            resultado["estado"] = "FALLIDO"
            resultado["razon"] = str(e)

            self.insert_alerta(
                "EXEC_ERROR",
                f"❌ Fallo ejecutando {side}: {str(e)}",
            )

        return resultado

    # ── Stop-Loss ─────────────────────────────────────────────
    async def place_stop_loss(
        self, side: str, cantidad_btc: float, precio_entrada: float
    ):
        """
        Registra el precio de STOP-LOSS en DB solamente.
        check_sl_tp() monitorea LOCALMENTE y cierra con market order.
        (No se coloca orden en Binance para evitar condicionales huérfanas.)
        """
        try:
            if side == "LONG":
                stop_price = precio_entrada * (1 - float(SLIPPAGE_SL_PCT))
            else:
                stop_price = precio_entrada * (1 + float(SLIPPAGE_SL_PCT))

            log.info(
                f"🛡️ SL LOCAL {side}: ${stop_price:.2f} "
                f"({float(SLIPPAGE_SL_PCT)*100:.2f}% del entry)"
            )

            # Persistir SL en DB
            try:
                self.connect_db()
                with self.conn.cursor() as cur:
                    cur.execute(
                        "UPDATE hermes_trades SET stop_loss = %s WHERE id = (SELECT MAX(id) FROM hermes_trades WHERE estado = 'EJECUTADO')",
                        (round(stop_price, 2),),
                    )
                self.conn.commit()
                log.info(f"✅ SL registrado en DB: ${stop_price:.2f}")
            except Exception as e:
                log.warning(f"⚠️ Error guardando SL en DB: {e}")

            self.insert_alerta(
                "STOP_LOSS_SET",
                f"🛡️ SL {side} @ ${stop_price:.2f} (local)",
            )

            import time as _t
            self.last_sl_time = _t.time()
            return stop_price

        except Exception as e:
            log.error(f"❌ Error calculando STOP_LOSS: {e}")
            self.insert_alerta(
                "SL_ERROR",
                f"❌ Fallo STOP_LOSS {side}: {str(e)}",
            )
            import time as _t
            self.last_sl_time = _t.time()
            return 0

    # ── Take-Profit ────────────────────────────────────────────
    async def place_take_profit(
        self, side: str, cantidad_btc: float, precio_entrada: float
    ):
        """
        Registra el precio de TAKE-PROFIT en DB solamente.
        check_sl_tp() monitorea LOCALMENTE y cierra con market order.
        (No se coloca orden en Binance para evitar condicionales huérfanas.)
        """
        try:
            tp_distance_pct = float(SLIPPAGE_SL_PCT * SLIPPAGE_TP_RATIO)
            if side == "LONG":
                tp_price = precio_entrada * (1 + tp_distance_pct)
            else:
                tp_price = precio_entrada * (1 - tp_distance_pct)

            log.info(
                f"🎯 TP LOCAL {side}: ${tp_price:.2f} "
                f"({tp_distance_pct*100:.2f}% de ganancia potencial)"
            )

            # Persistir TP en DB
            try:
                self.connect_db()
                with self.conn.cursor() as cur:
                    cur.execute(
                        "UPDATE hermes_trades SET take_profit = %s WHERE id = (SELECT MAX(id) FROM hermes_trades WHERE estado = 'EJECUTADO')",
                        (round(tp_price, 2),),
                    )
                self.conn.commit()
                log.info(f"✅ TP registrado en DB: ${tp_price:.2f}")
            except Exception as e:
                log.warning(f"⚠️ Error guardando TP en DB: {e}")

            self.insert_alerta(
                "TAKE_PROFIT_SET",
                f"🎯 TP {side} @ ${tp_price:.2f} (local)",
            )

            return tp_price

        except Exception as e:
            log.warning(f"⚠️ Error calculando TAKE_PROFIT: {e}")
            self.insert_alerta(
                "TP_ERROR",
                f"⚠️ Fallo TAKE_PROFIT {side}: {str(e)} — TP no colocado",
            )
            return 0

    # ── Gestión de Posiciones (desde Brain) ────────────────────
    async def cancel_and_replace_sl(self, trade_id: int, new_sl_price: float, side: str, amount: float):
        """
        Actualiza el SL de un trade en BD.
        Incluye protección: no deja que el trailing SL se acerque a menos de 0.15% del precio actual
        para evitar micro-cierres por trailing demasiado agresivo.
        check_sl_tp() se encarga de monitorear y ejecutar el cierre localmente.
        """
        try:
            # ── Protección: verificar que el SL no esté demasiado cerca del precio actual ──
            try:
                if self.exchange:
                    ticker = await self.exchange.fetch_ticker(SYMBOL)
                    mark_price = float(ticker.get("markPrice") or ticker.get("last", 0))
                    min_buffer = mark_price * 0.0025  # 0.25% de buffer mínimo (antes 0.15%)
                    
                    # Para LONG: SL debe estar por debajo del precio
                    # Para SHORT: SL debe estar por encima del precio
                    if side == "LONG":
                        distance = mark_price - new_sl_price
                        if distance < min_buffer and distance > 0:
                            adjusted_sl = mark_price - min_buffer
                            log.warning(f"🛡️ SL #{trade_id} muy cerca (${distance:.2f} < ${min_buffer:.2f}) — ajustando a ${adjusted_sl:.2f}")
                            new_sl_price = adjusted_sl
                    elif side == "SHORT":
                        distance = new_sl_price - mark_price
                        if distance < min_buffer and distance > 0:
                            adjusted_sl = mark_price + min_buffer
                            log.warning(f"🛡️ SL #{trade_id} muy cerca (${distance:.2f} < ${min_buffer:.2f}) — ajustando a ${adjusted_sl:.2f}")
                            new_sl_price = adjusted_sl
            except Exception as e:
                log.warning(f"⚠️ Error en buffer trailing: {e}")

            # 1. Actualizar SL en BD (esto es lo que realmente importa)
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE hermes_trades SET stop_loss = %s WHERE id = %s",
                    (round(new_sl_price, 1), trade_id),
                )
                self.conn.commit()
            log.info(f"📝 SL #{trade_id} actualizado en BD: ${new_sl_price:.2f}")

            # 2. NO colocar en Binance (check_sl_tp() maneja localmente)
            log.info(f"📝 SL #{trade_id} local — check_sl_tp() lo monitoreará en cada ciclo")

            self.insert_alerta(
                "SL_UPDATED",
                f"🛡️ SL #{trade_id} actualizado → ${new_sl_price:.2f} | Break-Even/Trailing",
            )
            return True

        except Exception as e:
            log.error(f"❌ Error actualizando SL #{trade_id}: {e}")
            return False

    async def force_close_position(self, trade_id: int, side: str, amount: float, reason: str):
        """
        Cierra una posición forzadamente con orden de mercado.
        Se usa cuando el Brain ordena Time-Out.
        """
        try:
            if not self.exchange:
                log.warning("⚠️ Exchange no conectado — no se puede cerrar posición")
                return False

            # Cancelar TODAS las órdenes (incluyendo condicionales invisibles)
            try:
                import requests as _req, json as _json, time as _time
                import hashlib as _hl, hmac as _hm, urllib.parse as _up
                _ts = int(_time.time() * 1000)
                _params = {"symbol": "BTCUSDT", "timestamp": _ts}
                _qs = _up.urlencode(sorted(_params.items()))
                _sig = _hm.new(self.exchange.secret.encode(), _qs.encode(), _hl.sha256).hexdigest()
                _url = f"https://fapi.binance.com/fapi/v1/allOpenOrders?{_qs}&signature={_sig}"
                _r = _req.delete(_url, headers={"X-MBX-APIKEY": self.exchange.apiKey})
                if _r.status_code == 200:
                    _result = _r.json()
                    if isinstance(_result, dict) and _result.get("code") == 0:
                        log.warning(f"🗑️ Canceladas TODAS las órdenes incluyendo condicionales")
                    elif isinstance(_result, list):
                        log.warning(f"🗑️ Canceladas {len(_result)} órdenes vía allOpenOrders")
                else:
                    log.warning(f"⚠️ Fallback a fetch_open_orders (status {_r.status_code})")
                    raise Exception("REST falló, usando ccxt")
            except Exception:
                # Fallback: ccxt (no ve condicionales pero mejor que nada)
                try:
                    open_orders = await self.exchange.fetch_open_orders(SYMBOL)
                    if open_orders:
                        log.warning(f"🗑️ Cancelando {len(open_orders)} órdenes visibles (fallback)...")
                        for o in open_orders:
                            try:
                                await self.exchange.cancel_order(o["id"], SYMBOL)
                            except Exception:
                                pass
                except Exception:
                    pass

            close_side = "sell" if side == "LONG" else "buy"
            log.warning(f"⏰ CERRANDO POSICIÓN #{trade_id} {side}: {amount:.5f} BTC @ Mercado | Razón: {reason}")

            try:
                close_order = await self.exchange.create_order(
                    symbol=SYMBOL,
                    type="market",
                    side=close_side,
                    amount=amount,
                    params={"reduceOnly": True},
                )
            except Exception as close_err:
                err_str = str(close_err)
                # Si el error es "ReduceOnly Order is rejected", la posición ya no existe
                if "ReduceOnly" in err_str or "-2022" in err_str:
                    log.warning(f"⚠️ Posición #{trade_id} ya no existe en exchange (ReduceOnly rejected) — solo se marca en BD")
                    # Marcar como cerrado en BD porque la posición ya no existe
                    try:
                        self.connect_db()
                        with self.conn.cursor() as cur:
                            cur.execute(
                                "UPDATE hermes_trades SET estado = 'CLOSED_FORCE', balance_despues = balance_antes + COALESCE(pnl_realizado, 0) WHERE id = %s",
                                (trade_id,),
                            )
                        self.conn.commit()
                        log.info(f"📝 Trade #{trade_id} marcado como CLOSED_FORCE en DB (posición expirada)")
                    except Exception as e:
                        log.warning(f"⚠️ Error actualizando estado en DB: {e}")
                    return False
                else:
                    # Error REAL de cierre: NO marcar CLOSED_FORCE para evitar posiciones fantasma
                    log.error(f"❌ Error cerrando posición #{trade_id}: {close_err}")
                    self.insert_alerta(
                        "FORCE_CLOSE_ERROR",
                        f"❌ Fallo cierre forzado #{trade_id}: {str(close_err)} — posición NO marcada como cerrada",
                    )
                    # Verificar si la posición sigue en Binance
                    try:
                        posiciones = await self.exchange.fetch_positions([SYMBOL])
                        for p in posiciones:
                            contracts = float(p.get("contracts", 0) or p.get("positionAmt", 0) or 0)
                            if abs(contracts) > 0:
                                pos_side = "LONG" if contracts > 0 else "SHORT"
                                if pos_side == side:
                                    log.warning(f"⚠️ Posición sigue activa en exchange: {abs(contracts):.3f} BTC {side} — manteniendo EJECUTADO en DB")
                                    return False
                        # Si no hay posición, marcar como cerrado
                        self.connect_db()
                        with self.conn.cursor() as cur:
                            cur.execute(
                                "UPDATE hermes_trades SET estado = 'CLOSED_FORCE', balance_despues = balance_antes + COALESCE(pnl_realizado, 0) WHERE id = %s",
                                (trade_id,),
                            )
                        self.conn.commit()
                        log.info(f"📝 Trade #{trade_id} marcado como CLOSED_FORCE en DB (posición ya no existe en exchange)")
                    except Exception as e2:
                        log.warning(f"⚠️ Error verificando posición en exchange: {e2}")
                    return False

            order_id = close_order.get("id", "unknown")
            fill_price = float(close_order.get("price", 0) or close_order.get("average", 0) or 0)
            log.warning(f"✅ POSICIÓN #{trade_id} CERRADA ID: {order_id} @ ${fill_price:.2f}")

            self.insert_alerta(
                "POSITION_CLOSED",
                f"⏰ Cierre forzado #{trade_id} {side}: "
                f"{amount:.5f} BTC @ ${fill_price:.2f} | Razón: {reason}",
            )

            # Marcar el trade como cerrado en DB
            try:
                self.connect_db()
                with self.conn.cursor() as cur:
                    cur.execute(
                        "UPDATE hermes_trades SET estado = 'CLOSED_FORCE' WHERE id = %s",
                        (trade_id,),
                    )
                self.conn.commit()
                log.info(f"📝 Trade #{trade_id} marcado como CLOSED_FORCE en DB")
            except Exception as e:
                log.warning(f"⚠️ Error actualizando estado en DB: {e}")

            return True

        except Exception as e:
            log.error(f"❌ Error cerrando posición #{trade_id}: {e}")
            self.insert_alerta(
                "FORCE_CLOSE_ERROR",
                f"❌ Fallo cierre forzado #{trade_id}: {str(e)}",
            )
            return False

    # ── Reconciliar posiciones DB vs Exchange ─────────────────
    async def reconcile_positions(self):
        """Revisa todos los trades EJECUTADO y verifica que existan en exchange.
        Si un trade está EJECUTADO en DB pero no hay posición en Binance,
        lo marca como CLOSED_FORCE automáticamente.
        También cierra posiciones en Binance que no tengan tracking en DB."""
        if not self.exchange:
            return
        try:
            # ── Obtener posición REAL desde Binance REST API ──
            # (ccxt fetch_positions a veces devuelve side incorrecto)
            real_side = None
            real_qty = 0.0
            try:
                # Hacemos la petición HTTP directamente a Binance
                import requests as _req, json as _json
                _ts = int(time.time() * 1000)
                _qs = f"symbol=BTCUSDT&timestamp={_ts}&recvWindow=10000"
                import hashlib as _hl, hmac as _hm
                _sig = _hm.new(self.exchange.secret.encode(), _qs.encode(), _hl.sha256).hexdigest()
                _url = f"{'https://fapi.binance.com'}/fapi/v2/positionRisk?{_qs}&signature={_sig}"
                _r = _req.get(_url, headers={"X-MBX-APIKEY": self.exchange.apiKey})
                if _r.status_code == 200:
                    for _pos in _r.json():
                        _amt = float(_pos.get("positionAmt", 0) or 0)
                        if abs(_amt) > 0.0005:
                            real_side = "SHORT" if _amt < 0 else "LONG"
                            real_qty = abs(_amt)
                            log.info(f"📡 Posición real (REST): {real_side} {real_qty:.3f} BTC @ ${float(_pos.get('entryPrice',0)):.2f}")
                            break
                    if real_side is None:
                        log.info("📡 Sin posición en exchange (REST)")
                else:
                    log.warning(f"⚠️ Error REST {_r.status_code} — fallback a ccxt")
                    raise Exception("REST falló")
            except Exception:
                # Fallback: ccxt fetch_positions
                try:
                    positions = await self.exchange.fetch_positions([SYMBOL])
                    for pos in positions:
                        amt = float(pos.get("positionAmt", 0) or pos.get("contracts", 0) or 0)
                        if abs(amt) > 0.0005:
                            real_side = "SHORT" if amt < 0 else "LONG"
                            real_qty = abs(amt)
                            log.info(f"📡 Posición real (ccxt): {real_side} {real_qty:.3f} BTC")
                            break
                except Exception as e2:
                    log.warning(f"⚠️ Error leyendo posición: {e2}")

            # ── Cancelar TODAS las órdenes (incluyendo condicionales) ──
            try:
                import requests as _req2, time as _time2
                import hashlib as _hl2, hmac as _hm2, urllib.parse as _up2
                _ts2 = int(_time2.time() * 1000)
                _p2 = {"symbol": "BTCUSDT", "timestamp": _ts2}
                _qs2 = _up2.urlencode(sorted(_p2.items()))
                _sig2 = _hm2.new(self.exchange.secret.encode(), _qs2.encode(), _hl2.sha256).hexdigest()
                _url2 = f"https://fapi.binance.com/fapi/v1/allOpenOrders?{_qs2}&signature={_sig2}"
                _r2 = _req2.delete(_url2, headers={"X-MBX-APIKEY": self.exchange.apiKey})
                if _r2.status_code == 200:
                    log.warning(f"🗑️ Canceladas TODAS las órdenes (reconcile)")
            except Exception:
                try:
                    open_orders = await self.exchange.fetch_open_orders(SYMBOL)
                    if open_orders:
                        for o in open_orders:
                            try:
                                await self.exchange.cancel_order(o["id"], SYMBOL)
                            except Exception:
                                pass
                except Exception:
                    pass

            # ── Obtener trades EJECUTADO de DB ──
            self.connect_db()
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, lado, cantidad_btc FROM hermes_trades
                    WHERE estado = 'EJECUTADO' AND modo IN ('REAL', 'DEMO')
                    ORDER BY id
                """)
                db_trades = cur.fetchall()

            # ── Si hay posición en Binance sin tracking en DB → cerrarla ──
            if not db_trades and real_qty > 0:
                log.warning(f"🔄 {real_side} {real_qty:.3f} BTC sin trackear en DB — cerrando...")
                close_side = "sell" if real_side == "LONG" else "buy"
                # Intentar 3 métodos hasta que funcione
                for metodo, params in [
                    ("reduceOnly", {"reduceOnly": True}),
                    ("closePosition", {"closePosition": True}),
                    ("market directo", {}),
                ]:
                    try:
                        r = await self.exchange.create_order(
                            symbol=SYMBOL, type="market", side=close_side,
                            amount=real_qty, params=params,
                        )
                        log.info(f"   ✅ Cerrada vía {metodo}")
                        break
                    except Exception as e:
                        log.warning(f"   ⚠️ {metodo} falló: {str(e)[:60]}")
                        if metodo == "market directo":
                            log.error(f"   ❌ No se pudo cerrar posición huérfana")
                return

            if not db_trades:
                return

            # ── Marcar fantasmas (EJECUTADO sin posición en exchange) ──
            for trade in db_trades:
                trade_id = trade["id"]
                side = trade["lado"]
                # Si no hay posición del mismo lado en exchange
                side_match = (side == real_side)
                if not side_match or real_qty < 0.0005:
                    log.warning(f"🔄 #{trade_id} {side} fantasma — marcando CLOSED_FORCE")
                    with self.conn.cursor() as cur:
                        cur.execute(
                            "UPDATE hermes_trades SET estado = 'CLOSED_FORCE' WHERE id = %s AND estado = 'EJECUTADO'",
                            (trade_id,),
                        )
                        if cur.rowcount > 0:
                            self.conn.commit()
                            log.info(f"📝 #{trade_id} marcado CLOSED_FORCE")

        except Exception as e:
            log.warning(f"⚠️ Error en reconcile_positions: {e}")

    # ── Sincronizar P&L desde Binance ──────────────────────────
    async def sync_position_pnl(self):
        """Lee posiciones reales desde Binance y actualiza el P&L en DB."""
        if not self.exchange:
            return
        try:
            positions = await self.exchange.fetch_positions([SYMBOL])
            for pos in positions:
                contracts = pos.get("contracts")
                if contracts is None or float(contracts or 0) == 0:
                    continue
                side = "LONG" if float(pos.get("positionAmt", 0) or 0) > 0 else "SHORT"
                entry = float(pos.get("entryPrice", 0) or 0)
                mark = float(pos.get("markPrice", 0) or 0)
                pnl = float(pos.get("unrealizedPnl", 0) or 0)
                leverage = float(pos.get("leverage", self.apalancamiento) or self.apalancamiento)

                self.connect_db()
                with self.conn.cursor() as cur:
                    # Buscar trade activo más reciente
                    cur.execute(
                        """SELECT id, pnl_realizado FROM hermes_trades
                           WHERE estado = 'EJECUTADO'
                           ORDER BY id DESC LIMIT 1"""
                    )
                    row = cur.fetchone()
                    if row and (row[1] is None or abs(float(row[1]) - pnl) > 0.01):
                        cur.execute(
                            "UPDATE hermes_trades SET pnl_realizado = %s WHERE id = %s",
                            (round(pnl, 2), row[0]),
                        )
                        self.conn.commit()
                        log.info(
                            f"📊 P&L real #{row[0]}: ${pnl:.2f} "
                            f"| Entry=${entry:.2f} Mark=${mark:.2f} "
                            f"| Apalancamiento={leverage:.0f}x"
                        )
        except Exception as e:
            log.warning(f"⚠️ Error syncing P&L: {e}")

    # ── Check SL/TP Local (porque Binance oculta algo orders) ──
    async def check_sl_tp(self):
        """
        Revisa en cada ciclo si el precio actual tocó el SL o TP
        almacenados en BD. Como Binance Futures convierte STOP_MARKET
        y TAKE_PROFIT_MARKET en 'algo orders' invisibles para
        fetch_open_orders(), este es el ÚNICO enforcement real de SL/TP.

        Se ejecuta DESPUÉS de sync_position_pnl() para tener precio actual.
        """
        try:
            self.connect_db()
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, lado, precio_entrada, cantidad_btc,
                           stop_loss, take_profit
                    FROM hermes_trades
                    WHERE estado = 'EJECUTADO' AND modo IN ('REAL', 'DEMO')
                    ORDER BY id DESC LIMIT 1
                """)
                trade = cur.fetchone()

            if not trade:
                return

            trade_id = trade["id"]
            side = trade["lado"]
            entry = float(trade["precio_entrada"])
            amount = float(trade["cantidad_btc"])
            sl_price = float(trade["stop_loss"]) if trade["stop_loss"] else None
            tp_price = float(trade["take_profit"]) if trade["take_profit"] else None

            if not sl_price and not tp_price:
                return

            # Obtener precio actual
            if not self.exchange:
                return

            try:
                ticker = await self.exchange.fetch_ticker(SYMBOL)
                mark_price = float(ticker.get("markPrice") or ticker.get("last", 0))
            except Exception:
                return

            if mark_price <= 0:
                return

            # ── Evaluar SL ──
            if sl_price and sl_price > 0:
                if side == "LONG" and mark_price <= sl_price:
                    log.warning(f"🛑 SL ACTIVADO #{trade_id} LONG: mark ${mark_price:.2f} ≤ SL ${sl_price:.2f}")
                    await self.force_close_position(
                        trade_id, side, amount,
                        f"STOP_LOSS - mark ${mark_price:.2f} ≤ SL ${sl_price:.2f}"
                    )
                    return
                elif side == "SHORT" and mark_price >= sl_price:
                    log.warning(f"🛑 SL ACTIVADO #{trade_id} SHORT: mark ${mark_price:.2f} ≥ SL ${sl_price:.2f}")
                    await self.force_close_position(
                        trade_id, side, amount,
                        f"STOP_LOSS - mark ${mark_price:.2f} ≥ SL ${sl_price:.2f}"
                    )
                    return

            # ── Evaluar TP ──
            if tp_price and tp_price > 0:
                if side == "LONG" and mark_price >= tp_price:
                    log.warning(f"🎯 TP ACTIVADO #{trade_id} LONG: mark ${mark_price:.2f} ≥ TP ${tp_price:.2f}")
                    await self.force_close_position(
                        trade_id, side, amount,
                        f"TAKE_PROFIT - mark ${mark_price:.2f} ≥ TP ${tp_price:.2f}"
                    )
                    return
                elif side == "SHORT" and mark_price <= tp_price:
                    log.warning(f"🎯 TP ACTIVADO #{trade_id} SHORT: mark ${mark_price:.2f} ≤ TP ${tp_price:.2f}")
                    await self.force_close_position(
                        trade_id, side, amount,
                        f"TAKE_PROFIT - mark ${mark_price:.2f} ≤ TP ${tp_price:.2f}"
                    )
                    return

        except Exception as e:
            log.warning(f"⚠️ Error en check_sl_tp: {e}")

    async def enforce_timeout(self):
        """Cierra posiciones abiertas que excedan MAX_POSITION_HOURS.
        Independiente de las alertas MGMT_TIME_OUT del brain — capa extra de seguridad."""
        try:
            self.connect_db()
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, lado, cantidad_btc,
                           EXTRACT(EPOCH FROM (NOW() - timestamp))/3600 as edad_horas
                    FROM hermes_trades
                    WHERE estado = 'EJECUTADO' AND modo IN ('REAL', 'DEMO')
                """)
                overdue = cur.fetchall()
            if not overdue:
                return

            for t in overdue:
                trade_id = t["id"]
                side = t["lado"]
                amount = float(t["cantidad_btc"])
                hours = float(t["edad_horas"])
                max_h = MAX_POSITION_HOURS

                if hours > max_h:
                    log.warning(
                        f"⏰ TIME-OUT directo #{trade_id}: {hours:.1f}h > {max_h}h máx — cerrando"
                    )
                    if not self.exchange and self.modo_sistema in ("REAL", "DEMO"):
                        connected = await self.connect_exchange()
                        if not connected:
                            log.warning("⚠️ No se pudo conectar exchange para timeout")
                            continue
                    await self.force_close_position(
                        trade_id, side, amount,
                        f"TIME_OUT - {hours:.1f}h excedido (máx {max_h}h)"
                    )
                    # force_close_position ya marca en BD — no duplicar
        except Exception as e:
            log.warning(f"⚠️ Error en enforce_timeout: {e}")

    async def check_position_mgmt(self):
        """
        Lee las alertas de gestión del Brain y actúa:
        - MGMT_BREAK_EVEN → mover SL a entrada
        - MGMT_TRAILING_SL → mover SL a swing low
        - MGMT_TIME_OUT → cerrar posición

        Conecta el exchange automáticamente si es necesario.
        """
        try:
            self.connect_db()

            # Conectar exchange si hace falta (para acciones de gestión)
            if not self.exchange and self.modo_sistema in ("REAL", "DEMO"):
                connected = await self.connect_exchange()
                if not connected:
                    log.warning("⚠️ No se pudo conectar exchange para position mgmt")
                    return
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, timestamp, tipo, mensaje FROM hermes_alertas
                    WHERE tipo IN ('MGMT_BREAK_EVEN', 'MGMT_TRAILING_SL', 'MGMT_TIME_OUT')
                    AND timestamp > NOW() - INTERVAL '1 hour'
                    ORDER BY timestamp DESC LIMIT 5
                    """
                )
                mgmt_alerts = cur.fetchall()

            if not mgmt_alerts:
                return

            # Deducir: solo procesar la alerta MÁS RECIENTE por (tipo, trade_id)
            # para evitar reprocesar alertas viejas cada ciclo
            import re
            seen = set()
            deduped = []
            for alert in mgmt_alerts:
                trade_match = re.search(r'#(\d+)', alert["mensaje"])
                trade_id = int(trade_match.group(1)) if trade_match else 0
                key = (alert["tipo"], trade_id)
                if key not in seen:
                    seen.add(key)
                    deduped.append(alert)

            for alert in deduped:
                alert_type = alert["tipo"]
                msg = alert["mensaje"]

                # Extraer trade_id del mensaje: "#{trade_id}" o "#XXXXX"
                trade_match = re.search(r'#(\d+)', msg)
                if not trade_match:
                    continue
                trade_id = int(trade_match.group(1))

                # Extraer precio objetivo del SL:
                # - Para MGMT_BREAK_EVEN: precio después de "ENTRY $"
                # - Para MGMT_TRAILING_SL: precio después de "→ $"
                # Fallback: último precio numérico
                target_price = None
                if alert_type == "MGMT_BREAK_EVEN":
                    be_match = re.search(r'ENTRY\s+\$(\d+\.?\d*)', msg)
                    if be_match:
                        target_price = float(be_match.group(1))
                elif alert_type == "MGMT_TRAILING_SL":
                    arrow_match = re.search(r'→\s+\$(\d+\.?\d*)', msg)
                    if arrow_match:
                        target_price = float(arrow_match.group(1))

                if target_price is None:
                    # Fallback: tomar el último precio numérico
                    price_matches = re.findall(r'\$(\d+\.?\d*)', msg)
                    if not price_matches:
                        continue
                    target_price = float(price_matches[-1])

                # Obtener datos del trade para cantidad y lado
                cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    "SELECT id, lado, cantidad_btc FROM hermes_trades WHERE id = %s",
                    (trade_id,),
                )
                trade = cur.fetchone()
                cur.close()

                if not trade:
                    continue

                side = trade["lado"]
                amount = float(trade["cantidad_btc"])

                # ── Verificar que la posición realmente existe en exchange ──
                if self.exchange:
                    try:
                        posiciones = await self.exchange.fetch_positions([SYMBOL])
                        pos_activa = False
                        for p in posiciones:
                            contracts = float(p.get("contracts", 0) or p.get("positionAmt", 0) or 0)
                            if abs(contracts) > 0:
                                pos_side = "LONG" if contracts > 0 else "SHORT"
                                if pos_side == side:
                                    pos_activa = True
                                    break
                        if not pos_activa:
                            log.warning(f"⚠️ Trade #{trade_id} {side} ya no tiene posición en exchange — saltando gestión")
                            # Marcar como cerrado en BD si el brain cree que está activo
                            with self.conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE hermes_trades SET estado = 'CLOSED_FORCE' WHERE id = %s AND estado = 'EJECUTADO'",
                                    (trade_id,),
                                )
                                if cur.rowcount > 0:
                                    self.conn.commit()
                                    log.info(f"📝 Trade #{trade_id} marcado como CLOSED_FORCE en DB (fantasma detectado)")
                            continue
                    except Exception as e:
                        log.warning(f"⚠️ No se pudo verificar posición en exchange: {e}")

                if alert_type == "MGMT_BREAK_EVEN":
                    log.info(f"📋 Procesando MGMT_BREAK_EVEN #{trade_id} → SL=${target_price:.2f}")
                    # No necesitamos verificar duplicados porque el brain solo envía una vez
                    await self.cancel_and_replace_sl(trade_id, target_price, side, amount)

                elif alert_type == "MGMT_TRAILING_SL":
                    log.info(f"📋 Procesando MGMT_TRAILING_SL #{trade_id} → SL=${target_price:.2f}")
                    await self.cancel_and_replace_sl(trade_id, target_price, side, amount)

                elif alert_type == "MGMT_TIME_OUT":
                    log.warning(f"📋 Procesando MGMT_TIME_OUT #{trade_id} → Cerrando posición")
                    await self.force_close_position(
                        trade_id, side, amount,
                        f"Time-Out ({MAX_POSITION_HOURS}h alcanzado)"
                    )

        except Exception as e:
            log.warning(f"⚠️ Error en check_position_mgmt: {e}")

    # ── Ciclo principal ───────────────────────────────────────
    async def cycle(self):
        """Un ciclo completo del executor."""
        try:
            # 1. Cargar configuración
            self.load_config()

            # 1b. Gestión de posiciones (Break-Even, Trailing, Time-Out)
            try:
                await self.check_position_mgmt()
            except Exception as e:
                log.warning(f"⚠️ Error en position mgmt: {e}")

            # 1b2. Time-Out directo: cerrar trades abiertos más allá del límite
            # (independiente de las alertas MGMT_TIME_OUT del brain)
            try:
                await self.enforce_timeout()
            except Exception as e:
                log.warning(f"⚠️ Error en enforce_timeout: {e}")

            # 1c. Sincronizar P&L real desde Binance
            try:
                await self.sync_position_pnl()
            except Exception as e:
                log.warning(f"⚠️ Error syncing P&L: {e}")

            # 1c2. Reconciliar posiciones: DB vs Exchange
            # Marca como CLOSED_FORCE los trades EJECUTADO que ya no existen en Binance
            try:
                await self.reconcile_positions()
            except Exception as e:
                log.warning(f"⚠️ Error en reconcile_positions: {e}")

            # 1d. Check SL/TP local (porque Binance oculta algo orders)
            try:
                await self.check_sl_tp()
            except Exception as e:
                log.warning(f"⚠️ Error en check_sl_tp: {e}")

            modo = self.modo_sistema
            es_simulacion = modo not in ("REAL", "DEMO")
            if es_simulacion:
                log.info(f"💤 Executor en modo {modo} — evaluando señales en simulación")

            # ── Leer métricas (todos los modos) ──
            row = self.get_latest_metrics()
            if not row:
                log.debug("⏳ Esperando datos en metricas_btc...")
                return

            precio = float(row.get("precio", 0))
            if precio <= 0:
                return

            # ── Evaluar señal (todos los modos) ──
            signal, razon = self.evaluate_signal(row)
            if not signal:
                log.info("🔍 Sin señal de trading — esperando condiciones")
                return

            log.info(f"🚦 SEÑAL DETECTADA: {signal} | {razon}")

            # ── Control duplicados en SIMULACION ──
            if es_simulacion:
                import time as _time
                since_last = _time.time() - self.last_sim_trade_time
                if since_last < 120:  # 2 min entre trades simulados
                    log.info(f"⏳ Cooldown simulación: {int(120 - since_last)}s — esperando")
                    return

            # ── Acciones solo para REAL/DEMO ──
            if not es_simulacion:
                # Cooldown post-SL
                import time as _time
                since_sl = _time.time() - self.last_sl_time
                if since_sl < self.sl_cooldown:
                    restante = int(self.sl_cooldown - since_sl)
                    log.info(f"⏳ Cooldown post-SL: {restante}s restantes (espera de {self.sl_cooldown}s tras stop-loss)")
                    return

                # Circuit breaker
                if not self.circuit_breaker():
                    return

                # Verificar posición abierta en exchange
                if await self.has_open_position(signal):
                    log.info(f"⏭️ Saltando {signal} — ya hay posición abierta")
                    return

                # Control de duplicados: trades del mismo lado en últimos 30s
                if self.has_recent_trade(signal, seconds=30):
                    return

                # Conectar exchange
                if not self.exchange:
                    connected = await self.connect_exchange()
                    if not connected:
                        log.error("❌ No se pudo conectar a Binance — abortando ejecución")
                        return

            # ── Calcular posición (todos los modos) ──
            pos = await self.calculate_position_size(precio)
            if pos["cantidad_btc"] <= 0:
                log.warning("⚠️ Cantidad calculada <= 0, abortando")
                return

            log.info(f"📐 Posición calculada: {pos['cantidad_btc']:.5f} BTC (${pos['valor_usd']:.2f}) | Margen: ${pos['margen_usado']:.2f} ({self.margen_operacion}% x {self.apalancamiento}x)")

            # ── Ejecutar orden (SIMULACION→SIMULADO, REAL/DEMO→real) ──
            resultado = await self.execute_order(signal, pos["cantidad_btc"], precio, razon)

            # ── Registrar en DB (todos los modos) ──
            self.register_trade({
                "tipo": resultado.get("tipo", modo),
                "simbolo": SYMBOL,
                "lado": signal,
                "cantidad_btc": Decimal(str(pos["cantidad_btc"])),
                "precio_entrada": Decimal(str(resultado.get("precio_entrada", precio))),
                "valor_usd": Decimal(str(pos["valor_usd"])),
                "apalancamiento_usado": self.apalancamiento,
                "margen_usado": Decimal(str(pos["margen_usado"])),
                "stop_loss": Decimal(str(resultado.get("stop_loss", 0))),
                "take_profit": Decimal(str(resultado.get("take_profit", 0))) if resultado.get("take_profit") else Decimal('0'),
                "estado": resultado.get("estado", "PENDIENTE"),
                "modo": modo,
                "razon": razon,
                "signal_tipo": f"EXEC_{signal}",
                "balance_antes": Decimal(str(pos["balance_antes"])),
            })
            # Actualizar timestamp para cooldown de simulacion
            if es_simulacion:
                import time as _st
                self.last_sim_trade_time = _st.time()

        except Exception as e:
            log.error(f"❌ Error en ciclo executor: {e}")


async def main():
    log.info("=" * 60)
    log.info("🤖 Hermes Executor — Motor de Ejecución Real")
    log.info(f"📊 Símbolo: {SYMBOL}")
    log.info(f"⏱️  Intervalo: {EXECUTOR_INTERVAL}s")
    log.info(f"📈 Límite diario: {MAX_TRADES_PER_DAY} trades")
    log.info(
        f"🔑 REAL Keys: {'✅' if EXCHANGE_API_KEY else '❌ Vacías'} | "
        f"DEMO Keys: {'✅' if EXCHANGE_API_KEY_DEMO else '❌ Vacías'}"
    )
    log.info("=" * 60)

    executor = Executor()

    # Al iniciar: verificar conectividad DB
    try:
        executor.connect_db()
        executor.insert_alerta(
            "EXECUTOR_START",
            f"🤖 Hermes Executor iniciado — "
            f"REAL Keys: {'✅' if EXCHANGE_API_KEY else '❌'} | "
            f"DEMO Keys: {'✅' if EXCHANGE_API_KEY_DEMO else '❌'}"
        )
    except Exception as e:
        log.error(f"❌ Error inicializando DB: {e}")

    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            log.info(
                f"🔄 Ciclo #{cycle_count} — "
                f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
            )
            await executor.cycle()

        except KeyboardInterrupt:
            log.info("👋 Executor detenido por el usuario")
            break
        except Exception as e:
            log.error(f"❌ Error fatal en ciclo: {e}")

        await asyncio.sleep(EXECUTOR_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("👋 Hermes Executor detenido")
