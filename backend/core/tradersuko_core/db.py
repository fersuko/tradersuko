"""
db.py — Conexión y operaciones PostgreSQL compartidas.

Cada instancia usa su propio esquema o tabla con discriminador "fuente"
para permitir múltiples pares/exchanges en la misma BD.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras

log = logging.getLogger("tradersuko.db")

load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

# ── Pool de conexiones (simple, una por proceso) ──────────────
_conn: Optional[object] = None


def get_config() -> dict:
    """Retorna DB_CONFIG desde .env o defaults."""
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "dbname": os.getenv("DB_NAME", "hermes_trading"),
        "user": os.getenv("DB_USER", "hermes_trader"),
        "password": os.getenv("DB_PASS", "H3rm3s_Tr4d1ng_S3cur3_P4ss_2026!"),
    }


def connect() -> object:
    """Retorna conexión PostgreSQL (reusa si activa)."""
    global _conn
    if _conn is None or _conn.closed:
        cfg = get_config()
        _conn = psycopg2.connect(**cfg)
        _conn.autocommit = False
        log.info(f"✅ Conectado a PostgreSQL {cfg['host']}:{cfg['port']}/{cfg['dbname']}")
    return _conn


def close():
    """Cierra conexión si activa."""
    global _conn
    if _conn and not _conn.closed:
        _conn.close()
        _conn = None
        log.info("🔌 Conexión PostgreSQL cerrada")


def insert_alerta(tipo: str, mensaje: str, fuente: str = "default"):
    """Inserta alerta en hermes_alertas."""
    try:
        conn = connect()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO hermes_alertas (tipo, mensaje, fuente) VALUES (%s, %s, %s)",
                (tipo, mensaje, fuente),
            )
        conn.commit()
    except Exception as e:
        log.warning(f"⚠️ Error insertando alerta: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def load_config(conn) -> dict:
    """Carga configuración desde hermes_config (tabla global)."""
    config = {}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM hermes_config WHERE id = 1")
            row = cur.fetchone()
        if row:
            config = {
                "modo_sistema": str(row.get("modo_sistema", "SIMULACION")),
                "apalancamiento": int(row.get("apalancamiento", 10)),
                "margen_operacion": float(row.get("margen_operacion", 2.0)),
                "umbral_liquidaciones": float(row.get("umbral_liquidaciones", 300000.0)),
                "delta_cvd_confirmacion": float(row.get("delta_cvd_confirmacion", 500000.0)),
            }
    except Exception as e:
        log.warning(f"⚠️ Error cargando config: {e}")
    return config


def update_config(conn, updates: dict):
    """Actualiza configuración en hermes_config."""
    if not updates:
        return
    sets = ", ".join(f"{k} = %s" for k in updates)
    vals = list(updates.values())
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE hermes_config SET {sets} WHERE id = 1", vals)
        conn.commit()
        log.info(f"✅ Config actualizada: {updates}")
    except Exception as e:
        log.warning(f"⚠️ Error actualizando config: {e}")
        conn.rollback()
