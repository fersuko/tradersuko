"""Banco de pruebas de TraderSuko — núcleo.

POR QUÉ EXISTE
--------------
El bot se ha ido "mejorando" a ciegas durante meses: cada cambio se justificaba con un
backtest que corría sobre datos contaminados (libro de 20 niveles, cvd_okx copiado,
liquidaciones = heurística del CVD). Este paquete existe para poder responder con datos:

  ¿La estrategia tiene edge, o solo parece tenerlo porque el sensor mentía?

REGLA MADRE
-----------
`decide()` replica **exactamente** la lógica de `hermes_executor.evaluate_signal()`.
Si el harness y el ejecutor no coinciden, el harness es un testigo inválido y sus
conclusiones no valen nada. Por eso `validate.py` reconcilia el replay contra los trades
reales que el bot ejecutó (ground truth en `hermes_trades`).

FUENTE ÚNICA DE PARÁMETROS
--------------------------
Los parámetros viven en `hermes_config` (BD) + las constantes de `params.py`. Se documenta
explícitamente cada divergencia histórica entre `hermes_brain.py` y `hermes_executor.py`.
"""

from __future__ import annotations

import os
import re
import pathlib
from dataclasses import dataclass, field
from typing import Optional

BASE_DIR = pathlib.Path(__file__).resolve().parent
TRADING_DIR = BASE_DIR.parent          # /home/hermes/tradersuko/backend
RUNTIME_DIR = pathlib.Path("/home/hermes/hermes_trading")


# ── Credenciales: una sola fuente, SIN duplicar el secreto ────────────────
def _load_env_file(path: pathlib.Path) -> dict:
    """Parser mínimo de .env (sin dependencias)."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def db_config() -> dict:
    """Misma config que el ejecutor, leyendo .env. La contraseña NUNCA se imprime.

    Deuda conocida: la contraseña está hardcodeada en 9 .py del proyecto. Este módulo NO
    la duplica: exige DB_PASS en el entorno/.env y falla ruidosamente si falta.
    """
    env = _load_env_file(RUNTIME_DIR / ".env")
    cfg = {
        "host": os.getenv("DB_HOST") or env.get("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT") or env.get("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME") or env.get("DB_NAME", "hermes_trading"),
        "user": os.getenv("DB_USER") or env.get("DB_USER", "hermes_trader"),
        "password": os.getenv("DB_PASS") or env.get("DB_PASS"),
    }
    if not cfg["password"]:
        raise SystemExit(
            "FALTA DB_PASS. Ponlo en el entorno o en /home/hermes/hermes_trading/.env "
            "(el harness no guarda la contraseña en su propio código)."
        )
    return cfg


def connect(autocommit: bool = True):
    import psycopg2
    conn = psycopg2.connect(**db_config())
    conn.autocommit = autocommit
    return conn


# ── Parámetros ───────────────────────────────────────────────────────────
@dataclass
class Params:
    """Fuente única. `umbral_*` vienen de la BD; el resto son constantes del código."""
    # De hermes_config (BD)
    umbral_liquidaciones: float = 5_000_000.0      # condición C (liq 1m)
    delta_cvd_confirmacion: float = 2_000_000.0    # condición A
    cvd_techo: float = 25_000_000.0                # bloqueo por agotamiento
    apalancamiento: int = 5
    margen_operacion_pct: float = 30.0

    # Constantes del código (executor)
    funding_extremo: float = 0.001                 # 0.1% por 8h
    trend_filter_enabled: bool = True
    b_ratio: float = 2.0                           # condición B (executor)
    min_condiciones: int = 3                       # el executor exige 3/3

    # Gestión (executor)
    sl_pct: float = 0.010                          # SL 1.0% del entry
    tp_r: float = 6.0                              # TP = 6R
    be_r: float = 2.5                              # break-even a 2.5R
    timeout_horas: int = 16

    # ── Registro de DIVERGENCIAS conocidas (brain vs executor) ──
    divergencias: list = field(default_factory=lambda: [
        "condición B: executor 2.0x  vs  brain 1.5x (hermes_brain.py:523)",
        "condición B: el COMENTARIO del executor dice 1.5x pero el CÓDIGO usa 2.0x "
        "(hermes_executor.py:484 vs :493)",
        "MAX_POSITION_HOURS: brain 8h -> 16h (corregido 26-sep, commit bf0231a)",
        "break-even: repo decía 2.5R, runtime usaba 1.0R (corregido 26-sep, commit 9900d66)",
        "el ejecutor exige 3/3 condiciones, no 2/3 (el docstring dice '2-de-3')",
        "condición C (liq >= $5M) es subconjunto de A (cvd >= $2M) -> en la práctica son 2 condiciones",
    ])


def load_params(conn) -> Params:
    p = Params()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hermes_config WHERE id = 1")
            cols = [d[0] for d in cur.description]
            row = dict(zip(cols, cur.fetchone()))
        if row:
            p.umbral_liquidaciones = float(row.get("umbral_liquidaciones") or p.umbral_liquidaciones)
            p.delta_cvd_confirmacion = float(row.get("delta_cvd_confirmacion") or p.delta_cvd_confirmacion)
            p.cvd_techo = float(row.get("cvd_techo") or p.cvd_techo)
            p.apalancamiento = int(row.get("apalancamiento") or p.apalancamiento)
            p.margen_operacion_pct = float(row.get("margen_operacion") or p.margen_operacion_pct)
    except Exception as e:
        print(f"⚠️  No se pudo leer hermes_config ({e}); uso valores por defecto")
    return p


# ── Decisión (réplica fiel de evaluate_signal) ───────────────────────────
@dataclass
class Decision:
    signal: Optional[str]        # "LONG" | None
    condiciones: int
    razones: list
    bloqueado_por: Optional[str] = None

    @property
    def dispara(self) -> bool:
        return self.signal == "LONG"


def decide(row: dict, liq_longs_1m: float, liq_shorts_1m: float,
           vwap15: Optional[float], p: Params) -> Decision:
    """Réplica exacta de `hermes_executor.evaluate_signal` (v1.6.15, puro LONG).

    Orden idéntico: condiciones -> funding -> techo CVD -> tendencia.
    """
    precio = float(row.get("precio") or 0)
    cvd = float(row.get("cvd_binance") or 0)
    depth_b = float(row.get("orderbook_depth_buyer") or 0)
    depth_s = float(row.get("orderbook_depth_seller") or 0)
    funding = float(row.get("funding_rate") or 0)

    liq_ok = (liq_longs_1m + liq_shorts_1m) >= p.umbral_liquidaciones
    funding_bloquea_long = funding > p.funding_extremo
    cvd_exhausted = abs(cvd) > p.cvd_techo

    trend = None
    if p.trend_filter_enabled and vwap15 is not None:
        if precio < vwap15:
            trend = "SHORT_ONLY"
        elif precio > vwap15:
            trend = "LONG_ONLY"

    cond = 0
    razones: list[str] = []
    if cvd > 0 and abs(cvd) >= p.delta_cvd_confirmacion:
        cond += 1
        razones.append(f"CVD+ ${abs(cvd):,.0f}")
    if depth_s > 0 and depth_b >= depth_s * p.b_ratio:
        cond += 1
        razones.append(f"Bids {depth_b / depth_s:.1f}x Asks")
    if liq_ok and liq_shorts_1m > liq_longs_1m:
        cond += 1
        razones.append(f"Liq Shorts ${liq_shorts_1m:,.0f}")

    if cond >= p.min_condiciones:
        if funding_bloquea_long:
            return Decision(None, cond, razones, "funding")
        if cvd_exhausted:
            return Decision(None, cond, razones, "cvd_techo")
        if trend == "SHORT_ONLY":
            return Decision(None, cond, razones, "tendencia")
        return Decision("LONG", cond, razones, None)
    return Decision(None, cond, razones, None)


# ── Serie en memoria (para replay rápido, SIN lookahead) ─────────────────
class Serie:
    """Filas de metricas_btc en memoria, con VWAP y ventana de liquidaciones.

    Replica la semántica SQL del ejecutor pero acotada a `timestamp <= ts` para no
    introducir lookahead (el ejecutor en vivo solo ve el presente; el replay debe ver
    lo mismo o mide otra cosa).
    """

    def __init__(self, rows: list[dict]):
        self.rows = sorted(rows, key=lambda r: r["timestamp"])   # ASC
        self.ts = [r["timestamp"] for r in self.rows]
        import bisect
        self._bisect = bisect

    def at(self, i: int) -> dict:
        return self.rows[i]

    def index_at_or_before(self, ts) -> Optional[int]:
        """Índice de la última fila con timestamp <= ts (None si no hay)."""
        j = self._bisect.bisect_right(self.ts, ts) - 1
        return j if j >= 0 else None

    def vwap(self, i: int, lookback_minutes: int) -> Optional[float]:
        """VWAP del ejecutor: últimas lookback*15 filas con precio>0 y volumen>0,
        agrupadas por minuto (se queda con la fila que gana el último write en orden
        DESC = la MÁS ANTIGUA del minuto — replicado tal cual, aunque el comentario
        del ejecutor afirme lo contrario)."""
        limit_rows = lookback_minutes * 15
        if i < 0:
            return None
        # Ventana hacia atrás desde i, filtrando precio>0 & volumen>0
        picked = []
        k = i
        while k >= 0 and len(picked) < limit_rows:
            r = self.rows[k]
            if (r.get("precio") or 0) > 0 and (r.get("volumen") or 0) > 0:
                picked.append(r)
            k -= 1
        if len(picked) < 6:
            return None
        grupos: dict = {}
        for r in picked:                      # orden DESC, igual que el SQL
            key = r["timestamp"].replace(second=0, microsecond=0)
            grupos[key] = (float(r["precio"]), float(r["volumen"]))
        if len(grupos) < 2:
            return None
        num = sum(pr * vo for pr, vo in grupos.values())
        den = sum(vo for _, vo in grupos.values())
        return num / den if den else None

    def liq_1m(self, i: int) -> tuple[float, float]:
        """Suma de liquidaciones_longs/shorts en (ts-60s, ts]."""
        ts = self.rows[i]["timestamp"]
        lo = ts - __import__("datetime").timedelta(seconds=60)
        a = self._bisect.bisect_right(self.ts, lo)
        b = self._bisect.bisect_right(self.ts, ts)
        tl = ts_ = 0.0
        for j in range(a, b):
            tl += float(self.rows[j].get("liquidaciones_longs") or 0)
            ts_ += float(self.rows[j].get("liquidaciones_shorts") or 0)
        return tl, ts_


def parse_razon_ratio(razon: str) -> Optional[float]:
    """Extrae 'Bids 3.3x Asks' -> 3.3 del campo razon de los trades reales."""
    if not razon:
        return None
    m = re.search(r"Bids\s+([\d.]+)x\s+Asks", razon)
    return float(m.group(1)) if m else None
