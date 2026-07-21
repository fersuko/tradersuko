import React from 'react';
import type { PositionData } from '../types';
import { Target, ShieldAlert } from 'lucide-react';

interface PositionManagementPanelProps {
  position: PositionData | null;
  isLoading: boolean;
}

export const PositionManagementPanel: React.FC<PositionManagementPanelProps> = ({
  position,
  isLoading
}) => {
  if (isLoading) {
    return (
      <div className="glass-panel rounded-xl p-5 flex flex-col justify-center items-center h-[180px] border border-slate-800">
        <div className="w-6 h-6 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin mb-2" />
        <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Cargando Posición...</span>
      </div>
    );
  }

  if (!position) {
    return (
      <div className="glass-panel rounded-xl p-5 border border-slate-800 flex flex-col justify-center items-center h-[180px] text-center font-mono">
        <ShieldAlert className="w-6 h-6 text-slate-600 mb-2" />
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Sin Posición Activa</span>
        <span className="text-[9px] text-slate-600 mt-1 uppercase">Cerebro escaneando desbalances de liquidez</span>
      </div>
    );
  }

  const {
    side,
    entryPrice,
    markPrice,
    size,
    leverage,
    pnl,
    stopLoss,
    takeProfit,
    marginUsd,
  } = position;

  const isLong = side === 'LONG';
  const isPnlPositive = pnl >= 0;

  // PnL% como Binance: PnL / Margen
  const pnlPercent = marginUsd > 0 ? (pnl / marginUsd) * 100 : 0;

  return (
    <div className={`glass-panel rounded-xl p-4 border transition-all duration-300 ${
      isPnlPositive 
        ? 'border-brand-green/30 bg-brand-green/[0.01]' 
        : 'border-brand-red/20 bg-brand-red/[0.01]'
    }`}>
      
      {/* Cabecera: SHORT 5x | BTCUSDT */}
      <div className="flex items-center justify-between border-b border-slate-900 pb-3 mb-3">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-brand-cyan" />
          <h4 className="text-sm font-bold text-white tracking-wide uppercase font-mono">
            Position
          </h4>
        </div>
        <div className="flex items-center gap-2 font-mono text-[9px] font-bold">
          <span className={`px-2 py-0.5 rounded ${
            isLong ? 'bg-brand-green/10 text-brand-green border border-brand-green/20' : 'bg-brand-red/10 text-brand-red border border-brand-red/20'
          }`}>
            {side} {leverage}x
          </span>
          <span className="bg-slate-950 text-slate-400 px-2 py-0.5 rounded border border-slate-900">
            BTCUSDT
          </span>
        </div>
      </div>

      {/* Grid 2 columnas */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 font-mono text-[11px]">
        
        {/* Columna izquierda: Entry, Mark, Size */}
        <div className="flex flex-col gap-1.5">
          <div className="flex justify-between">
            <span className="text-slate-500">Entry:</span>
            <span className="text-white font-bold">${entryPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Mark:</span>
            <span className="text-slate-300">${markPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Size:</span>
            <span className="text-slate-300">{size.toFixed(4)} BTC</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Margin:</span>
            <span className="text-yellow-400 font-bold">${marginUsd.toFixed(2)}</span>
          </div>
        </div>

        {/* Columna derecha: PnL, ROI */}
        <div className="flex flex-col gap-1.5 items-end">
          <div className="flex flex-col items-end">
            <span className="text-[9px] text-slate-500 uppercase">PNL</span>
            <div className="flex items-baseline gap-1.5">
              <span className={`text-lg font-black tracking-tight ${isPnlPositive ? 'text-brand-green' : 'text-brand-red'}`}>
                {isPnlPositive ? '+' : ''}${pnl.toFixed(2)}
              </span>
              <span className={`text-[10px] font-bold ${isPnlPositive ? 'text-brand-green' : 'text-brand-red'}`}>
                ({isPnlPositive ? '+' : ''}{pnlPercent.toFixed(2)}%)
              </span>
            </div>
          </div>
          <div className="flex items-center gap-1 text-[9px] text-slate-600 mt-0.5">
            <span>{isLong ? 'Entry > Mark = Loss' : 'Entry < Mark = Loss'}</span>
          </div>
        </div>
      </div>

      {/* SL / TP */}
      <div className="mt-3 pt-2.5 border-t border-slate-900/60 grid grid-cols-2 gap-3 font-mono text-[10px]">
        <div className="flex items-center justify-between bg-slate-950/30 px-2.5 py-1.5 rounded border border-slate-900/80">
          <span className="text-slate-500">SL:</span>
          <span className="text-brand-red font-black">${stopLoss.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
        </div>
        <div className="flex items-center justify-between bg-slate-950/30 px-2.5 py-1.5 rounded border border-slate-900/80">
          <span className="text-slate-500">TP:</span>
          <span className="text-brand-green font-black">
            {takeProfit ? `$${takeProfit.toLocaleString('en-US', { minimumFractionDigits: 2 })}` : 'N/A'}
          </span>
        </div>
      </div>

    </div>
  );
};
