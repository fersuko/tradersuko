import React, { useRef, useEffect } from 'react';
import { createChart, CrosshairMode, LineSeries, createSeriesMarkers } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, LineData, Time } from 'lightweight-charts';
import { BarChart3 } from 'lucide-react';
import type { TelemetriaRegistro, TradeData } from '../types';

interface Props {
  telemetria: TelemetriaRegistro[];
  trades: TradeData[];
  isLoading: boolean;
}

function parseTime(ts: string): Time {
  return Math.floor(new Date(ts).getTime() / 1000) as Time;
}

export const TradesChart: React.FC<Props> = ({ telemetria, trades, isLoading }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const markersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#0f1117' },
        textColor: '#64748b',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#334155',
        scaleMargins: { top: 0.05, bottom: 0.15 },
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 4,
        minBarSpacing: 2,
      },
      width: containerRef.current.clientWidth,
      height: 300,
    });

    const lineSeries = chart.addSeries(LineSeries, {
      color: '#22c55e',
      lineWidth: 1,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 3,
      priceFormat: {
        type: 'price',
        precision: 1,
        minMove: 0.1,
      },
      lastValueVisible: true,
      priceLineVisible: false,
    });

    chartRef.current = chart;
    priceSeriesRef.current = lineSeries;

    // ── Tooltip interactivo ──────────────────────────
    chart.subscribeCrosshairMove((param) => {
      const tooltip = document.getElementById('trades-chart-tooltip');
      if (!tooltip) return;

      if (!param.time || !param.point) {
        tooltip.style.display = 'none';
        return;
      }

      const clickTime = Number(param.time);
      const nearbyTrades = trades.filter((t) => {
        const tTime = Math.floor(new Date(t.timestamp).getTime() / 1000);
        return Math.abs(tTime - clickTime) < 60;
      });

      if (nearbyTrades.length > 0) {
        const trade = nearbyTrades[0];
        const isWin = trade.pnl >= 0;
        tooltip.style.display = 'block';
        tooltip.style.left = `${param.point.x + 15}px`;
        tooltip.style.top = `${param.point.y - 10}px`;
        tooltip.innerHTML = `
          <div style="font-size:10px;font-family:monospace;color:#94a3b8;">
            <strong style="color:${isWin ? '#22c55e' : '#ef4444'};">#${trade.id} ${trade.side}</strong><br/>
            Entry: $${trade.entryPrice.toFixed(1)}<br/>
            P&L: <span style="color:${isWin ? '#22c55e' : '#ef4444'}">${isWin ? '+' : ''}$${trade.pnl.toFixed(2)}</span><br/>
            ${trade.estado} · ${trade.modo}
          </div>
        `;
      } else {
        tooltip.style.display = 'none';
      }
    });

    // ── ResizeObserver ───────────────────────────────────
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect;
        chart.applyOptions({ width: Math.min(width, 1200) });
      }
    });
    if (containerRef.current) ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      priceSeriesRef.current = null;
    };
  }, []);

  // ── Actualizar datos ──────────────────────────────────
  useEffect(() => {
    const line = priceSeriesRef.current;
    if (!line) return;
    if (!telemetria.length) return;

    const lineData: LineData[] = telemetria.map((r) => ({
      time: parseTime(r.timestamp),
      value: r.precio,
    }));

    line.setData(lineData);

    const chart = chartRef.current;
    if (chart) {
      chart.timeScale().fitContent();
    }
  }, [telemetria]);

  // ── Actualizar marcadores ─────────────────────────────
  useEffect(() => {
    const line = priceSeriesRef.current;
    if (!line) return;
    if (!trades.length) return;

    // Crear o actualizar plugin de marcadores
    if (!markersRef.current) {
      markersRef.current = createSeriesMarkers<Time>(line);
    }

    const markers: any[] = trades.map((trade) => {
      const isWin = trade.pnl >= 0;
      return {
        time: parseTime(trade.timestamp),
        position: trade.side === 'LONG' ? 'belowBar' as const : 'aboveBar' as const,
        color: isWin ? '#22c55e' : '#ef4444',
        shape: trade.side === 'LONG' ? 'arrowUp' as const : 'arrowDown' as const,
        text: `#${trade.id} ${trade.side === 'LONG' ? 'L' : 'S'} $${trade.entryPrice.toFixed(1)}`,
        size: 1,
      };
    });

    markersRef.current!.setMarkers(markers);
  }, [trades]);

  return (
    <div className="w-full">
      <div className="flex items-center gap-3 p-4 pb-0">
        <BarChart3 className="w-4 h-4 text-brand-cyan" />
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400 font-mono">
          Precio BTC & Historial de Trades
        </h2>
        <div className="flex items-center gap-2 ml-auto">
          <span className="flex items-center gap-1.5 text-[10px] font-mono text-brand-green">
            <span className="w-2 h-2 rounded-full bg-brand-green" />
            LONG ✓
          </span>
          <span className="flex items-center gap-1.5 text-[10px] font-mono text-red-400">
            <span className="w-2 h-2 rounded-full bg-red-400" />
            SHORT ✗
          </span>
          <span className="flex items-center gap-1.5 text-[10px] font-mono text-green-500/70">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500/70" />
            Ganador
          </span>
          <span className="flex items-center gap-1.5 text-[10px] font-mono text-red-500/70">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500/70" />
            Perdedor
          </span>
        </div>
      </div>

      <div className="relative p-4">
        {isLoading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/60 backdrop-blur-sm rounded-xl">
            <div className="w-5 h-5 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        <div className="w-full rounded-xl overflow-hidden border border-slate-800/60 bg-[#0f1117]">
          <div ref={containerRef} className="w-full" />

          {/* Tooltip flotante para trades */}
          <div
            id="trades-chart-tooltip"
            style={{
              display: 'none',
              position: 'absolute',
              zIndex: 100,
              pointerEvents: 'none',
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '6px',
              padding: '6px 10px',
              boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
            }}
          />
        </div>

        {!isLoading && (!telemetria.length || !trades.length) && (
          <p className="text-center text-slate-600 text-xs font-mono mt-3">
            {!telemetria.length && !trades.length
              ? 'Esperando datos de precio y trades...'
              : !trades.length
              ? 'No hay trades registrados aún'
              : 'Cargando datos de precio...'}
          </p>
        )}
      </div>
    </div>
  );
};
