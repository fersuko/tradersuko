import React from 'react';
import type { ExecutorStatus, PositionData, ModoSistema } from '../types';
import { Cpu, Play, Clock } from 'lucide-react';

interface TradingPanelProps {
  executor: ExecutorStatus | null;
  position: PositionData | null;
  isLoading: boolean;
}

export const TradingPanel: React.FC<TradingPanelProps> = ({
  executor,
  position,
  isLoading
}) => {
  if (isLoading || !executor) {
    return (
      <div className="glass-panel rounded-xl p-5 flex flex-col justify-center items-center h-[200px] border border-slate-800">
        <div className="w-6 h-6 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin mb-2" />
        <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Cargando...</span>
      </div>
    );
  }

  const { modo, tradesHoy, circuitBreaker, ultimoTrade, ultimaSenal } = executor;
  const hasPosition = position && position.pnl !== undefined;

  // 5 cuadritos de trades diarios
  const maxTrades = 5;
  const filledTrades = Math.min(maxTrades, Math.max(0, tradesHoy));

  // Formateador de tiempo relativo
  const formatTimeAgo = (isoString: string) => {
    try {
      const diffMs = Date.now() - new Date(isoString).getTime();
      const diffSecs = Math.floor(diffMs / 1000);
      if (diffSecs < 60) return `hace ${diffSecs}s`;
      const diffMins = Math.floor(diffSecs / 60);
      if (diffMins < 60) return `hace ${diffMins}m`;
      const diffHours = Math.floor(diffMins / 60);
      return `hace ${diffHours}h`;
    } catch {
      return '';
    }
  };

  const modeColors: Record<ModoSistema, { bg: string; text: string; label: string }> = {
    REAL: { bg: 'bg-brand-red/10 border-brand-red/30', text: 'text-brand-red', label: '🔥 REAL' },
    DEMO: { bg: 'bg-amber-500/10 border-amber-500/30', text: 'text-amber-400', label: '⚡ DEMO' },
    SIMULACION: { bg: 'bg-slate-800/50 border-slate-700', text: 'text-slate-400', label: '💤 SIMULACIÓN' },
  };

  const modeStyle = modeColors[modo] || modeColors.SIMULACION;

  return (
    <div className={`glass-panel rounded-xl p-4 border transition-all duration-300 ${
      modo === 'REAL'
        ? 'border-brand-red/35 bg-brand-red/[0.01] shadow-lg shadow-brand-red/5'
        : modo === 'DEMO'
        ? 'border-amber-500/25 bg-amber-500/[0.01]'
        : 'border-slate-800'
    }`}>

      {/* ── CABECERA ── */}
      <div className="flex items-center justify-between border-b border-slate-900 pb-3 mb-3">
        <div className="flex items-center gap-2">
          <Cpu className={`w-4 h-4 ${modo === 'REAL' ? 'text-brand-red animate-pulse' : modo === 'DEMO' ? 'text-amber-500 animate-pulse' : 'text-brand-cyan'}`} />
          <h4 className="text-sm font-bold text-white tracking-wide uppercase font-mono">
            Executor
          </h4>
          {/* Badge de modo (estático, sin dropdown) */}
          <span className={`text-[9px] font-black px-2 py-0.5 rounded border ${modeStyle.bg} ${modeStyle.text}`}>
            {modeStyle.label}
          </span>
          {/* Circuit breaker */}
          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
            circuitBreaker.bloqueado
              ? 'bg-brand-red/10 border border-brand-red/20 text-brand-red'
              : 'bg-brand-green/10 border border-brand-green/20 text-brand-green'
          }`}>
            {circuitBreaker.bloqueado ? '🔒' : '🔓'}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-3 font-mono">

        {/* ── CUADRITOS DE TRADES DIARIOS ── */}
        <div className="flex items-center gap-2">
          <span className="text-[8px] text-slate-500 uppercase tracking-wider">Trades Hoy:</span>
          <div className="flex gap-1">
            {Array.from({ length: maxTrades }).map((_, i) => (
              <div
                key={i}
                className={`w-5 h-5 rounded-sm border ${
                  i < filledTrades
                    ? modo === 'REAL'
                      ? 'bg-brand-red border-brand-red/60'
                      : modo === 'DEMO'
                      ? 'bg-amber-500 border-amber-500/60'
                      : 'bg-brand-cyan border-brand-cyan/60'
                    : 'bg-slate-900 border-slate-800'
                }`}
              />
            ))}
          </div>
          <span className="text-[10px] text-slate-400 font-bold">{tradesHoy}/{maxTrades}</span>
        </div>

        {/* ── POSICIÓN ACTIVA ── */}
        {hasPosition ? (
          <>
            <div className="border-t border-slate-900/60 pt-2">
              <div className="text-[8px] text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <Clock className="w-2.5 h-2.5" />
                POSICIÓN ACTIVA
              </div>
              <div className="bg-slate-950/40 rounded-lg p-2.5 border border-slate-900/80">
                {/* Precios grid */}
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Entry:</span>
                    <span className="text-white font-bold">${position.entryPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Mark:</span>
                    <span className="text-slate-300">${position.markPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Size:</span>
                    <span className="text-slate-300">{position.size.toFixed(4)} BTC</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Margin:</span>
                    <span className="text-yellow-400 font-bold">${position.marginUsd.toFixed(2)}</span>
                  </div>
                </div>

                {/* PnL grande */}
                <div className="flex items-center justify-between mt-2 pt-2 border-t border-slate-900/60">
                  <span className="text-[9px] text-slate-500 uppercase">PNL</span>
                  <div className="flex items-baseline gap-1.5">
                    <span className={`text-base font-black tracking-tight ${position.pnl >= 0 ? 'text-brand-green' : 'text-brand-red'}`}>
                      {position.pnl >= 0 ? '+' : ''}${position.pnl.toFixed(2)}
                    </span>
                    <span className={`text-[10px] font-bold ${position.pnl >= 0 ? 'text-brand-green' : 'text-brand-red'}`}>
                      ({position.pnl >= 0 ? '+' : ''}
                      {position.marginUsd > 0 ? ((position.pnl / position.marginUsd) * 100).toFixed(2) : '0.00'}%)
                    </span>
                  </div>
                </div>

                {/* SL / TP compactos */}
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <div className="flex items-center justify-between bg-slate-950/50 px-2 py-1 rounded border border-slate-900 text-[9px]">
                    <span className="text-slate-500">SL:</span>
                    <span className="text-brand-red font-black">${position.stopLoss.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex items-center justify-between bg-slate-950/50 px-2 py-1 rounded border border-slate-900 text-[9px]">
                    <span className="text-slate-500">TP:</span>
                    <span className="text-brand-green font-black">
                      {position.takeProfit ? `$${position.takeProfit.toLocaleString('en-US', { minimumFractionDigits: 2 })}` : 'N/A'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="border-t border-slate-900/60 pt-2">
            <div className="text-[8px] text-slate-500 uppercase tracking-wider mb-1">POSICIÓN ACTIVA</div>
            <div className="bg-slate-950/40 rounded-lg p-3 border border-slate-900/80 text-center">
              <span className="text-[10px] text-slate-600 font-mono">Sin posición abierta</span>
            </div>
          </div>
        )}

        {/* ── ÚLTIMA SEÑAL + ÚLTIMA EJECUCIÓN ── */}
        <div className="grid grid-cols-2 gap-2 border-t border-slate-900/60 pt-2">
          <div>
            <div className="flex justify-between text-slate-500 text-[8px] mb-0.5">
              <span>ÚLTIMA SEÑAL</span>
              {ultimaSenal && <span>{formatTimeAgo(ultimaSenal.timestamp)}</span>}
            </div>
            <div className="text-[10px] font-bold text-slate-300 bg-slate-950/40 p-1.5 rounded border border-slate-900 truncate">
              {ultimaSenal ? (
                <div className="flex items-center gap-1">
                  <Play className="w-2.5 h-2.5 text-brand-cyan" />
                  <span className="text-brand-cyan font-extrabold">{ultimaSenal.tipo}</span>
                  {ultimaSenal.mensaje && <span className="text-slate-400 font-medium truncate">- {ultimaSenal.mensaje}</span>}
                </div>
              ) : (
                <span className="text-slate-600 italic">Ninguna</span>
              )}
            </div>
          </div>
          <div>
            <div className="flex justify-between text-slate-500 text-[8px] mb-0.5">
              <span>ÚLT. EJECUCIÓN</span>
              {ultimoTrade && <span>{formatTimeAgo(ultimoTrade.timestamp)}</span>}
            </div>
            <div className="text-[10px] font-bold text-slate-300 bg-slate-950/40 p-1.5 rounded border border-slate-900 truncate">
              {ultimoTrade ? (
                <div className="flex items-center justify-between">
                  <span className={(ultimoTrade.tipo || '').includes('BUY') || (ultimoTrade.tipo || '').includes('LONG') ? 'text-brand-green' : 'text-brand-red'}>
                    {ultimoTrade.tipo || '---'}
                  </span>
                  <span className="text-white font-bold">
                    {ultimoTrade.precio && !isNaN(ultimoTrade.precio) ? `$${ultimoTrade.precio.toLocaleString('en-US')}` : '---'}
                  </span>
                </div>
              ) : (
                <span className="text-slate-600 italic">Sin ejecuciones</span>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
