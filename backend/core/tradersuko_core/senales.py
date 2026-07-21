"""
senales.py — Evaluación de señales de trading (genérico).

Sistema 2-de-3 condiciones:
  1. CVD (Cumulative Volume Delta) supera umbral
  2. Order book imbalance (muros) supera ratio
  3. Liquidaciones recientes superan umbral

Sin dependencia de ningún exchange específico.
"""

import logging
from decimal import Decimal
from typing import Optional

log = logging.getLogger("tradersuko.senales")

# ── Constantes default (sobreescribibles por instancia) ──────
DEFAULT_CVD_UMBRAL = 1_050_000
DEFAULT_LIQ_UMBRAL = 700_000
DEFAULT_MURO_RATIO = 1.5
SLIPPAGE_SL_PCT = Decimal("0.001")     # 0.1%
SLIPPAGE_TP_RATIO = Decimal("3.0")     # 1:3
MAX_TRADES_PER_DAY = 5
MAX_POSITION_HOURS = 2


def evaluar_senal(
    cvd: float,
    liquidaciones_1m: float,
    bids_total: float,
    asks_total: float,
    cvd_umbral: float = DEFAULT_CVD_UMBRAL,
    liq_umbral: float = DEFAULT_LIQ_UMBRAL,
    muro_ratio: float = DEFAULT_MURO_RATIO,
) -> tuple:
    """
    Evalúa las 3 condiciones y retorna (senal, razon, condiciones_cumplidas).

    Returns:
        senal: "LONG", "SHORT" o None
        razon: str descriptiva
        condiciones: int (0-3) cuántas condiciones se cumplieron
    """
    condiciones_long = 0
    condiciones_short = 0
    razones_long = []
    razones_short = []

    # ── Condición 1: CVD ──
    if cvd > cvd_umbral:
        condiciones_long += 1
        razones_long.append(f"CVD+ ${cvd:,.0f}")
    elif cvd < -cvd_umbral:
        condiciones_short += 1
        razones_short.append(f"CVD- ${abs(cvd):,.0f}")

    # ── Condición 2: Muros (Order Book Imbalance) ──
    if bids_total > 0 and asks_total > 0:
        ratio = bids_total / asks_total if asks_total > 0 else 99
        if ratio >= muro_ratio:
            condiciones_long += 1
            razones_long.append(f"Bids {ratio:.1f}x Asks")
        elif ratio <= (1 / muro_ratio):
            condiciones_short += 1
            razones_short.append(f"Asks {1/ratio:.1f}x Bids")
    elif bids_total > 0 and asks_total == 0:
        condiciones_long += 1
        razones_long.append("Solo Bids en libro")
    elif asks_total > 0 and bids_total == 0:
        condiciones_short += 1
        razones_short.append("Solo Asks en libro")

    # ── Condición 3: Liquidaciones ──
    if liquidaciones_1m > liq_umbral:
        condiciones_long += 1
        razones_long.append(f"Liq ${liquidaciones_1m:,.0f}")
    elif liquidaciones_1m < -liq_umbral:
        condiciones_short += 1
        razones_short.append(f"Liq ${abs(liquidaciones_1m):,.0f}")
    elif liquidaciones_1m > 0:
        condiciones_long += 1
        razones_long.append(f"Liq+ ${liquidaciones_1m:,.0f}")
    elif liquidaciones_1m < 0:
        condiciones_short += 1
        razones_short.append(f"Liq- ${abs(liquidaciones_1m):,.0f}")

    # ── Decisión 2-de-3 ──
    if condiciones_long >= 2:
        razon = "Señal LONG (2/3): " + " | ".join(razones_long[:3])
        return "LONG", razon, condiciones_long
    elif condiciones_short >= 2:
        razon = "Señal SHORT (2/3): " + " | ".join(razones_short[:3])
        return "SHORT", razon, condiciones_short

    return None, "Esperando condiciones", 0


def calcular_posicion(
    balance_usdt: float,
    precio: float,
    apalancamiento: int,
    margen_pct: float,
) -> dict:
    """
    Calcula tamaño de posición basado en balance, apalancamiento y margen.

    Returns:
        dict con: cantidad_btc, valor_usd, margen_usado
    """
    margen_usado = balance_usdt * (margen_pct / 100.0)
    valor_usd = margen_usado * apalancamiento
    cantidad = valor_usd / precio if precio > 0 else 0

    return {
        "cantidad": round(cantidad, 5),
        "valor_usd": round(valor_usd, 2),
        "margen_usado": round(margen_usado, 2),
    }


def calcular_sl_tp(
    precio_entrada: float, lado: str
) -> dict:
    """
    Calcula precios de Stop Loss y Take Profit según constantes globales.
    """
    sl_pct = float(SLIPPAGE_SL_PCT)
    tp_pct = float(SLIPPAGE_SL_PCT * SLIPPAGE_TP_RATIO)

    if lado == "LONG":
        sl = precio_entrada * (1 - sl_pct)
        tp = precio_entrada * (1 + tp_pct)
    else:
        sl = precio_entrada * (1 + sl_pct)
        tp = precio_entrada * (1 - tp_pct)

    return {
        "stop_loss": round(sl, 1),
        "take_profit": round(tp, 1),
    }


def circuit_breaker(
    conn, max_trades: int = MAX_TRADES_PER_DAY, modo: str = "REAL"
) -> tuple:
    """
    Verifica si se ha alcanzado el límite diario de trades.
    Retorna (permitido: bool, usados: int, max: int).
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM hermes_trades
                   WHERE estado IN ('EJECUTADO', 'CLOSED_FORCE', 'CLOSED_SL', 'CLOSED_TP')
                   AND modo = %s
                   AND timestamp > NOW() - INTERVAL '24 hours'""",
                (modo,),
            )
            usados = cur.fetchone()[0]
        return usados < max_trades, usados, max_trades
    except Exception as e:
        log.warning(f"⚠️ Error en circuit_breaker: {e}")
        return True, 0, max_trades
