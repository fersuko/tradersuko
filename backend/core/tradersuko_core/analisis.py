"""
analisis.py — Análisis de mercado y gestión de posiciones.

Contiene la lógica del BrainAnalyzer: interpretación de señales,
break-even, trailing SL, time-outs. Sin dependencia de exchange.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("tradersuko.analisis")

# ── Constantes por defecto ──
SWING_LOOKBACK = 12   # velas para swing low/high
CANDLE_MINUTES = 5    # tamaño de vela
PRESION_ALTA = 60     # >60% = presión compra fuerte
PRESION_BAJA = 40     # <40% = presión venta fuerte


def get_swing_levels(precios: list, lookback: int = SWING_LOOKBACK) -> dict:
    """
    Encuentra el swing low y swing high en los últimos N precios.
    Retorna {swing_low: float, swing_high: float}.
    """
    if len(precios) < 3:
        return {"swing_low": None, "swing_high": None}

    window = precios[-lookback:] if len(precios) > lookback else precios
    return {
        "swing_low": min(window),
        "swing_high": max(window),
    }


def evaluar_gestion_posicion(
    trade: dict,
    precio_actual: float,
    precio_entry: float,
    swing_low: Optional[float],
    swing_high: Optional[float],
    horas_abierto: float,
    max_horas: float = 2.0,
) -> list:
    """
    Evalúa si una posición necesita gestión (break-even, trailing, time-out).
    Retorna lista de alertas: [(tipo, mensaje), ...]
    """
    alertas = []
    lado = trade.get("lado", "LONG")
    pnl_pct = ((precio_actual - precio_entry) / precio_entry) * 100
    if lado == "SHORT":
        pnl_pct = -pnl_pct

    sl_actual = trade.get("stop_loss")
    if sl_actual is None:
        sl_actual = 0

    # 1. Break-Even: si PnL >= 1R (TP_RATIO del SL), mover SL a entrada
    # 1R ≈ SLIPPAGE_SL_PCT = 0.1%
    if pnl_pct >= 0.1 and sl_actual < precio_entry * 0.999 if lado == "LONG" else sl_actual > precio_entry * 1.001:
        alertas.append((
            "MGMT_BREAK_EVEN",
            f"#{trade['id']} Break-Even {lado} | "
            f"PnL {pnl_pct:.2f}% | ENTRY ${precio_entry:.2f} → SL a break-even",
        ))

    # 2. Trailing SL: si hay swing low/high y estamos en ganancia
    if pnl_pct >= 0.15:
        if lado == "LONG" and swing_low and swing_low > sl_actual:
            alertas.append((
                "MGMT_TRAILING_SL",
                f"#{trade['id']} Trailing {lado} | "
                f"Swing Low ${swing_low:.2f} → SL a ${swing_low:.2f}",
            ))
        elif lado == "SHORT" and swing_high and swing_high < sl_actual:
            alertas.append((
                "MGMT_TRAILING_SL",
                f"#{trade['id']} Trailing {lado} | "
                f"Swing High ${swing_high:.2f} → SL a ${swing_high:.2f}",
            ))

    # 3. Time-Out: si excede horas máximas
    if horas_abierto > max_horas:
        alertas.append((
            "MGMT_TIME_OUT",
            f"#{trade['id']} Time-Out {lado} | "
            f"{horas_abierto:.1f}h > {max_horas}h máx",
        ))

    return alertas


def evaluar_analisis_mercado(
    cvd: float,
    presion_compra: float,
    liquidaciones: float,
    muro_ratio: float,
    funding_rate: float = 0,
) -> dict:
    """
    Análisis completo de mercado basado en las 4 métricas.
    Retorna dict con señales y fuerza (0-100).
    """
    resultado = {
        "senal_principal": "NEUTRAL",
        "fuerza": 50,
        "factores": [],
    }

    # CVD momentum
    if abs(cvd) > 1_000_000:
        resultado["fuerza"] += 15 if cvd > 0 else -15
        resultado["factores"].append(f"CVD {'alcista' if cvd > 0 else 'bajista'} (${abs(cvd):,.0f})")

    # Presión de compra (>60% compra = alcista, <40% = bajista)
    if presion_compra > PRESION_ALTA:
        resultado["fuerza"] += 10
        resultado["factores"].append(f"Presión compra {presion_compra:.0f}%")
    elif presion_compra < PRESION_BAJA:
        resultado["fuerza"] -= 10
        resultado["factores"].append(f"Presión venta {100 - presion_compra:.0f}%")

    # Muros (order book imbalance)
    if muro_ratio >= 1.5:
        resultado["fuerza"] += 10
        resultado["factores"].append(f"Muros compradores {muro_ratio:.1f}x")
    elif muro_ratio <= 0.67:
        resultado["fuerza"] -= 10
        resultado["factores"].append(f"Muros vendedores {1/muro_ratio:.1f}x")

    # Liquidaciones
    if abs(liquidaciones) > 700_000:
        resultado["fuerza"] += 10 if liquidaciones > 0 else -10
        resultado["factores"].append(f"Liquidaciones {'alcistas' if liquidaciones > 0 else 'bajistas'}")

    # Funding rate extremo (contra-indicador)
    if abs(funding_rate) > 0.001:
        # Funding muy positivo = mercado sobre-comprado → señal bajista
        resultado["fuerza"] -= 10 if funding_rate > 0 else -10
        resultado["factores"].append(f"Funding extremo {funding_rate*100:.4f}%")

    # Determinar señal principal
    if resultado["fuerza"] >= 65:
        resultado["senal_principal"] = "LONG"
    elif resultado["fuerza"] <= 35:
        resultado["senal_principal"] = "SHORT"

    resultado["fuerza"] = max(0, min(100, resultado["fuerza"]))
    return resultado
