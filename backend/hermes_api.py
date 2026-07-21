#!/usr/bin/env python3
"""
hermes_api.py — API REST asíncrona para exponer datos de trading.
Endpoint: GET /api/v1/telemetria  (últimos 100 registros)
"""

import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, Literal
import psycopg2
import psycopg2.extras
import hashlib
import hmac
import time as time_module
import requests

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

API_PORT = int(os.getenv("API_PORT", "8000"))
API_HOST = os.getenv("API_HOST", "0.0.0.0")

# ── Binance API helper (datos vivos de la posición) ──────────
BINANCE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("EXCHANGE_SECRET", "")

def get_binance_live_position() -> Optional[dict]:
    """Consulta Binance Futures para obtener datos reales de la posición activa."""
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return None
    try:
        base = "https://fapi.binance.com"
        ts = int(time_module.time() * 1000)
        params = {"timestamp": ts}
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
        r = requests.get(f"{base}/fapi/v2/positionRisk", params=params, headers=headers, timeout=5)
        data = r.json()
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if amt != 0:
                return p
        return None
    except Exception as e:
        print(f"[API] ⚠️ Error consultando Binance: {e}")
        return None

# ── FastAPI app ────────────────────────────────────────────────
app = FastAPI(
    title="Hermes Trading API",
    version="1.0.0",
    description="API cuantitativa — telemetría de BTC en tiempo real",
)

# CORS: permitir conexiones desde cualquier origen (frontend React, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper: serializar tipos no-JSON ──────────────────────────
def serialize_row(row):
    """Convierte Decimal, datetime y otros tipos a JSON-serializable."""
    serialized = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            serialized[key] = float(value)
        elif isinstance(value, datetime):
            serialized[key] = value.isoformat()
        elif isinstance(value, (int, float, str, bool)):
            serialized[key] = value
        elif value is None:
            serialized[key] = None
        else:
            serialized[key] = str(value)
    return serialized


# ── Helper: snake_case → camelCase para el frontend React ────
def snake_to_camel(data: dict) -> dict:
    """Convierte claves snake_case a camelCase para compatibilidad con React."""
    mapping = {
        "umbral_liquidaciones": "umbralLiquidaciones",
        "delta_cvd_confirmacion": "deltaCvd",
        "apalancamiento": "leverage",
        "margen_operacion": "margenOperacion",
        "modo_sistema": "modoSistema",
        "updated_at": "updatedAt",
    }
    camel = {}
    for key, value in data.items():
        camel_key = mapping.get(key, key)
        camel[camel_key] = value
    return camel


# ── Endpoint: Telemetría ──────────────────────────────────────
@app.get("/api/v1/telemetria")
async def get_telemetria(limit: int = 100):
    """
    Retorna los últimos N registros de metricas_btc.
    Default: 100, Máximo: 1000.
    """
    if limit < 1:
        limit = 1
    if limit > 1000:
        limit = 1000

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM metricas_btc
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        conn.close()

        if not rows:
            return {
                "ok": True,
                "data": [],
                "count": 0,
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Contar cuántos registros hay en total
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM metricas_btc")
            total = cur.fetchone()[0]
        conn.close()

        return {
            "ok": True,
            "data": [serialize_row(r) for r in rows],
            "count": len(rows),
            "total_registros": total,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error consultando base de datos: {str(e)}",
        )


@app.get("/api/v1/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "servicio": "hermes_trading_api",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Modelo para actualización de config ─────────────────────
class ConfigUpdate(BaseModel):
    umbral_liquidaciones: Optional[float] = None
    delta_cvd_confirmacion: Optional[float] = None
    apalancamiento: Optional[int] = None
    margen_operacion: Optional[float] = None
    modo_sistema: Optional[Literal["SIMULACION", "DEMO", "REAL"]] = None


# ── Endpoint: GET /api/v1/config ────────────────────────────
@app.get("/api/v1/config")
async def get_config():
    """Devuelve la configuración actual del sistema."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM hermes_config WHERE id = 1")
            row = cur.fetchone()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="No hay configuración")

        data = serialize_row(row)
        return {
            "ok": True,
            "data": data,                          # snake_case (brain, ingest)
            "calibration": snake_to_camel(data),   # camelCase (frontend sliders)
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error leyendo configuración: {str(e)}"
        )


# ── Endpoint: POST /api/v1/config ───────────────────────────
@app.post("/api/v1/config")
async def update_config(config: ConfigUpdate):
    """Actualiza la configuración del sistema."""
    updates = {}
    if config.umbral_liquidaciones is not None:
        updates["umbral_liquidaciones"] = config.umbral_liquidaciones
    if config.delta_cvd_confirmacion is not None:
        updates["delta_cvd_confirmacion"] = config.delta_cvd_confirmacion
    if config.apalancamiento is not None:
        updates["apalancamiento"] = config.apalancamiento
    if config.margen_operacion is not None:
        updates["margen_operacion"] = config.margen_operacion
    if config.modo_sistema is not None:
        updates["modo_sistema"] = config.modo_sistema

    if not updates:
        raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")

    try:
        set_clause = ", ".join(
            f"{k} = %s" for k in updates.keys()
        )
        # Agregar updated_at
        set_clause += ", updated_at = NOW()"
        values = list(updates.values()) + [1]

        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE hermes_config SET {set_clause} WHERE id = %s",
                values,
            )
            if cur.rowcount == 0:
                conn.rollback()
                conn.close()
                raise HTTPException(status_code=404, detail="Config no encontrada")
        conn.commit()
        conn.close()

        # Retornar la config actualizada
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM hermes_config WHERE id = 1")
            row = cur.fetchone()
        conn.close()

        data = serialize_row(row)
        return {
            "ok": True,
            "data": data,
            "calibration": snake_to_camel(data),
            "updated": list(updates.keys()),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error actualizando configuración: {str(e)}"
        )


# ── Endpoint: GET /api/v1/alertas ───────────────────────────
@app.get("/api/v1/alertas")
async def get_alertas(limit: int = 10):
    """
    Retorna los últimos N registros de hermes_alertas.
    Default: 10, Máximo: 100.
    """
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, timestamp, tipo, mensaje
                FROM hermes_alertas
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        conn.close()

        return {
            "ok": True,
            "data": [serialize_row(r) for r in rows],
            "count": len(rows),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error consultando alertas: {str(e)}"
        )


# ── Endpoint: GET /api/v1/poc ───────────────────────────────
@app.get("/api/v1/poc")
async def get_poc():
    """
    Retorna el Point of Control (POC): el nivel de precio con
    mayor volumen acumulado en las últimas 2 horas.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT price_bucket, total_volume
                FROM volume_profile
                WHERE updated_at > NOW() - INTERVAL '2 hours'
                ORDER BY total_volume DESC
                LIMIT 1
                """
            )
            poc = cur.fetchone()
        conn.close()

        if not poc:
            return {
                "ok": True,
                "poc_precio": None,
                "poc_volumen": None,
                "message": "Aún acumulando datos de perfil de volumen",
            }

        return {
            "ok": True,
            "poc_precio": float(poc["price_bucket"]),
            "poc_volumen": float(poc["total_volume"]),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error consultando POC: {str(e)}"
        )


# ── Endpoint: GET /api/v1/radar ─────────────────────────────
@app.get("/api/v1/radar")
async def get_radar():
    """
    Radar de Confirmación Algorítmica.
    Compara los valores actuales de mercado contra los umbrales
    de configuración para mostrar al trader qué condiciones se cumplen.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)

        # 1. Última métrica disponible + liquidaciones acumuladas en 1 minuto
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM metricas_btc ORDER BY timestamp DESC LIMIT 1"
            )
            latest = cur.fetchone()

        # 1b. Liquidaciones acumuladas en ventana de 1 minuto (no solo la última fila que se resetea cada 5s)
        liq_longs = 0.0
        liq_shorts = 0.0
        if latest:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT COALESCE(SUM(liquidaciones_longs), 0) as total_longs,
                              COALESCE(SUM(liquidaciones_shorts), 0) as total_shorts
                       FROM metricas_btc
                       WHERE timestamp > NOW() - INTERVAL '1 minute'"""
                )
                liq_row = cur.fetchone()
                liq_longs = float(liq_row["total_longs"] or 0)
                liq_shorts = float(liq_row["total_shorts"] or 0)

        # 2. Configuración vigente
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM hermes_config WHERE id = 1")
            config = cur.fetchone()

        conn.close()

        if not latest or not config:
            return {
                "ok": True,
                "radar": {
                    "barrido_liquidez": 0,
                    "barrido_liquidez_umbral": 500000,
                    "giro_cvd": 0,
                    "giro_cvd_umbral": 500000,
                    "soporte_ob_ratio": 0,
                    "soporte_ob_minimo": 1.5,
                    "estado": "ESPERANDO_DATOS",
                },
                "calibration": {},
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Calcular valores (liquidaciones desde ventana de 1 minuto, no solo última fila)
        barrido = liq_longs + liq_shorts

        cvd = float(latest.get("cvd_binance", 0) or 0)
        depth_b = float(latest.get("orderbook_depth_buyer", 0) or 0)
        depth_s = float(latest.get("orderbook_depth_seller", 0) or 0)
        ob_ratio = round(depth_b / depth_s, 2) if depth_s > 0 else 0

        umbral_liq = float(config.get("umbral_liquidaciones", 500000))
        umbral_cvd = float(config.get("delta_cvd_confirmacion", 500000))
        umbral_ob = 1.5

        # Determinar estado
        condiciones = 0
        if barrido >= umbral_liq:
            condiciones += 1
        if abs(cvd) >= umbral_cvd:
            condiciones += 1
        if ob_ratio >= umbral_ob:
            condiciones += 1

        if condiciones >= 2:
            estado = "CONFIRMADO"
        elif condiciones >= 1:
            estado = "ATENCION"
        else:
            estado = "BLOQUEADO"

        return {
            "ok": True,
            "radar": {
                "barrido_liquidez": round(barrido, 2),
                "barrido_liquidez_umbral": umbral_liq,
                "giro_cvd": round(abs(cvd), 2),
                "giro_cvd_umbral": umbral_cvd,
                "soporte_ob_ratio": ob_ratio,
                "soporte_ob_minimo": umbral_ob,
                "estado": estado,
                "condiciones_cumplidas": condiciones,
                "condiciones_necesarias": 3,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error consultando radar: {str(e)}",
        )


# ── Endpoint: GET /api/v1/executor/status ──────────────────
@app.get("/api/v1/executor/status")
async def get_executor_status():
    """
    Estado actual del Executor: modo, keys, trades hoy,
    circuit breaker, última señal detectada.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        max_trades = 5

        # 1. Config actual
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM hermes_config WHERE id = 1")
            config = cur.fetchone()

        # 2. Trades hoy (solo REAL, excluyendo cerrados)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM hermes_trades
                WHERE timestamp > NOW() - INTERVAL '24 hours'
                AND estado NOT IN ('CANCELADO', 'CLOSED', 'CLOSED_FORCE', 'FALLIDO', 'SIMULADO')
                AND modo = 'REAL'
                """
            )
            trades_hoy = cur.fetchone()[0]

        # 3. Último trade
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, timestamp, lado, precio_entrada, cantidad_btc,
                       valor_usd, stop_loss, take_profit, estado, modo, razon
                FROM hermes_trades
                ORDER BY timestamp DESC LIMIT 1
                """
            )
            ultimo_trade = cur.fetchone()

        # 4. Última señal de trading (no heartbeat, no sys)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, timestamp, tipo, mensaje
                FROM hermes_alertas
                WHERE tipo IN ('CVD_SIGNAL', 'BUY_PRESSURE_HIGH',
                               'SELL_PRESSURE_HIGH', 'LIQUIDATION_LONGS',
                               'LIQUIDATION_SHORTS', 'MURO_FILTER_BLOCK')
                ORDER BY timestamp DESC LIMIT 1
                """
            )
            ultima_senal = cur.fetchone()

        # 5. Último heartbeat del executor
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT timestamp, mensaje FROM hermes_alertas
                WHERE tipo = 'EXECUTOR_START'
                ORDER BY timestamp DESC LIMIT 1
                """
            )
            exec_start = cur.fetchone()

        # 6. Trades activos (EJECUTADO)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, lado, precio_entrada, cantidad_btc,
                       stop_loss, take_profit, timestamp,
                       EXTRACT(EPOCH FROM (NOW() - timestamp))/3600 as edad_horas
                FROM hermes_trades
                WHERE estado = 'EJECUTADO'
                ORDER BY timestamp DESC
                """
            )
            trades_activos = cur.fetchall()

        # 6b. Precio actual para P&L mark-to-market
        with conn.cursor() as cur:
            cur.execute("SELECT precio FROM metricas_btc ORDER BY timestamp DESC LIMIT 1")
            price_row = cur.fetchone()
            current_price = float(price_row[0]) if price_row else 0

        # 7. P&L del día (hoy, excluyendo SIMULACION)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(pnl_realizado), 0) as pnl_dia
                FROM hermes_trades
                WHERE timestamp > NOW() - INTERVAL '24 hours'
                AND estado IN ('TP_HIT', 'SL_HIT', 'CLOSED_FORCE')
                AND modo != 'SIMULACION'
                """
            )
            pnl_dia = float(cur.fetchone()[0])

        conn.close()

        modo = str(config.get("modo_sistema", "SIMULACION")) if config else "SIMULACION"
        cb_bloqueado = trades_hoy >= max_trades

        # Verificar si keys existen en entorno
        tiene_real = bool(os.getenv("EXCHANGE_API_KEY", ""))
        tiene_demo = bool(os.getenv("EXCHANGE_API_KEY_DEMO", ""))

        # Serializar último trade
        trade_data = None
        if ultimo_trade:
            trade_data = serialize_row(ultimo_trade)

        senal_data = None
        if ultima_senal:
            senal_data = serialize_row(ultima_senal)

        return {
            "ok": True,
            "executor": {
                "modo": modo,
                "keys": {
                    "real": tiene_real,
                    "demo": tiene_demo,
                },
                "trades_hoy": trades_hoy,
                "max_trades_dia": max_trades,
                "circuit_breaker": {
                    "bloqueado": cb_bloqueado,
                    "disponibles": max(0, max_trades - trades_hoy),
                    "total": max_trades,
                },
                "ultimo_trade": trade_data,
                "ultima_senal": senal_data,
                "ultimo_inicio": (
                    serialize_row(exec_start) if exec_start else None
                ),
                "trades_activos": len(trades_activos),
                "trades_activos_lista": [
                    {
                        "id": t["id"],
                        "lado": t["lado"],
                        "precio_entrada": float(t["precio_entrada"]),
                        "cantidad_btc": float(t["cantidad_btc"]) if t["cantidad_btc"] else 0,
                        "stop_loss": float(t["stop_loss"]) if t["stop_loss"] else 0,
                        "take_profit": float(t["take_profit"]) if t["take_profit"] else 0,
                        "edad_horas": round(float(t["edad_horas"]), 2),
                        "timestamp": t["timestamp"].isoformat(),
                        "pnl_estimado": round(
                            (float(t["precio_entrada"]) - current_price) * float(t["cantidad_btc"])
                            if t["lado"] == "SHORT" and current_price > 0
                            else (current_price - float(t["precio_entrada"])) * float(t["cantidad_btc"])
                            if t["lado"] == "LONG" and current_price > 0
                            else 0,
                            2,
                        ) if t["cantidad_btc"] else 0,
                    }
                    for t in trades_activos
                ],
                "pnl_dia": round(pnl_dia, 2),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error consultando estado del executor: {str(e)}",
        )


# ── Endpoint: GET /api/v1/trades ─────────────────────────────
@app.get("/api/v1/trades")
async def get_trades(limit: int = 20):
    """
    Retorna los trades recientes con su R-múltiple calculado.
    Para trades abiertos, calcula R mark-to-market con precio actual.
    Para trades cerrados, calcula R con balance_despues - balance_antes.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)

        # Precio actual para mark-to-market
        with conn.cursor() as cur:
            cur.execute("SELECT precio FROM metricas_btc ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
            current_price = float(row[0]) if row else 0

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, timestamp, lado, precio_entrada, cantidad_btc,
                       stop_loss, take_profit, estado, modo, razon,
                       balance_antes, balance_despues, apalancamiento_usado
                FROM hermes_trades
                ORDER BY timestamp DESC LIMIT %s
            """, (limit,))
            trades = cur.fetchall()

        conn.close()

        result = []
        for t in trades:
            entry = float(t["precio_entrada"])
            sl = float(t["stop_loss"])
            amount = float(t["cantidad_btc"])
            side = t["lado"]
            r_dist = abs(entry - sl) if sl > 0 else 300.0

            # Calcular P&L
            if t["balance_despues"] is not None:
                # Trade cerrado: P&L realizado
                pnl = float(t["balance_despues"]) - float(t["balance_antes"])
                pnl_type = "REALIZADO"
            elif current_price > 0:
                # Trade abierto: mark-to-market
                if side == "LONG":
                    pnl = (current_price - entry) * amount
                else:
                    pnl = (entry - current_price) * amount
                pnl_type = "MARK_TO_MARKET"
            else:
                pnl = 0.0
                pnl_type = "DESCONOCIDO"

            r_multiple = round(pnl / r_dist, 2) if r_dist > 0 else 0.0

            # Calculate exit_price for closed trades
            exit_price = None
            if t["estado"] in ("TP_HIT", "SL_HIT", "CLOSED_FORCE", "CLOSED", "CANCELADO") and t["balance_despues"] is not None:
                realized_pnl = float(t["balance_despues"]) - float(t["balance_antes"])
                if amount > 0 and abs(realized_pnl) > 0.001:
                    if side == "LONG":
                        exit_price = round(entry + (realized_pnl / amount), 2)
                    else:
                        exit_price = round(entry - (realized_pnl / amount), 2)
                else:
                    exit_price = entry  # No P&L = entry price
            elif t["estado"] in ("TP_HIT", "SL_HIT") and current_price > 0:
                # Approximate exit from pnl direction
                if current_price > 0 and amount > 0:
                    if side == "LONG":
                        exit_price = round(entry + (pnl / amount), 2)
                    else:
                        exit_price = round(entry - (pnl / amount), 2)

            result.append({
                "id": t["id"],
                "timestamp": t["timestamp"].isoformat() if t["timestamp"] else None,
                "side": t["lado"],
                "entry_price": round(entry, 2),
                "exit_price": exit_price,
                "amount_btc": round(amount, 5),
                "stop_loss": round(sl, 2) if sl > 0 else None,
                "take_profit": round(float(t["take_profit"]), 2) if t.get("take_profit") and float(t["take_profit"]) > 0 else None,
                "estado": t["estado"],
                "modo": t["modo"],
                "razon": t["razon"],
                "r_distance": round(r_dist, 2),
                "pnl_usd": round(pnl, 2),
                "pnl_type": pnl_type,
                "r_multiple": r_multiple,
                "apalancamiento": t["apalancamiento_usado"],
            })

        return {
            "ok": True,
            "trades": result,
            "count": len(result),
            "current_price": round(current_price, 2) if current_price > 0 else None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error consultando trades: {str(e)}",
        )


# ── Endpoint: GET /api/v1/position ───────────────────────────
@app.get("/api/v1/position")
async def get_position():
    """
    Retorna el estado de la posición activa con datos de gestión:
    - trade actual abierto (entry, SL actual, side, tamaño)
    - estado del SL (INICIAL / BREAK-EVEN / TRAILING)
    - P&L actual estimado
    - tiempo vivo
    - últimas alertas de gestión
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)

        # 1. Último trade EJECUTADO sin balance_despues (posición abierta)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, timestamp, lado, precio_entrada, cantidad_btc,
                       valor_usd, stop_loss, take_profit, apalancamiento_usado
                FROM hermes_trades
                WHERE estado = 'EJECUTADO'
                AND balance_despues IS NULL
                ORDER BY timestamp DESC LIMIT 1
            """)
            trade = cur.fetchone()

        if not trade:
            conn.close()
            return {"ok": True, "position": None, "message": "No hay posición abierta"}

        # 2. Precio actual + datos vivos de Binance
        live = get_binance_live_position()
        with conn.cursor() as cur:
            cur.execute("SELECT precio FROM metricas_btc ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
            current_price = float(row[0]) if row else 0

        # 3. Alertas de gestión recientes para este trade
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT tipo, mensaje, timestamp FROM hermes_alertas
                WHERE tipo IN ('POSITION_OPEN','MGMT_BREAK_EVEN','MGMT_TRAILING_SL','MGMT_TIME_OUT')
                AND mensaje LIKE %s
                ORDER BY timestamp DESC LIMIT 10
            """, (f"%#{trade['id']}%",))
            mgmt_alerts = cur.fetchall()

        conn.close()

        trade_id = trade["id"]
        side = trade["lado"]
        entry = float(trade["precio_entrada"])
        amount = float(trade["cantidad_btc"])
        sl_raw = trade.get("stop_loss", 0) or 0
        sl_initial = float(sl_raw)
        if sl_initial <= 0:
            sl_initial = (entry - 300.0) if side == "LONG" else (entry + 300.0)

        # ── Usar datos vivos de Binance (source of truth) ──
        if live and abs(float(live.get("positionAmt", 0))) > 0:
            leverage_used = int(float(live.get("leverage", 5)))
            mark_price = float(live.get("markPrice", current_price))
            pnl_usd = float(live.get("unRealizedProfit", 0))
            margin_usd = float(live.get("isolatedWallet", 0))
            live_source = "BINANCE"
        else:
            leverage_used = int(trade["apalancamiento_usado"])
            mark_price = current_price
            if current_price > 0:
                pnl_usd = ((mark_price - entry) * amount) if side == "LONG" else ((entry - mark_price) * amount)
            else:
                pnl_usd = 0
            margin_usd = (entry * amount) / leverage_used if leverage_used > 0 else 0
            live_source = "DB"

        # Determinar estado del SL desde las alertas
        sl_state = "INICIAL"
        for alert in mgmt_alerts:
            if alert["tipo"] == "MGMT_TRAILING_SL":
                sl_state = "TRAILING"
            elif alert["tipo"] == "MGMT_BREAK_EVEN" and sl_state != "TRAILING":
                sl_state = "BREAK-EVEN"

        # Extraer SL actual del último trailing o break-even
        current_sl = sl_initial
        for alert in mgmt_alerts:
            if alert["tipo"] in ("MGMT_BREAK_EVEN", "MGMT_TRAILING_SL"):
                match = re.search(r'\$(\d+\.?\d*)', alert["mensaje"])
                if match:
                    # Nos quedamos con el último (más reciente por el ORDER BY DESC)
                    current_sl = float(match.group(1))

        # Calcular derivados (usa mark_price que viene de Binance si está disponible)
        risk_per_btc = abs(entry - sl_initial)
        risk_usd = risk_per_btc * amount  # Riesgo real en dólares
        r_active = round(pnl_usd / risk_usd, 4) if risk_usd > 0 else 0.0
        # PnL% al estilo Binance: (PnL / Margen) * 100
        pnl_pct = round((pnl_usd / margin_usd) * 100, 2) if margin_usd > 0 else 0.0
        pnl_type = "MARK_TO_MARKET" if mark_price > 0 else "DESCONOCIDO"
        # Tiempo vivo
        open_time = trade["timestamp"]
        elapsed_hours = (datetime.now(timezone.utc) - open_time).total_seconds() / 3600

        return {
            "ok": True,
            "position": {
                "trade_id": trade_id,
                "side": side,
                "entry_price": round(entry, 2),
                "mark_price": round(mark_price, 2) if mark_price > 0 else None,
                "size": round(amount, 5),
                "leverage": leverage_used,
                "stop_loss": round(current_sl, 2),
                "sl_initial": round(sl_initial, 2),
                "sl_current": round(current_sl, 2),
                "sl_state": sl_state,
                "pnl": round(pnl_usd, 2),
                "pnl_usd": round(pnl_usd, 2),
                "pnl_pct": round(pnl_pct, 2),
                "risk_usd": round(risk_usd, 2),
                "risk_per_btc": round(risk_per_btc, 2),
                "margin_usd": round(margin_usd, 2),
                "r_active": r_active,
                "pnl_type": pnl_type,
                "elapsed_hours": round(elapsed_hours, 2),
                "max_hours": 8,
                "take_profit": round(float(trade["take_profit"]), 2) if trade.get("take_profit") and float(trade["take_profit"]) > 0 else None,
                "last_mgmt_alerts": [serialize_row(a) for a in mgmt_alerts[:5]],
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error consultando posición: {str(e)}",
        )


# ── Frontend estático (SPA) ────────────────────────────────────
FRONTEND_DIST = os.getenv("FRONTEND_DIST", "/home/hermes/tradersuko/dist")

if os.path.isdir(FRONTEND_DIST):
    app.mount(
        "/assets",
        StaticFiles(directory=f"{FRONTEND_DIST}/assets"),
        name="assets",
    )

    @app.get("/")
    async def serve_index():
        return FileResponse(f"{FRONTEND_DIST}/index.html")

    @app.get("/{filename:path}")
    async def serve_spa(filename: str):
        # No tocar rutas de API
        if filename.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        filepath = os.path.join(FRONTEND_DIST, filename)
        if os.path.isfile(filepath):
            return FileResponse(filepath)
        # SPA fallback → index.html
        return FileResponse(f"{FRONTEND_DIST}/index.html")
else:
    print(f"⚠️ Frontend dist no encontrado en {FRONTEND_DIST}. Solo API activa.")


# ── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "hermes_api:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level="info",
    )
