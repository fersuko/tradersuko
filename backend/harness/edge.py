"""Análisis de edge sobre datos honestos.

Tres preguntas, tres secciones:

  [A] FRECUENCIA — Con el libro REAL, ¿cada cuánto se cumple la condición B a cada umbral?
      (Antes: el 20-niveles daba 3-14x casi siempre. Ahora: libro completo ~1.0x.)
      Nota: esto NO es edge, es frecuencia. Con ~6h de libro honesto no hay outcomes aún.

  [B] EDGE DEL NÚCLEO — Todo lo demás (precio, CVD) SÍ es honesto desde junio. ¿Tiene edge
      la entrada de momentum (CVD + tendencia) medida por excursión favorable/desfavorable
      en unidades de R? Esto responde "¿el 83% no llega a +1R?" sin depender de la gestión.

  [C] ¿SIRVIÓ LA CONDICIÓN B FALSA? — Cada trade real guardó el ratio con el que entró
      ('Bids 9.2x Asks'). Si ese ratio no predice el PnL, la condición B era arbitraria.

Uso:  python3 -m harness.edge [--dias N] [--horizonte-h 16]
"""
from __future__ import annotations

import argparse
import datetime as dt
from collections import defaultdict

import numpy as np

from .core import Params, Serie, connect, decide, load_params, parse_razon_ratio

HONEST_BOOK_SINCE = dt.datetime(2026, 9, 26, 7, 13, tzinfo=dt.timezone.utc)  # fix del libro


def _load(conn, dias=None):
    q = ("SELECT timestamp, precio, volumen, cvd_binance, funding_rate, "
         "orderbook_depth_buyer, orderbook_depth_seller, "
         "liquidaciones_longs, liquidaciones_shorts "
         "FROM metricas_btc WHERE precio > 0")
    if dias:
        q += f" AND timestamp >= now() - interval '{int(dias)} days'"
    q += " ORDER BY timestamp ASC"
    with conn.cursor() as cur:
        cur.execute(q)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def seccion_a(conn, serie: Serie, p: Params):
    print("\n" + "=" * 78)
    print("[A] FRECUENCIA de la condición B con el libro REAL (desde el fix del 26-sep 07:13 UTC)")
    print("=" * 78)
    rows = [r for r in serie.rows if r["timestamp"] >= HONEST_BOOK_SINCE]
    if not rows:
        print("   sin filas honestas todavía")
        return
    ratios = []
    for r in rows:
        db = float(r["orderbook_depth_buyer"] or 0)
        ds = float(r["orderbook_depth_seller"] or 0)
        if ds > 0:
            ratios.append(db / ds)
    a = np.array(ratios)
    print(f"   filas: {len(a):,}  |  ventana: {rows[0]['timestamp']:%H:%M} -> {rows[-1]['timestamp']:%H:%M} UTC")
    print(f"   ratio real bids/asks -> mediana {np.median(a):.3f}  p90 {np.percentile(a,90):.3f}  "
          f"p99 {np.percentile(a,99):.3f}  max {a.max():.3f}")
    print(f"\n   {'umbral':>8} | {'% del tiempo que pasa':>22} | veredicto")
    for th in (2.0, 1.5, 1.3, 1.2, 1.1, 1.05, 1.0):
        pct = 100.0 * (a >= th).mean()
        v = "NUNCA opera" if pct < 0.5 else ("raro" if pct < 5 else "operaría")
        print(f"   {th:>7.2f}x | {pct:>21.2f}% | {v}")
    print("\n   (Comparación: el sensor FALSO de 20 niveles daba ratios de 2.4x-9.9x en los")
    print("    trades reales -> con el libro completo esa señal casi no existe.)")


def seccion_b(conn, serie: Serie, p: Params, horizonte_h: int = 16):
    print("\n" + "=" * 78)
    print(f"[B] EDGE DEL NÚCLEO — excursión en R tras señal de momentum (CVD + tendencia)")
    print("=" * 78)
    n = len(serie.rows)
    precio = np.array([float(r["precio"]) for r in serie.rows])
    ts = np.array([r["timestamp"].timestamp() for r in serie.rows])
    H = horizonte_h * 3600

    # Candidatos: condición A sola (CVD+ >= umbral, no agotado) y sin restricción de libro.
    cand = []
    for i, r in enumerate(serie.rows):
        cvd = float(r["cvd_binance"] or 0)
        if cvd > 0 and cvd >= p.delta_cvd_confirmacion and abs(cvd) <= p.cvd_techo:
            cand.append(i)
    print(f"   filas con condición A (CVD+ >= ${p.delta_cvd_confirmacion:,.0f}, no agotado): {len(cand):,}")

    def sim(i):
        """Simula un LONG desde precio[i]: SL 1R, TP 6R, BE a 2.5R, timeout H.

        Vectorizado. Aproximación documentada: NO replica el trailing por swing-lows
        (eso requeriría el orderflow tick a tick); usa el SL fijo + BE. El objetivo es
        medir EXCURSIÓN (MFE/MAE), que es independiente de la gestión.
        """
        v = serie.vwap(i, 15)
        if v is None or precio[i] < v:          # filtro de tendencia
            return None
        entry = precio[i]
        R = entry * p.sl_pct
        if R <= 0:
            return None
        end = ts[i] + H
        j = np.searchsorted(ts, end, side="right")
        seg = precio[i + 1:j]
        if seg.size == 0:
            return None

        run_max = np.maximum.accumulate(seg)

        def first_idx(mask):
            w = np.flatnonzero(mask)
            return int(w[0]) if w.size else None

        k_tp = first_idx(seg >= entry + p.tp_r * R)
        k_sl = first_idx(seg <= entry - R)
        k_be = first_idx((run_max >= entry + p.be_r * R) & (seg <= entry))

        eventos = [(k, kind) for k, kind in
                   ((k_tp, "tp"), (k_sl, "sl"), (k_be, "be")) if k is not None]
        if eventos:
            k, kind = min(eventos)
            pnl = {"tp": p.tp_r * R, "sl": -R, "be": 0.0}[kind]
        else:
            k = seg.size - 1
            pnl = float(seg[-1] - entry)
        k = min(k, seg.size - 1)
        mfe = float(run_max[k] - entry)
        mae = float(entry - seg[:k + 1].min())
        return pnl / R, mfe / R, mae / R

    res, mfes, maes = [], [], []
    for i in cand:
        r = sim(i)
        if r is None:
            continue
        res.append(r[0]); mfes.append(r[1]); maes.append(r[2])
    if res:
        res = np.array(res); mfes = np.array(mfes); maes = np.array(maes)
        print(f"\n   ── entrada de momentum + filtro de tendencia ──  n={len(res):,}")
        print(f"      resultado/gestión (R): media {res.mean():+.3f}  mediana {np.median(res):+.3f}  "
              f"total {res.sum():+.0f}R")
        print(f"      ganadores {(res>0.01).mean()*100:.1f}%   perdedores {(res<-0.01).mean()*100:.1f}%   "
              f"planos {(np.abs(res)<=0.01).mean()*100:.1f}%")
        print(f"      llegó a +1R: {(mfes>=1).mean()*100:.1f}%   +2.5R: {(mfes>=2.5).mean()*100:.1f}%   "
              f"+6R: {(mfes>=6).mean()*100:.1f}%")
        print(f"      excursión favorable media: {mfes.mean():+.2f}R   desfavorable media: {maes.mean():.2f}R")
        pf = res[res>0].sum()/max(abs(res[res<0].sum()), 1e-9)
        print(f"      profit factor bruto: {pf:.2f}")
    else:
        print("   sin señales")


def seccion_d(serie: Serie, p: Params, horizontes=(1, 2, 4)):
    """¿El ratio REAL del libro predice el retorno futuro?

    Se mide a horizontes CORTOS a propósito: una señal de order flow es de vida corta, y
    con horizonte corto se obtienen muchas más ventanas independientes por día que con las
    16h del timeout. Es la vía para tener una lectura en DÍAS en vez de en semanas.
    """
    print("\n" + "=" * 78)
    print("[D] ¿El ratio REAL predice el retorno futuro corto? (ventana honesta del libro)")
    print("=" * 78)
    precio = np.array([float(r["precio"]) for r in serie.rows])
    ts = np.array([r["timestamp"].timestamp() for r in serie.rows])
    idx = [i for i, r in enumerate(serie.rows)
           if r["timestamp"] >= HONEST_BOOK_SINCE and float(r["orderbook_depth_seller"] or 0) > 0]
    if len(idx) < 60:
        print(f"   muestra insuficiente todavía ({len(idx)} filas honestas) — volver más adelante")
        return
    ratios = np.array([float(serie.rows[i]["orderbook_depth_buyer"] or 0)
                       / float(serie.rows[i]["orderbook_depth_seller"]) for i in idx])
    print(f"   filas honestas: {len(idx):,}")
    for h in horizontes:
        rets = np.full(len(idx), np.nan)
        for k, i in enumerate(idx):
            j = int(np.searchsorted(ts, ts[i] + h * 3600, side="right")) - 1
            if j > i:
                rets[k] = precio[j] / precio[i] - 1.0
        ok = ~np.isnan(rets)
        if ok.sum() < 60:
            print(f"\n   ── horizonte {h}h ── ventana futura insuficiente "
                  f"({int(ok.sum())} filas con futuro completo)")
            continue
        q = np.quantile(ratios[ok], [0, 1/3, 2/3, 1.0])
        print(f"\n   ── horizonte {h}h ── n={int(ok.sum()):,}  "
              f"correlación ratio~retorno: {np.corrcoef(ratios[ok], rets[ok])[0,1]:+.3f}")
        print(f"      {'tercil de ratio':<18} {'n':>7} {'ret medio':>11} {'% positivo':>12}")
        for nombre, lo, hi in (("bajo", q[0], q[1]), ("medio", q[1], q[2]), ("alto", q[2], q[3])):
            sel = (ratios[ok] >= lo) & (ratios[ok] <= hi if nombre == "alto" else ratios[ok] < hi)
            if sel.sum() == 0:
                continue
            print(f"      {nombre:<18} {int(sel.sum()):>7} {rets[ok][sel].mean()*100:>10.4f}% "
                  f"{(rets[ok][sel] > 0).mean()*100:>11.1f}%")
    print("\n   Si el tercil ALTO no bate al BAJO, el ratio real no tiene poder predictivo")
    print("   (o el efecto es más largo que estos horizontes).")


def seccion_c(conn):
    print("\n" + "=" * 78)
    print("[C] ¿SIRVIÓ LA CONDICIÓN B FALSA? — ratio registrado vs PnL realizado")
    print("=" * 78)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT razon, pnl_realizado FROM hermes_trades "
            "WHERE modo='REAL' AND tipo='REAL' AND pnl_realizado IS NOT NULL "
            "AND razon LIKE '%Bids%' ORDER BY timestamp ASC"
        )
        rows = cur.fetchall()
    buckets = defaultdict(list)
    for razon, pnl in rows:
        r = parse_razon_ratio(razon)
        if r is None:
            continue
        if r < 3:      b = "2-3x (bajo)"
        elif r < 5:    b = "3-5x"
        elif r < 8:    b = "5-8x"
        else:          b = "8x+ (muy alto)"
        buckets[b].append(float(pnl))
    print(f"   trades con ratio registrado: {sum(len(v) for v in buckets.values())}")
    print(f"\n   {'bucket (ratio FALSO)':<22} {'n':>5} {'PnL total':>11} {'PnL medio':>11} {'% ganadores':>12}")
    for b in ("2-3x (bajo)", "3-5x", "5-8x", "8x+ (muy alto)"):
        v = buckets.get(b, [])
        if not v:
            continue
        a = np.array(v)
        print(f"   {b:<22} {len(a):>5} {a.sum():>+11.2f} {a.mean():>+11.3f} {(a>0).mean()*100:>11.1f}%")
    print("\n   Si el PnL medio NO sube con el ratio, la condición B no tenía poder predictivo.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=None)
    ap.add_argument("--horizonte-h", type=int, default=16)
    a = ap.parse_args()
    conn = connect()
    p = load_params(conn)
    rows = _load(conn, a.dias)
    print(f"filas cargadas: {len(rows):,}")
    serie = Serie(rows)
    seccion_a(conn, serie, p)
    seccion_b(conn, serie, p, a.horizonte_h)
    seccion_c(conn)
    seccion_d(serie, p)
    conn.close()
