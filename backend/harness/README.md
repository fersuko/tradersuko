# Banco de pruebas de TraderSuko

Responde con datos la pregunta que llevaba meses contestándose a ciegas:

> **¿La estrategia tiene edge, o solo lo parecía porque el sensor mentía?**

## Por qué existe

Cada "mejora" histórica del bot se justificó con un backtest que corría sobre datos
contaminados (libro de 20 niveles, `cvd_okx` copiado, liquidaciones = heurística del CVD).
Este paquete es el testigo que faltaba.

## Regla madre

`core.decide()` **replica exactamente** `hermes_executor.evaluate_signal()`. Si no
coinciden, el harness es un testigo inválido. Por eso `validate.py` reconcilia el replay
contra los trades que el bot **realmente** ejecutó.

## Uso

```bash
cd /home/hermes/tradersuko/backend
PY=/home/hermes/hermes_trading/venv/bin/python3

$PY -m harness.validate --desde 2026-09-22     # credibilidad del replay
$PY -m harness.edge --dias 30                  # frecuencias + edge + poder predictivo
```

## Resultado de validación (26-sep-2026)

| prueba | resultado |
|---|---|
| serie en memoria vs SQL independiente | 25/25 ✅ |
| recuperar la fila que el bot usó | 100/100 (desfase mediano 4 s) |
| reproducir inputs (ratio y CVD) | 100/100 ✅ |
| **reproducir la DECISIÓN (trades desde 22-sep)** | **10/10 = 100% ✅** |
| reproducir la DECISIÓN (todos los trades) | 69/100 |

**Por qué no 100% global:** la lógica del bot **cambió con el tiempo**. Trades de julio se
ejecutaron sin filtro de tendencia (activado 15-ago-2026) y sin techo de CVD; los de
septiembre anteriores al 22, con el bug del `NOW()` congelado (la condición C pasaba
siempre). El harness modela la versión **actual**, y contra esa versión reproduce 10/10.
Validar trades viejos contra la lógica de hoy no es un fallo del harness: es un dato
—**el bot no tiene una sola lógica, tiene un historial de lógicas**— que hay que fijar en
`params.py` si se quiere backtestear hacia atrás.

## Hallazgos

### 1. Con el libro real, la condición B (2.0x) es de facto "nunca operar"

Ventana honesta (26-sep 07:13→13:00 UTC, 3,695 filas): ratio real bids/asks
**mediana 0.983**, p90 1.189, p99 1.381.

| umbral | % del tiempo que pasa |
|---|---|
| 2.00x (config actual) | **0.03%** |
| 1.50x (el del brain) | 0.35% |
| 1.30x | 2.73% |
| 1.20x | 8.93% |
| 1.10x | 21.41% |

### 2. El núcleo (CVD + tendencia) tiene edge bruto MUY delgado

30 días, 78,789 filas con condición A + tendencia:

- resultado medio **+0.117R**, mediana **−0.223R**
- ganadores 42.6% / perdedores 56.4%
- llegó a +1R: 35.9% · +2.5R: 9.9% · **+6R: 1.7%**
- excursión favorable media +1.14R, desfavorable 0.71R
- profit factor bruto **1.25**

**Perfil de boleto de lotería**: la media la sostienen ~1.7% de trades que llegan a 6R.

### 3. La condición B falsa no era ruido: era una escala MAL CALIBRADA

PnL por ratio registrado (251 trades):

| ratio FALSO | n | PnL medio | % ganadores |
|---|---|---|---|
| 2-3x | 70 | −0.092 | 42.9% |
| 3-5x | 73 | +0.081 | 46.6% |
| 5-8x | 29 | +0.660 | 48.3% |
| 8x+ | 79 | +0.248 | 50.6% |

La tasa de acierto **sí** sube con el ratio (42.9%→50.6%). O sea: el sensor de 20 niveles
no medía "un muro de compras" (lo que la estrategia creía), pero sí medía **algo** con poder
predictivo débil. El error no fue medir basura: fue **umbralizar una escala que no
correspondía al libro real**. Con el libro completo, "2.0x" significa el 0.03% superior; con
la rebanada de 20 niveles significaba "casi siempre".

## Salvedades (lo que estos números NO dicen)

1. **Los 78,789 "trades" son filas solapadas**, no observaciones independientes: hay una
   señal cada ~11 s, así que el tamaño muestral efectivo es órdenes de magnitud menor. Los
   porcentajes son indicativos; los intervalos de confianza serían enormes.
2. **Comisiones**: con margen 30% y 5x, el nocional es ~1.5× el balance. Ida y vuelta a
   taker (~0.1% del nocional) cuesta **~0.1R por trade**, o sea **~85% del edge bruto
   medido (+0.117R)**. Sin contar funding ni slippage. **El edge medido probablemente no
   sobrevive a los costes.**
3. **La simulación aproxima la gestión**: SL fijo 1R + BE a 2.5R + timeout. NO replica el
   trailing por swing-lows. La excursión además se mide sobre snapshots de ~5 s, así que
   los extremos reales son más grandes que los medidos (sesgo en ambos sentidos).
4. **El libro honesto tiene ~6 h.** No hay datos futuros suficientes para medir si el ratio
   REAL predice resultados. Eso requiere dejar correr el modo sombra días.
5. La condición C (liq ≥ $5M) es **inalcanzable** con el feed real (~$50k por evento).
   Cualquier edge que aportara históricamente venía del bug del `NOW()`.

## Siguiente

- Acumular días de libro honesto y volver a correr `edge.py` → medir el ratio REAL vs outcomes.
- Fijar en `params.py` las versiones históricas de la lógica para poder backtestear hacia atrás.
- Decidir con datos: sin condición B (¿edge?) / recalibrar B sobre el libro real / cambiar de entrada.
