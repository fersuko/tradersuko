#!/usr/bin/env python3
"""
hermes_ingest.py — Ingestor asíncrono de datos de trading en tiempo real.
Conecta a Binance WebSockets + CCXT REST.
Calcula: CVD, TPS, FVG (Fair Value Gaps), Volume Profile (POC).
"""

import os
import json
import asyncio
import logging
import time as time_module
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dotenv import load_dotenv
import aiohttp
import ccxt.async_support as ccxt
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

SYMBOL = os.getenv("SYMBOL", "BTC/USDT:USDT")
DEPTH_LIMIT = 50
DEPTH_PCT = Decimal("0.01")
DEPTH_INTERVAL = 5
PRICE_BUCKET_SIZE = 10  # $10 USD para volume profile

BINANCE_WS = "wss://fstream.binance.com/stream?streams="
STREAMS = (
    "btcusdt@trade/"
    "btcusdt@depth20@100ms/"
    "btcusdt@markPrice@1s/"
    "!forceOrder@arr"
)

INSERT_INTERVAL = 5
RECONNECT_DELAY = 5

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hermes_ingest")


class DataAggregator:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.reset()
        # Velas de 1 minuto: dict {minuto_epoch: {open,high,low,close,volume}}
        self._1m_candles: dict = {}
        self._current_minute = None
        self._current_candle = None
        # Volume profile: dict {price_bucket: total_volume}
        self._volume_profile: dict = {}

    def reset(self):
        self.cvd_binance = Decimal("0")
        self.cvd_okx = Decimal("0")
        self.last_price = Decimal("0")
        self.open_interest = None
        self.funding_rate = None
        self.depth_buyer = Decimal("0")
        self.depth_seller = Decimal("0")
        self.presion_compra = Decimal("0")
        self.liquidaciones_longs = Decimal("0")
        self.liquidaciones_shorts = Decimal("0")
        self.trade_count = 0
        self.trades_per_second = Decimal("0")
        # FVG activo
        self.precio_alto_fvg = None
        self.precio_bajo_fvg = None
        # Heurística de liquidaciones
        self._prev_mark_price = Decimal("0")
        self._price_velocity_1m = Decimal("0")  # cambio % en 1 minuto
        self._velocity_samples = []

    # ── Cálculo de velas 1m y FVG ────────────────────────────
    def _update_1m_candle(self, price: Decimal, qty: Decimal):
        """Construye velas de 1 minuto desde los trades."""
        now = datetime.now(timezone.utc)
        minute_key = now.replace(second=0, microsecond=0).timestamp()

        if minute_key != self._current_minute:
            # Cerrar vela anterior y evaluar FVG
            self._detect_fvg()
            # Nueva vela
            self._current_minute = minute_key
            self._current_candle = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
                "ts": now,
            }
        else:
            c = self._current_candle
            if price > c["high"]:
                c["high"] = price
            if price < c["low"]:
                c["low"] = price
            c["close"] = price
            c["volume"] += qty

        # Guardar en histórico (últimas 5 velas)
        self._1m_candles[minute_key] = self._current_candle
        # Limpiar velas viejas (> 5 min)
        cutoff = now.timestamp() - 300
        for key in list(self._1m_candles.keys()):
            if key < cutoff:
                del self._1m_candles[key]

    def _detect_fvg(self):
        """Detecta Fair Value Gap entre la vela 1 y 3 (saltando vela 2)."""
        if not self._current_candle:
            return

        candles = sorted(self._1m_candles.values(), key=lambda c: c["ts"])
        if len(candles) < 3:
            return

        c1 = candles[-3]  # Vela 1 (3 atrás)
        c2 = candles[-2]  # Vela 2 (intermedia)
        c3 = candles[-1]  # Vela 3 (recién cerrada)

        # Bullish FVG: c1.high < c3.low → gap alcista
        if c1["high"] < c3["low"]:
            self.precio_alto_fvg = c3["low"]
            self.precio_bajo_fvg = c1["high"]
            log.info(
                f"📐 FVG ALCISTA detectado: "
                f"${self.precio_bajo_fvg:.2f} - ${self.precio_alto_fvg:.2f}"
            )
        # Bearish FVG: c1.low > c3.high → gap bajista
        elif c1["low"] > c3["high"]:
            self.precio_alto_fvg = c1["low"]
            self.precio_bajo_fvg = c3["high"]
            log.info(
                f"📐 FVG BAJISTA detectado: "
                f"${self.precio_bajo_fvg:.2f} - ${self.precio_alto_fvg:.2f}"
            )

    # ── Volume Profile (POC) ──────────────────────────────────
    def _add_to_volume_profile(self, price: Decimal, qty: Decimal):
        """Acumula volumen en buckets de $10."""
        # Redondear al bucket de $10 más cercano
        bucket = (price / PRICE_BUCKET_SIZE).to_integral_value(
            rounding=ROUND_HALF_UP
        ) * PRICE_BUCKET_SIZE
        volume_usd = price * qty
        self._volume_profile[float(bucket)] = (
            self._volume_profile.get(float(bucket), Decimal("0")) + volume_usd
        )

    async def flush_volume_profile(self):
        """Persiste volume profile en DB."""
        if not self._volume_profile:
            return
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            conn.autocommit = False
            cur = conn.cursor()
            for bucket, vol in self._volume_profile.items():
                cur.execute(
                    """
                    INSERT INTO volume_profile (price_bucket, total_volume, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (price_bucket)
                    DO UPDATE SET total_volume = volume_profile.total_volume + %s,
                                  updated_at = NOW()
                    """,
                    (bucket, float(vol), float(vol)),
                )
            conn.commit()
            cur.close()
            conn.close()
            log.info(
                f"📊 Volume Profile: {len(self._volume_profile)} buckets actualizados"
            )
            # Resetear acumulador (los datos ya están en DB)
            self._volume_profile = {}
        except Exception as e:
            log.warning(f"⚠️ Error flush volume profile: {e}")

    # ── Procesamiento de streams ──────────────────────────────
    async def process_trade(self, data):
        async with self.lock:
            price = Decimal(str(data["p"]))
            qty = Decimal(str(data["q"]))
            volume = price * qty
            is_buyer_maker = data["m"]

            self.last_price = price
            self.trade_count += 1

            if is_buyer_maker:
                self.cvd_binance -= volume
            else:
                self.cvd_binance += volume

            # Velas 1m + FVG
            self._update_1m_candle(price, qty)
            # Volume profile
            self._add_to_volume_profile(price, qty)

    async def process_depth(self, data):
        async with self.lock:
            bids_total = sum(
                Decimal(b[0]) * Decimal(b[1]) for b in data.get("b", [])
            )
            asks_total = sum(
                Decimal(a[0]) * Decimal(a[1]) for a in data.get("a", [])
            )
            self.depth_buyer = bids_total
            self.depth_seller = asks_total
            self._update_presion()

    def set_depth_from_rest(self, bids_usd, asks_usd):
        self.depth_buyer = bids_usd
        self.depth_seller = asks_usd
        self._update_presion()

    def _update_presion(self):
        total = self.depth_buyer + self.depth_seller
        if total > 0:
            self.presion_compra = round(
                (self.depth_buyer / total) * 100, 2
            )
        else:
            self.presion_compra = Decimal("50")

    async def process_mark_price(self, data):
        async with self.lock:
            fr = data.get("r")
            if fr:
                self.funding_rate = Decimal(str(fr))
            oi = data.get("i")
            if oi:
                self.open_interest = Decimal(str(oi))
            
            # Heurística de liquidaciones por velocidad de precio
            mark_price = Decimal(str(data.get("p", "0")))
            if self._prev_mark_price > 0 and mark_price > 0:
                change_pct = (mark_price - self._prev_mark_price) / self._prev_mark_price
                self._velocity_samples.append(change_pct)
                
                # Mantener últimos 10 samples (~10 segundos)
                if len(self._velocity_samples) > 10:
                    self._velocity_samples.pop(0)
                
                # Si hay suficiente muestra, calcular velocidad
                if len(self._velocity_samples) >= 5:
                    total_change = sum(self._velocity_samples, Decimal("0"))
                    abs_change = abs(total_change)
                    
                    # Umbral: 0.15% en 5-10 segundos = posible micro-liquidación
                    if abs_change > Decimal("0.0015"):
                        estimated_volume = abs_change * Decimal("5000000")
                        if total_change < 0:
                            self.liquidaciones_longs += estimated_volume
                            log.info(f"💥 LIQ ESTIMADA LONG: ${estimated_volume:.2f} (velocidad {float(total_change)*100:.2f}%)")
                        else:
                            self.liquidaciones_shorts += estimated_volume
                            log.info(f"💥 LIQ ESTIMADA SHORT: ${estimated_volume:.2f} (velocidad {float(total_change)*100:.2f}%)")
                        self._velocity_samples = []
            
            self._prev_mark_price = mark_price

    async def process_force_order(self, data):
        async with self.lock:
            order = data.get("o", {})
            side = order.get("S", "")
            executed_qty = Decimal(str(order.get("q", "0")))
            executed_price = Decimal(str(order.get("p", "0")))
            usd_value = executed_qty * executed_price

            if side == "SELL":
                self.liquidaciones_shorts += usd_value
                log.info(
                    f"💥 LIQUIDACIÓN SHORT: {usd_value:.2f} USD @ {executed_price}"
                )
            elif side == "BUY":
                self.liquidaciones_longs += usd_value
                log.info(
                    f"💥 LIQUIDACIÓN LONG: {usd_value:.2f} USD @ {executed_price}"
                )

    def get_snapshot(self, interval_seconds=INSERT_INTERVAL):
        tps = (
            Decimal(str(self.trade_count)) / Decimal(str(interval_seconds))
            if interval_seconds > 0
            else Decimal("0")
        )
        # Heurística #2: CVD alto = posible barrido de liquidez
        # Si en 5s hay >$5M de CVD, puede ser liquidación (no trades normales)
        cvd_abs = abs(self.cvd_binance)
        if cvd_abs > Decimal("5000000"):
            if self.cvd_binance > 0:  # Compra agresiva = shorts liquidando
                self.liquidaciones_shorts += cvd_abs
                log.info(f"💥 CVD-BARRIDO SHORT: ${float(cvd_abs):,.0f} en {interval_seconds}s")
            else:  # Venta agresiva = longs liquidando
                self.liquidaciones_longs += cvd_abs
                log.info(f"💥 CVD-BARRIDO LONG: ${float(cvd_abs):,.0f} en {interval_seconds}s")
        return {
            "precio": self.last_price,
            "open_interest": self.open_interest,
            "funding_rate": self.funding_rate,
            "orderbook_depth_buyer": self.depth_buyer,
            "orderbook_depth_seller": self.depth_seller,
            "cvd_binance": self.cvd_binance,
            "cvd_okx": self.cvd_binance,
            "presion_compra": self.presion_compra,
            "liquidaciones_longs": self.liquidaciones_longs,
            "liquidaciones_shorts": self.liquidaciones_shorts,
            "alerta_activa": False,
            "trade_count": self.trade_count,
            "trades_per_second": tps,
            "precio_alto_fvg": self.precio_alto_fvg,
            "precio_bajo_fvg": self.precio_bajo_fvg,
            "volumen": float(self._current_candle["volume"]) if self._current_candle else 0,
        }


class DBInserter:
    def __init__(self):
        self.conn = None

    def connect(self):
        self.conn = psycopg2.connect(**DB_CONFIG)
        self.conn.autocommit = False
        log.info("✅ Conectado a PostgreSQL")

    def insert(self, snapshot):
        if self.conn is None or self.conn.closed:
            self.connect()

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO metricas_btc (
                        timestamp, precio, open_interest, funding_rate,
                        orderbook_depth_buyer, orderbook_depth_seller,
                        cvd_binance, cvd_okx, presion_compra,
                        liquidaciones_longs, liquidaciones_shorts,
                        alerta_activa, trades_per_second,
                        precio_alto_fvg, precio_bajo_fvg,
                        volumen
                    ) VALUES (
                        %(timestamp)s, %(precio)s, %(open_interest)s,
                        %(funding_rate)s, %(orderbook_depth_buyer)s,
                        %(orderbook_depth_seller)s, %(cvd_binance)s,
                        %(cvd_okx)s, %(presion_compra)s,
                        %(liquidaciones_longs)s, %(liquidaciones_shorts)s,
                        %(alerta_activa)s, %(trades_per_second)s,
                        %(precio_alto_fvg)s, %(precio_bajo_fvg)s,
                        %(volumen)s
                    )
                    """,
                    {
                        "timestamp": datetime.now(timezone.utc),
                        **snapshot,
                    },
                )
            self.conn.commit()
            log.info(
                f"📊 Insertado | ${snapshot['precio']:.2f} | "
                f"CVD: {snapshot['cvd_binance']:.0f} | "
                f"TPS: {snapshot['trades_per_second']:.1f} | "
                f"FVG: {snapshot['precio_alto_fvg'] or '-'} | "
                f"Depth B: ${snapshot['orderbook_depth_buyer']:,.0f}"
            )
        except Exception as e:
            self.conn.rollback()
            log.error(f"❌ Error insertando: {e}")
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


# ── Tarea: depth REST ──────────────────────────────────────────
async def depth_poller(aggregator: DataAggregator, stop_event: asyncio.Event):
    exchange = ccxt.binanceusdm({"enableRateLimit": True})

    while not stop_event.is_set():
        try:
            price = aggregator.last_price
            if price <= 0:
                await asyncio.sleep(DEPTH_INTERVAL)
                continue

            orderbook = await exchange.fetch_order_book(SYMBOL, limit=DEPTH_LIMIT)
            if not orderbook:
                await asyncio.sleep(DEPTH_INTERVAL)
                continue

            price_dec = Decimal(str(price))
            lower = price_dec * (Decimal("1") - DEPTH_PCT)
            upper = price_dec * (Decimal("1") + DEPTH_PCT)

            bids_usd = Decimal("0")
            for b in orderbook["bids"]:
                bp, bq = Decimal(str(b[0])), Decimal(str(b[1]))
                if bp >= lower:
                    bids_usd += bp * bq
                else:
                    break

            asks_usd = Decimal("0")
            for a in orderbook["asks"]:
                ap, aq = Decimal(str(a[0])), Decimal(str(a[1]))
                if ap <= upper:
                    asks_usd += ap * aq
                else:
                    break

            if bids_usd > 0 or asks_usd > 0:
                aggregator.set_depth_from_rest(bids_usd, asks_usd)

        except Exception as e:
            log.warning(f"⚠️ Error en depth_poller: {e}")

        await asyncio.sleep(DEPTH_INTERVAL)

    await exchange.close()
    log.info("🛑 Depth poller detenido")


# ── Main ───────────────────────────────────────────────────────
async def main():
    log.info("🚀 Hermes Ingest — TPS + FVG + Volume Profile")
    log.info(f"Conectando a Binance Futures: {STREAMS}")

    aggregator = DataAggregator()
    db = DBInserter()

    try:
        db.connect()
        log.info("✅ Conexión a PostgreSQL establecida")
    except Exception as e:
        log.warning(f"⚠️ DB: {e}")

    stop_event = asyncio.Event()
    rest_task = asyncio.create_task(depth_poller(aggregator, stop_event))
    log.info("✅ Depth poller REST lanzado")

    ws_url = BINANCE_WS + STREAMS
    last_insert = datetime.now(timezone.utc)
    last_cvd_reset = datetime.now(timezone.utc)
    profile_flush_counter = 0

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url) as ws:
                    log.info("✅ WebSocket conectado a Binance Futures")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                                stream = data.get("stream", "")
                                payload = data.get("data", {})

                                if "trade" in stream:
                                    await aggregator.process_trade(payload)
                                elif "depth" in stream:
                                    await aggregator.process_depth(payload)
                                elif "markPrice" in stream:
                                    await aggregator.process_mark_price(payload)
                                elif "forceOrder" in stream:
                                    await aggregator.process_force_order(payload)

                            except json.JSONDecodeError:
                                log.warning("⚠️ JSON inválido")
                            except Exception as e:
                                log.error(f"❌ Error: {e}")

                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            log.error(f"❌ WS error: {ws.exception()}")
                            break

                        # Insertar cada INSERT_INTERVAL segundos
                        now = datetime.now(timezone.utc)
                        if (now - last_insert).total_seconds() >= INSERT_INTERVAL:
                            snapshot = aggregator.get_snapshot(INSERT_INTERVAL)
                            if snapshot["precio"] > 0:
                                db.insert(snapshot)

                            # Resetear acumuladores
                            aggregator.liquidaciones_longs = Decimal("0")
                            aggregator.liquidaciones_shorts = Decimal("0")
                            aggregator.trade_count = 0
                            last_insert = now

                            # Resetear CVD cada 5 minutos para evitar sesgo acumulativo
                            # El CVD debe reflejar agresión neta RECIENTE, no desde el inicio del programa
                            if (now - last_cvd_reset).total_seconds() >= 300:  # 5 minutos
                                aggregator.cvd_binance = Decimal("0")
                                aggregator.cvd_okx = Decimal("0")
                                last_cvd_reset = now
                                log.info("🔄 CVD reseteado — ventana de 5 minutos")

                            # Flush volume profile cada ~30s (~6 ciclos)
                            profile_flush_counter += 1
                            if profile_flush_counter >= 6:
                                await aggregator.flush_volume_profile()
                                profile_flush_counter = 0

        except asyncio.CancelledError:
            log.info("🛑 Ingestor detenido")
            break
        except Exception as e:
            log.error(f"❌ Conexión perdida: {e}. Reconectando en {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("👋 Hermes Ingest detenido por el usuario")
