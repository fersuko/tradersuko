"""Validación del harness contra la realidad.

REGLA MADRE: ningún componente es testigo válido de sí mismo.
=> El harness no puede validarse con el harness. Se valida contra:
   (1) los TRADES REALES que el bot ejecutó (hermes_trades)      -> la decisión
   (2) el campo `razon` que el propio bot escribió               -> los inputs usados
   (3) una implementación SQL independiente de VWAP/liq          -> la serie en memoria

Por qué (2) obliga a BUSCAR la fila: el bot registra el trade DESPUÉS de decidir (la orden
market tarda ~1-3 s y el registro otro poco), y metricas_btc inserta cada ~5 s. La fila
exacta que el bot leyó puede no ser la fila en el timestamp del trade. Por eso, para medir
FIDELIDAD DE LÓGICA, se busca en [ts-60s, ts+2s] la fila que mejor reproduce los inputs que
el propio bot escribió (CVD y ratio Bids/Asks del campo `razon`). Separar las dos cosas
importa: si la lógica está bien y lo que falla es recuperar la fila, eso NO es un bug del
harness; si la lógica no reproduce, el harness es un testigo inválido.

Uso:  python3 -m harness.validate [--limit N] [--ventana-s 60]
"""
from __future__ import annotations

import argparse
import datetime as dt
import re

from .core import Params, Serie, connect, decide, load_params, parse_razon_ratio


def load_rows(conn, since=None, until=None) -> list[dict]:
    q = ("SELECT timestamp, precio, volumen, cvd_binance, orderbook_depth_buyer, "
         "orderbook_depth_seller, funding_rate, liquidaciones_longs, liquidaciones_shorts, "
         "liq_real_longs, liq_real_shorts "
         "FROM metricas_btc WHERE precio > 0")
    args = []
    if since:
        q += " AND timestamp >= %s"
        args.append(since)
    if until:
        q += " AND timestamp <= %s"
        args.append(until)
    q += " ORDER BY timestamp ASC"
    with conn.cursor() as cur:
        cur.execute(q, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def sql_vwap(conn, ts, lookback_minutes: int):
    """Implementación SQL independiente (la del ejecutor, acotada a <= ts)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT precio, volumen, timestamp FROM metricas_btc "
            "WHERE precio > 0 AND volumen > 0 AND timestamp <= %s "
            "ORDER BY timestamp DESC LIMIT %s",
            (ts, lookback_minutes * 15),
        )
        rows = cur.fetchall()
    if len(rows) < 6:
        return None
    grupos = {}
    for precio, vol, rts in rows:          # DESC, igual que el ejecutor
        grupos[rts.replace(second=0, microsecond=0)] = (float(precio), float(vol))
    if len(grupos) < 2:
        return None
    return sum(p * v for p, v in grupos.values()) / sum(v for _, v in grupos.values())


def sql_liq_1m(conn, ts):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(liquidaciones_longs),0), COALESCE(SUM(liquidaciones_shorts),0) "
            "FROM metricas_btc WHERE timestamp > %s - INTERVAL '60 seconds' AND timestamp <= %s",
            (ts, ts),
        )
        return cur.fetchone()


def check_serie_vs_sql(conn, serie: Serie, n: int = 25) -> bool:
    """Auto-chequeo: la serie en memoria debe dar lo mismo que el SQL."""
    import random
    idxs = random.Random(7).sample(range(len(serie.rows)), min(n, len(serie.rows)))
    bad = 0
    for i in idxs:
        ts = serie.rows[i]["timestamp"]
        lm, ls = serie.vwap(i, 15), sql_vwap(conn, ts, 15)
        if (lm is None) != (ls is None) or (lm is not None and ls is not None and abs(lm - ls) > 0.01):
            bad += 1
            print(f"   ✗ VWAP difiere @{ts}: memoria={lm} sql={ls}")
        ml, ms = serie.liq_1m(i)
        sl, ss = sql_liq_1m(conn, ts)
        if abs(ml - float(sl)) > 0.01 or abs(ms - float(ss)) > 0.01:
            bad += 1
            print(f"   ✗ LIQ difiere @{ts}: memoria={ml}/{ms} sql={sl}/{ss}")
    print(f"   memoria vs SQL: {len(idxs) - bad}/{len(idxs)} muestras coinciden")
    return bad == 0


def real_trades(conn, limit=None, desde=None) -> list[dict]:
    base = ("SELECT timestamp, lado, precio_entrada, razon FROM hermes_trades "
            "WHERE modo='REAL' AND tipo='REAL' AND lado='LONG' AND precio_entrada > 0")
    if desde:
        base += f" AND timestamp >= '{desde}'"
    q = (f"SELECT * FROM ({base} ORDER BY timestamp DESC LIMIT {int(limit)}) s ORDER BY timestamp ASC"
         if limit else base + " ORDER BY timestamp ASC")
    with conn.cursor() as cur:
        cur.execute(q)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def parse_cvd(razon: str):
    m = re.search(r"CVD\+\s*\$([\d,]+)", razon or "")
    return float(m.group(1).replace(",", "")) if m else None


def find_best_row(serie: Serie, t, bot_ratio, bot_cvd, ventana_s=60):
    """Busca en [ts-ventana, ts+2s] la fila que mejor reproduce los inputs registrados."""
    j0 = serie.index_at_or_before(t["timestamp"] - dt.timedelta(seconds=ventana_s))
    j1 = serie.index_at_or_before(t["timestamp"] + dt.timedelta(seconds=2))
    if j0 is None or j1 is None:
        return None
    best = None
    for j in range(j0, j1 + 1):
        r = serie.rows[j]
        ds = float(r["orderbook_depth_seller"] or 0)
        if ds <= 0:
            continue
        ratio = float(r["orderbook_depth_buyer"] or 0) / ds
        cvd = abs(float(r["cvd_binance"] or 0))
        err = abs(ratio - bot_ratio) + abs(cvd - bot_cvd) / max(bot_cvd, 1)
        if best is None or err < best[0]:
            best = (err, j, ratio, cvd)
    return best


def validate(limit=None, ventana_s=60, desde=None):
    conn = connect()
    p = load_params(conn)
    print("=" * 78)
    print("VALIDADOR DEL HARNESS — ¿el replay reproduce al ejecutor?")
    print("=" * 78)
    print("\nPARÁMETROS EN USO (fuente única):")
    print(f"  cond A: cvd > 0 y |cvd| >= ${p.delta_cvd_confirmacion:,.0f}   "
          f"techo ${p.cvd_techo:,.0f}")
    print(f"  cond B: bids >= {p.b_ratio}x asks")
    print(f"  cond C: liq 1m >= ${p.umbral_liquidaciones:,.0f} y shorts > longs")
    print(f"  exige {p.min_condiciones}/3 | SL {p.sl_pct*100:.1f}% | TP {p.tp_r}R | BE {p.be_r}R | timeout {p.timeout_horas}h")
    print("\nDIVERGENCIAS REGISTRADAS (brain vs executor):")
    for d in p.divergencias:
        print(f"  • {d}")

    trades = real_trades(conn, limit, desde)
    print(f"\nTrades reales LONG a validar: {len(trades)}" + (f"  (desde {desde})" if desde else ""))
    since = (trades[0]["timestamp"] - dt.timedelta(hours=2)) if trades else None
    rows = load_rows(conn, since=since)
    serie = Serie(rows)
    print(f"Filas cargadas: {len(rows):,}")

    print("\n[1] Auto-chequeo: serie en memoria vs implementación SQL independiente")
    check_serie_vs_sql(conn, serie)

    # ── 2) ¿Se puede recuperar la fila que el bot usó? ──
    print(f"\n[2] Inputs: ¿existe una fila en [ts-{ventana_s}s, ts+2s] que reproduzca lo registrado?")
    recuperados = []
    for t in trades:
        br, bc = parse_razon_ratio(t["razon"]), parse_cvd(t["razon"])
        if br is None or bc is None:
            continue
        best = find_best_row(serie, t, br, bc, ventana_s)
        if best is None:
            continue
        err, j, ratio, cvd = best
        off = serie.rows[j]["timestamp"] - t["timestamp"]
        recuperados.append((t, j, ratio, cvd, br, bc, off))
    ok_r = sum(1 for x in recuperados if abs(x[2] - x[4]) < 0.15)
    ok_c = sum(1 for x in recuperados if abs(x[3] - x[5]) / max(x[5], 1) < 0.05)
    print(f"   fila recuperable: {len(recuperados)}/{len(trades)}")
    print(f"   ratio coincide (<0.15x): {ok_r}/{len(recuperados)}")
    print(f"   CVD   coincide (<5%):    {ok_c}/{len(recuperados)}")
    if recuperados:
        offs = sorted(abs(x[6].total_seconds()) for x in recuperados)
        print(f"   desfase del timestamp del trade vs fila usada: mediana {offs[len(offs)//2]:.0f}s  "
              f"max {offs[-1]:.0f}s")

    # ── 3) La prueba dura: ¿el replay reproduce la DECISIÓN? ──
    print("\n[3] Decisión: ¿el replay produce señal LONG en cada trade real?")
    print("    (se compara el n/3 que el bot escribió en `razon` con el del replay)")
    hits, misses = 0, []
    cond_igual = 0
    for t, j, ratio, cvd, br, bc, off in recuperados:
        tl, ts_ = serie.liq_1m(j)
        d = decide(serie.rows[j], tl, ts_, serie.vwap(j, 15), p)
        m = re.search(r"\((\d)/3\)", t["razon"] or "")
        bot_n = int(m.group(1)) if m else None
        if bot_n is not None and bot_n == d.condiciones:
            cond_igual += 1
        if d.dispara:
            hits += 1
        else:
            misses.append((t["timestamp"], d.condiciones, bot_n, d.bloqueado_por,
                           ", ".join(d.razones) or "sin condiciones"))
    tot = len(recuperados)
    rate = 100.0 * hits / tot if tot else 0.0
    print(f"   n/3 coincide con el registrado por el bot: {cond_igual}/{tot} "
          f"({100.0*cond_igual/max(tot,1):.1f}%)")
    print(f"   señal LONG reproducida: {hits}/{tot}  ({rate:.1f}%)")
    for ts, c, bot_n, blk, raz in misses[:10]:
        print(f"     ✗ {ts:%Y-%m-%d %H:%M} | replay {c}/3 vs bot {bot_n}/3 | block={blk} | {raz}")
    conn.close()
    print()
    return rate


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ventana-s", type=int, default=60)
    ap.add_argument("--desde", type=str, default=None,
                    help="solo trades desde esta fecha (ISO), ej. 2026-09-22")
    a = ap.parse_args()
    validate(a.limit, a.ventana_s, a.desde)
