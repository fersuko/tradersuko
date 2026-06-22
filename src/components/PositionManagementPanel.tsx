import React from 'react';
import type { PositionData } from '../types';
import { Target, ShieldAlert, Award } from 'lucide-react';

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
      <div className="glass-panel rounded-xl p-5 flex flex-col justify-center items-center h-[220px] border border-slate-800">
        <div className="w-6 h-6 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin mb-2" />
        <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Cargando Posición...</span>
      </div>
    );
  }

  if (!position) {
    return (
      <div className="glass-panel rounded-xl p-5 border border-slate-800 flex flex-col justify-center items-center h-[220px] text-center font-mono">
        <ShieldAlert className="w-6 h-6 text-slate-600 mb-2" />
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Sin Posición Activa</span>
        <span className="text-[9px] text-slate-600 mt-1 uppercase">Cerebro escaneando desbalances de liquidez</span>
      </div>
    );
  }

  const {
    symbol,
    side,
    entryPrice,
    markPrice,
    size,
    leverage,
    pnl,
    stopLoss,
    takeProfit,
    rActive,
    rDistance,
    pnlType
  } = position;

  const isLong = side === 'LONG';
  
  // Calcular porcentaje de PnL aproximado
  const pnlPercent = (entryPrice > 0)
    ? ((markPrice - entryPrice) / entryPrice) * 100 * leverage * (isLong ? 1 : -1)
    : 0;

  const isPnlPositive = pnl >= 0;

  // Determinar color de R-Múltiple según especificación:
  // - rojo < 0R -> text-brand-red
  // - blanco 0–0.9R -> text-slate-200
  // - verde 1–1.9R -> text-brand-green
  // - purpura >= 2R -> text-purple-400
  const getRColorClass = (r: number) => {
    if (r < 0) return 'text-brand-red text-glow-red';
    if (r >= 0 && r < 1.0) return 'text-slate-100';
    if (r >= 1.0 && r < 2.0) return 'text-brand-green text-glow-green';
    return 'text-purple-400 text-glow-purple'; // >= 2.0
  };

  return (
    <div className={`glass-panel rounded-xl p-5 border transition-all duration-300 ${
      isPnlPositive 
        ? 'border-brand-green/30 bg-brand-green/[0.01]' 
        : 'border-brand-red/20 bg-brand-red/[0.01]'
    }`}>
      
      {/* Cabecera */}
      <div className="flex items-center justify-between border-b border-slate-900 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-brand-cyan" />
          <h4 className="text-sm font-bold text-white tracking-wide uppercase font-mono">
            Position Management
          </h4>
        </div>
        <div className="flex items-center gap-2 font-mono text-[9px] font-bold">
          <span className={`px-2 py-0.5 rounded ${
            isLong ? 'bg-brand-green/10 text-brand-green border border-brand-green/20' : 'bg-brand-red/10 text-brand-red border border-brand-red/20'
          }`}>
            {side} {leverage}x
          </span>
          <span className="bg-slate-950 text-slate-400 px-2 py-0.5 rounded border border-slate-900">
            {symbol}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        
        {/* Lado Izquierdo: Precios y P&L */}
        <div className="flex flex-col justify-between font-mono">
          <div className="flex flex-col gap-1">
            <span className="text-[9px] text-slate-500 uppercase">PNL ABIERTO</span>
            <div className="flex items-baseline gap-1.5">
              <span className={`text-lg font-black tracking-tight ${isPnlPositive ? 'text-brand-green' : 'text-brand-red'}`}>
                {isPnlPositive ? '+' : ''}${pnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className={`text-[10px] font-bold ${isPnlPositive ? 'text-brand-green' : 'text-brand-red'}`}>
                ({isPnlPositive ? '+' : ''}{pnlPercent.toFixed(2)}%)
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-1.5 text-[10px] mt-3 pt-2.5 border-t border-slate-900/60">
            <div className="flex justify-between">
              <span className="text-slate-500">Entry Price:</span>
              <span className="text-white font-bold">${entryPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Mark Price:</span>
              <span className="text-slate-300">${markPrice.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Position Size:</span>
              <span className="text-slate-300">{size.toFixed(4)} BTC</span>
            </div>
          </div>
        </div>

        {/* Lado Derecho: R-Múltiple Activo */}
        <div className="flex flex-col items-center justify-center bg-slate-950/60 border border-slate-900 rounded-lg p-3 text-center font-mono">
          <span className="text-[9px] text-slate-500 uppercase font-black tracking-wider flex items-center gap-1">
            <Award className="w-3 h-3 text-slate-500" /> R-Múltiple Activo
          </span>
          
          <span className={`text-2xl font-black tracking-tight my-1 ${getRColorClass(rActive)}`}>
            {rActive >= 0 ? '+' : ''}{rActive.toFixed(2)}R
          </span>
          
          <div className="text-[9px] text-slate-500 uppercase mt-0.5">
            <span className="font-bold text-slate-400">{pnlType}</span>
            <span className="block text-[8px] text-slate-600 mt-0.5">
              ${pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} / $300 RIESGO
            </span>
          </div>

          {/* Distancia a SL */}
          <div className="w-full mt-3 pt-2 border-t border-slate-900 text-[8px] flex flex-col gap-1 items-stretch">
            <div className="flex justify-between text-slate-600">
              <span>DIST. SL:</span>
              <span className={rDistance >= 0 ? 'text-brand-green font-bold' : 'text-brand-red font-bold'}>
                {rDistance >= 0 ? '+' : ''}{rDistance.toFixed(2)}R
              </span>
            </div>
            {/* Barra indicadora rápida */}
            <div className="h-1 bg-slate-900 rounded-full overflow-hidden">
              <div 
                className={`h-full transition-all duration-500 ${rDistance >= 0 ? 'bg-brand-green' : 'bg-brand-red'}`} 
                style={{ width: `${Math.min(100, Math.max(0, (rDistance + 1) * 50))}%` }}
              />
            </div>
          </div>
        </div>

      </div>

      {/* Niveles de Stop Loss / Take Profit */}
      <div className="mt-4 pt-3 border-t border-slate-900/60 grid grid-cols-2 gap-4 font-mono text-[9px]">
        <div className="flex items-center justify-between bg-slate-950/30 px-2 py-1.5 rounded border border-slate-900/80">
          <span className="text-slate-500">STOP LOSS (SL):</span>
          <span className="text-brand-red font-black">${stopLoss.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
        </div>
        <div className="flex items-center justify-between bg-slate-950/30 px-2 py-1.5 rounded border border-slate-900/80">
          <span className="text-slate-500">TAKE PROFIT (TP):</span>
          <span className="text-brand-green font-black">
            {takeProfit ? `$${takeProfit.toLocaleString('en-US', { minimumFractionDigits: 2 })}` : 'N/A'}
          </span>
        </div>
      </div>

    </div>
  );
};
