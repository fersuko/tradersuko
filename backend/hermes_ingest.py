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
    "password": os.getenv("DB_PASS", ""),
}

SYMBOL = os.getenv("SYMBOL", "BTC/USDT:USDT")
# Símbolo para las APIs REST de Binance (formato plano, sin ccxt).
# OJO: hay que cortar el sufijo ":USDT" PRIMERO. `SYMBOL.replace("/", "")` a secas da
# "BTCUSDT:USDT" → Binance responde -1121 Invalid symbol (bug real de sep-2026).
BINANCE_SYMBOL = SYMBOL.split(":")[0].replace("/", "")
DEPTH_LIMIT = 1000  # v1.6.17: era 50. Medido el 26-sep: con 50 niveles el libro
                    # visible era $1.03M cuando el real dentro de ±1% es $31.65M
                    # → el bot veía el **3.2%** del libro, y la ratio bids/asks se
                    # DA VUELTA según la profundidad (1.00x con 50 vs 0.84x con 1000).
                    # La condición B se evaluaba sobre ruido.
DEPTH_PCT = Decimal("0.01")
DEPTH_INTERVAL = 5
PRICE_BUCKET_SIZE = 10  # $10 USD para volume profile

BINANCE_WS = "wss://fstream.binance.com/stream?streams="
STREAMS = (
    "btcusdt@trade/"
    # v1.6.17: SE QUITÓ "btcusdt@depth20@100ms". Daba 20 niveles (~$0.8M) y
    # SOBRESCRIBÍA cada 100 ms el valor bueno del poller REST (1000 niveles,
    # ~$32M), así que subir DEPTH_LIMIT no servía de nada. Ahora el poller REST
    # es la fuente ÚNICA de profundidad y de presión de compra.
    "btcusdt@markPrice@1s/"
    "!forceOrder@arr"   # mudo en este host: las liquidaciones reales van por el
                        # worker dedicado al host alterno (liquidations_real_worker)
)

INSERT_INTERVAL = 5
RECONNECT_DELAY = 5

# ── CVD multi-venue (OKX + Coinbase) ───────────────────────────
# La columna `cvd_okx` era una COPIA LITERAL de `cvd_binance` (se asignaba así en
# `get_snapshot`), por lo que cualquier "divergencia entre venues" era
# estructuralmente imposible: la diferencia era exactamente 0 en las 1.588.305 filas.
# Aquí se calcula de verdad desde los trades de cada venue.
#
# CVD = Σ(USD del taker comprador) − Σ(USD del taker vendedor), ventana de 5 min
# (mismo reset que el CVD de Binance).
OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
OKX_INST = os.getenv("OKX_INST", "BTC-USDT-SWAP")
# BTC-USDT-SWAP: 1 contrato = 0.01 BTC. El campo `sz` de OKX viene en CONTRATOS,
# NO en BTC — sin este factor el CVD sale 100× inflado. Verificado vía
# /api/v5/public/instruments (ctVal=0.01, ctValCcy=BTC, lotSz=0.01).
OKX_CTVAL = Decimal("0.01")
COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
COINBASE_PRODUCT = os.getenv("COINBASE_PRODUCT", "BTC-USD")
CVD_VENUE_RESET = 300      # 5 min, igual que el CVD de Binance
OKX_PING_INTERVAL = 20     # OKX cierra la conexión si pasa >30 s sin tráfico
COINBASE_PING_INTERVAL = 20

# ── Liquidaciones REALES (modo sombra) ─────────────────────────
# El feed real de Binance SÍ existe, pero SOLO en el host alterno: en
# `fstream.binance.com` entrega **0 frames** desde este VPS (mientras `@trade`
# entrega cientos). Ver Trading/Journal/Hallazgo-2026-09-26-Host-WS-Binance.
#
# Se instala en MODO SOMBRA: se guarda en las columnas `liq_real_*` SIN filtrar la
# señal (la señal sigue usando `liquidaciones_*` = la heurística del CVD). Motivo:
# el umbral actual ($5M/min) se calibró CONTRA esa heurística, y la sonda del
# 26-sep midió **0 liquidaciones de BTC en 21.7 min** → conectar el feed real con
# ese umbral dejaría al bot casi sin operar. Primero se acumulan datos honestos
# alineados con los trades; después se decide con evidencia.
LIQ_WS = "wss://fstream.binancefuture.com/stream?streams=!forceOrder@arr"
LIQ_SYMBOL = "BTCUSDT"   # !forceOrder@arr trae TODOS los símbolos → filtrar o se
                         # mezclan liquidaciones de ENA/SOL/etc. en las de BTC

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
        self.cvd_coinbase = Decimal("0")
        self.last_price = Decimal("0")
        self.open_interest = None
        self.funding_rate = None
        self.depth_buyer = Decimal("0")
        self.depth_seller = Decimal("0")
        self.presion_compra = Decimal("0")
        self.liquidaciones_longs = Decimal("0")
        self.liquidaciones_shorts = Decimal("0")
        # v1.6.17: liquidaciones REALES (MODO SOMBRA — se guardan pero NO filtran la señal)
        self.liq_real_longs = Decimal("0")
        self.liq_real_shorts = Decimal("0")
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
        """Stream `btcusdt@markPrice@1s`.

        ⚠️ CORRECCIÓN 24-sep-2026 — dos cosas importantes:
        1. `data["i"]` es el **index price**, NO el open interest. Antes se asignaba a
           `self.open_interest`, lo que habría metido ~$83.900 en una columna llamada
           "open_interest" (un valor FINGIDO: plausible pero de otra magnitud y otro
           significado). El OI real viene por REST en `oi_funding_poller`.
        2. Desde este VPS **este stream no entrega NADA**: verificado con dump crudo, 0
           frames en `/ws/btcusdt@markPrice@1s`, `/ws/btcusdt@markPrice` y
           `!markPrice@arr`, mientras `btcusdt@trade` entrega cientos. Consecuencia: la
           heurística de liquidaciones por velocidad de abajo **también estaba muerta**.
           Se deja el código porque es correcto si el stream llega a funcionar.
        """
        async with self.lock:
            fr = data.get("r")
            if fr:
                self.funding_rate = Decimal(str(fr))

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
            "cvd_okx": self.cvd_okx,
            "cvd_coinbase": self.cvd_coinbase,
            "presion_compra": self.presion_compra,
            "liquidaciones_longs": self.liquidaciones_longs,
            "liquidaciones_shorts": self.liquidaciones_shorts,
            # v1.6.17: modo sombra — dato real, todavía sin uso en la señal
            "liq_real_longs": self.liq_real_longs,
            "liq_real_shorts": self.liq_real_shorts,
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
                        cvd_binance, cvd_okx, cvd_coinbase, presion_compra,
                        liquidaciones_longs, liquidaciones_shorts,
                        liq_real_longs, liq_real_shorts,
                        alerta_activa, trades_per_second,
                        precio_alto_fvg, precio_bajo_fvg,
                        volumen
                    ) VALUES (
                        %(timestamp)s, %(precio)s, %(open_interest)s,
                        %(funding_rate)s, %(orderbook_depth_buyer)s,
                        %(orderbook_depth_seller)s, %(cvd_binance)s,
                        %(cvd_okx)s, %(cvd_coinbase)s, %(presion_compra)s,
                        %(liquidaciones_longs)s, %(liquidaciones_shorts)s,
                        %(liq_real_longs)s, %(liq_real_shorts)s,
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


# ── Tarea: Open Interest + Funding por REST ────────────────────
#
# ¿Por qué REST y no el stream `@markPrice`?
#   Verificado el 24-sep-2026 con dump crudo: desde este VPS el stream de mark price
#   devuelve **0 frames** (ni siquiera un error) en `/ws/btcusdt@markPrice@1s`,
#   `/ws/btcusdt@markPrice` y `!markPrice@arr`, mientras `btcusdt@trade` entrega
#   cientos de mensajes en el mismo periodo. El endpoint REST sí responde.
#   Además `data["i"]` del stream era el *index price*, no el OI (ver
#   `process_mark_price`). Estas columnas llevaban **toda la historia de la tabla en
#   NULL/0**: `open_interest` y `funding_rate` nunca tuvieron un valor real, lo que
#   dejaba muerta la alerta `FUNDING_EXTREME` del brain y el log "Funding=0.0000%".
OI_FUNDING_INTERVAL = 20  # segundos — el funding cambia cada 8 h; 20 s sobra de sobra

_FAPI = "https://fapi.binance.com/fapi/v1"


async def oi_funding_poller(aggregator: DataAggregator, stop_event: asyncio.Event):
    """Rellena `open_interest` (en BTC) y `funding_rate` (fracción, p.ej. 0.0001 = 0.01%).

    Formato del funding: **fracción**, que es lo que Binance devuelve y lo que esperan los
    consumidores (`executor` imprime `funding*100:.4f}%`; `brain` compara con
    `FUNDING_EXTREME = 0.001` = 0.1%).
    """
    sym = BINANCE_SYMBOL
    ok_once = False
    async with aiohttp.ClientSession() as session:
        while not stop_event.is_set():
            oi = fr = None
            try:
                async with session.get(f"{_FAPI}/openInterest",
                                       params={"symbol": sym}, timeout=10) as r:
                    if r.status == 200:
                        oi = (await r.json()).get("openInterest")
                async with session.get(f"{_FAPI}/premiumIndex",
                                       params={"symbol": sym}, timeout=10) as r:
                    if r.status == 200:
                        d = await r.json()
                        fr = d.get("lastFundingRate")
            except Exception as e:
                log.warning(f"⚠️ oi_funding_poller: {type(e).__name__}: {e}")

            if oi is not None or fr is not None:
                async with aggregator.lock:
                    if oi is not None:
                        aggregator.open_interest = Decimal(str(oi))
                    if fr is not None:
                        aggregator.funding_rate = Decimal(str(fr))
                if not ok_once:
                    log.info("✅ OI + funding REST activos (el stream @markPrice no llega)")
                    ok_once = True
                log.info(
                    f"📈 OI {float(oi):,.0f} BTC | "
                    f"funding {float(fr) * 100:+.4f}%"
                    if (oi is not None and fr is not None) else "📈 OI/funding parcial"
                )

            await asyncio.sleep(OI_FUNDING_INTERVAL)
    log.info("🛑 OI/funding poller detenido")


# ── Tareas: CVD por venue (OKX perp + Coinbase spot) ───────────
#
# ¿Por qué WebSocket y no REST? El CVD necesita el lado AGRESOR (taker) de cada
# trade. Un endpoint REST agregado también lo da, pero a menor resolución y con
# más latencia; el WS va trade a trade y ya existe infraestructura de reconexión.
#
# Verificado el 24-sep-2026 desde este VPS: los WS de OKX, Bybit y Coinbase
# entregan trades reales con lado taker. El fallo del `@markPrice` de Binance era
# un caso aislado, no un problema general de WebSockets en este host.
#
# ⚠️ TRAMPA DE COINBASE: su documentación dice textualmente que en el canal
# `matches` "the side field indicates the MAKER order side". Usarlo tal cual deja
# el CVD INVERTIDO — signo plausible y dirección contraria, el peor tipo de bug.
# El lado del taker es el OPUESTO (la doc lo confirma: side="sell" es un up-tick,
# es decir compra agresiva).
async def okx_cvd_worker(aggregator: DataAggregator, stop_event: asyncio.Event):
    """CVD (ventana 5 min) desde los trades de OKX BTC-USDT-SWAP.

    `sz` viene en CONTRATOS → notional USD = sz × ctVal × px.
    OKX cierra la conexión si pasa >30 s sin tráfico: hay que mandar `ping` de
    aplicación (texto) y él responde `pong`. Un ping a nivel WS no basta.
    """
    sub = {"op": "subscribe", "args": [{"channel": "trades", "instId": OKX_INST}]}
    ok_once = False
    while not stop_event.is_set():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(OKX_WS, timeout=20, heartbeat=25) as ws:
                    await ws.send_str(json.dumps(sub))
                    log.info(f"✅ CVD OKX conectado ({OKX_INST}, ctVal={OKX_CTVAL})")
                    last_ping = time_module.monotonic()
                    while not stop_event.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.receive(), timeout=15)
                        except asyncio.TimeoutError:
                            msg = None
                        if msg is not None:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                if msg.data == "pong":
                                    pass
                                else:
                                    d = json.loads(msg.data)
                                    if d.get("arg", {}).get("channel") == "trades":
                                        delta = Decimal("0")
                                        for t in d.get("data", []):
                                            usd = (Decimal(str(t["sz"])) * OKX_CTVAL
                                                   * Decimal(str(t["px"])))
                                            delta += usd if t["side"] == "buy" else -usd
                                        if delta:
                                            async with aggregator.lock:
                                                aggregator.cvd_okx += delta
                                            if not ok_once:
                                                log.info("✅ CVD OKX fluyendo")
                                                ok_once = True
                            elif msg.type in (aiohttp.WSMsgType.CLOSE,
                                              aiohttp.WSMsgType.ERROR):
                                log.warning("⚠️ CVD OKX: conexión cerrada, reconectando")
                                break
                        if time_module.monotonic() - last_ping >= OKX_PING_INTERVAL:
                            await ws.send_str("ping")
                            last_ping = time_module.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"⚠️ CVD OKX reconectando: {type(e).__name__}: {e}")
        await asyncio.sleep(RECONNECT_DELAY)
    log.info("🛑 CVD OKX detenido")


async def coinbase_cvd_worker(aggregator: DataAggregator, stop_event: asyncio.Event):
    """CVD (ventana 5 min) desde los trades SPOT de Coinbase (BTC-USD).

    Es spot, no perp: sirve como señal distinta — divergencia spot-vs-perp.
    `side` es el lado del MAKER (ver nota arriba) → se invierte para obtener el taker.
    Coinbase también cierra la conexión sin tráfico; se manda ping JSON.
    """
    sub = {"type": "subscribe", "product_ids": [COINBASE_PRODUCT],
           "channels": ["matches"]}
    ok_once = False
    while not stop_event.is_set():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(COINBASE_WS, timeout=20, heartbeat=20) as ws:
                    await ws.send_str(json.dumps(sub))
                    log.info(f"✅ CVD Coinbase conectado ({COINBASE_PRODUCT})")
                    last_ping = time_module.monotonic()
                    while not stop_event.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.receive(), timeout=15)
                        except asyncio.TimeoutError:
                            msg = None
                        if msg is not None:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                d = json.loads(msg.data)
                                if d.get("type") == "match":
                                    usd = Decimal(str(d["size"])) * Decimal(str(d["price"]))
                                    # side = MAKER → taker es el opuesto
                                    delta = usd if d.get("side") == "sell" else -usd
                                    async with aggregator.lock:
                                        aggregator.cvd_coinbase += delta
                                    if not ok_once:
                                        log.info("✅ CVD Coinbase fluyendo")
                                        ok_once = True
                            elif msg.type in (aiohttp.WSMsgType.CLOSE,
                                              aiohttp.WSMsgType.ERROR):
                                log.warning("⚠️ CVD Coinbase: conexión cerrada, reconectando")
                                break
                        if time_module.monotonic() - last_ping >= COINBASE_PING_INTERVAL:
                            await ws.send_str(json.dumps({"type": "ping"}))
                            last_ping = time_module.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"⚠️ CVD Coinbase reconectando: {type(e).__name__}: {e}")
        await asyncio.sleep(RECONNECT_DELAY)
    log.info("🛑 CVD Coinbase detenido")


# ── Tarea: liquidaciones REALES (MODO SOMBRA) ──────────────────
#
# Semántica del lado (importante, y el handler viejo la tiene al revés):
#   Binance manda `S` = el lado de la ORDEN forzada.
#     S=SELL → se cerró a la fuerza un LONG  → es una LIQUIDACIÓN DE LONGS
#     S=BUY  → se cerró a la fuerza un SHORT → es una LIQUIDACIÓN DE SHORTS
#   `process_force_order` (arriba) hace lo contrario: suma S=SELL a
#   `liquidaciones_shorts`. Hoy da igual porque esas columnas las llena la
#   heurística, no ese handler; pero al activar el feed real HAY QUE USAR LA
#   SEMÁNTICA CORRECTA (la de aquí), o el signo de la señal sale invertido.
async def liquidations_real_worker(aggregator: DataAggregator, stop_event: asyncio.Event):
    """Acumula liquidaciones REALES de BTCUSDT en `liq_real_*` (modo sombra).

    Host ALTERNO obligatorio (`fstream.binancefuture.com`): en `.com` este stream
    entrega 0 frames desde este VPS.
    Filtra por símbolo: `!forceOrder@arr` trae TODOS los mercados.
    NO filtra la señal todavía — solo acumula para poder medirlo después.
    """
    ok_once = False
    n_btc = 0
    while not stop_event.is_set():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(LIQ_WS, timeout=25, heartbeat=25) as ws:
                    log.info("✅ Liquidaciones REALES conectadas (host alterno, modo sombra)")
                    while not stop_event.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.receive(), timeout=30)
                        except asyncio.TimeoutError:
                            continue
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            if msg.data == "pong":
                                continue
                            try:
                                o = json.loads(msg.data).get("data", {}).get("o", {})
                            except Exception:
                                continue
                            if o.get("s") != LIQ_SYMBOL:
                                continue  # ← filtro clave: solo BTCUSDT
                            try:
                                usd = (Decimal(str(o.get("q", "0")))
                                       * Decimal(str(o.get("ap") or o.get("p") or "0")))
                            except Exception:
                                continue
                            async with aggregator.lock:
                                if o.get("S") == "SELL":
                                    aggregator.liq_real_longs += usd    # se liquidó un LONG
                                else:
                                    aggregator.liq_real_shorts += usd   # se liquidó un SHORT
                            n_btc += 1
                            log.info(f"💥 LIQ REAL {'LONG' if o.get('S')=='SELL' else 'SHORT'} "
                                     f"${float(usd):,.0f} @ {o.get('ap') or o.get('p')} "
                                     f"(evento #{n_btc} de BTCUSDT)")
                            if not ok_once:
                                log.info("✅ Liquidaciones REALES fluyendo (BTCUSDT)")
                                ok_once = True
                        elif msg.type in (aiohttp.WSMsgType.CLOSE,
                                          aiohttp.WSMsgType.ERROR):
                            log.warning("⚠️ Liquidaciones reales: conexión cerrada, reconectando")
                            break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"⚠️ Liquidaciones reales reconectando: {type(e).__name__}: {e}")
        await asyncio.sleep(RECONNECT_DELAY)
    log.info("🛑 Liquidaciones reales detenido")


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

    # OI + funding por REST: el stream @markPrice no entrega nada desde este VPS
    oi_task = asyncio.create_task(oi_funding_poller(aggregator, stop_event))
    log.info("✅ OI/funding poller REST lanzado")

    # CVD por venue: OKX (perp #2 por volumen) + Coinbase (spot)
    okx_task = asyncio.create_task(okx_cvd_worker(aggregator, stop_event))
    cb_task = asyncio.create_task(coinbase_cvd_worker(aggregator, stop_event))
    log.info("✅ Workers CVD multi-venue lanzados (OKX + Coinbase)")

    # v1.6.17: liquidaciones REALES en modo sombra (no filtran la señal)
    liq_task = asyncio.create_task(liquidations_real_worker(aggregator, stop_event))
    log.info("✅ Worker de liquidaciones REALES lanzado (modo sombra)")

    ws_url = BINANCE_WS + STREAMS
    last_insert = datetime.now(timezone.utc)
    last_cvd_reset = datetime.now(timezone.utc)
    profile_flush_counter = 0

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url, timeout=30.0, heartbeat=30.0) as ws:
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
                            # v1.6.16: liq_real_* se resetea por CICLO (igual que las de arriba).
                            # Antes solo se reseteaba junto al CVD (cada 5 min) → el mismo valor
                            # se reescribía en ~60 filas y sumar la columna inflaba el volumen ×60.
                            aggregator.liq_real_longs = Decimal("0")
                            aggregator.liq_real_shorts = Decimal("0")
                            aggregator.trade_count = 0
                            last_insert = now

                            # Resetear CVD cada 5 minutos para evitar sesgo acumulativo
                            # El CVD debe reflejar agresión neta RECIENTE, no desde el inicio del programa
                            if (now - last_cvd_reset).total_seconds() >= 300:  # 5 minutos
                                aggregator.cvd_binance = Decimal("0")
                                aggregator.cvd_okx = Decimal("0")
                                aggregator.cvd_coinbase = Decimal("0")
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
