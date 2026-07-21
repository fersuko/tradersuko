"""
modelos.py — Modelos de datos y validación (Pydantic v2).
"""

from pydantic import BaseModel, Field
from typing import Optional


class ConfigExchange(BaseModel):
    """Configuración de un exchange para una instancia."""
    nombre: str = "binance"
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = False
    testnet_api_key: str = ""
    testnet_api_secret: str = ""


class ConfigPar(BaseModel):
    """Configuración del par de trading."""
    simbolo: str = "BTC/USDT:USDT"
    simbolo_binance: str = "BTCUSDT"  # Binance spot symbol
    tick_size: float = 0.1
    step_size: float = 0.001


class ConfigEstrategia(BaseModel):
    """Parámetros de la estrategia."""
    apalancamiento: int = 99
    margen_operacion: float = 10.0  # porcentaje
    sl_pct: float = 0.001  # 0.1%
    tp_ratio: float = 3.0  # 1:3
    max_trades_dia: int = 5
    max_horas_posicion: int = 2
    umbral_cvd: float = 1_050_000
    umbral_liq: float = 700_000
    umbral_muro_ratio: float = 1.5


class InstanciaConfig(BaseModel):
    """Configuración completa de una instancia."""
    id: str = "default"           # ej: "binance_btc_real"
    etiqueta: str = "BTC Real"    # nombre visible
    exchange: ConfigExchange = ConfigExchange()
    par: ConfigPar = ConfigPar()
    estrategia: ConfigEstrategia = ConfigEstrategia()
    modo: str = "REAL"            # REAL | DEMO | SIMULACION


class ConfigUpdate(BaseModel):
    """Modelo para actualizar configuración vía API."""
    umbral_liquidaciones: Optional[float] = None
    delta_cvd_confirmacion: Optional[float] = None
    apalancamiento: Optional[int] = None
    margen_operacion: Optional[float] = None
    modo_sistema: Optional[str] = None
