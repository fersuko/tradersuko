import React from 'react';
import type { TelemetriaRegistro } from '../types';
import { ShieldCheck, ShieldAlert, Layers } from 'lucide-react';

interface OrderBookDepthWidgetProps {
  latestRecord: TelemetriaRegistro | undefined;
  isLoading: boolean;
}

export const OrderBookDepthWidget: React.FC<OrderBookDepthWidgetProps> = ({ latestRecord, isLoading }) => {
  if (isLoading || !latestRecord) {
    return (
      <div className="glass-panel rounded-xl p-4 flex flex-col justify-center items-center h-full min-h-[160px] border border-slate-800">
        <div className="w-5 h-5 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin mb-1" />
        <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Cargando Muros...</span>
      </div>
    );
  }

  const bids = latestRecord.orderbook_depth_buyer;
  const asks = latestRecord.orderbook_depth_seller;
  const total = bids + asks;
  
  // Porcentajes para la barra de progreso
  const bidsPercent = total > 0 ? (bids / total) * 100 : 50;
  const asksPercent = total > 0 ? (asks / total) * 100 : 50;

  // Calcular el ratio dominante
  const isBidsDominant = bids >= asks;
  const ratio = isBidsDominant 
    ? (asks > 0 ? bids / asks : bids) 
    : (bids > 0 ? asks / bids : asks);

  const isSafe = ratio >= 1.5;

  return (
    <div className="glass-panel rounded-xl p-4 border border-slate-800 transition-all duration-300 h-full">
      {/* Cabecera */}
      <div className="flex items-center gap-2 mb-3 border-b border-slate-900 pb-2">
        <Layers className="w-3.5 h-3.5 text-brand-cyan text-glow-cyan" />
        <h4 className="text-xs font-bold text-white tracking-wide uppercase font-mono flex-1">
          Muros Institucionales
        </h4>
        <span className="text-[8px] font-mono text-slate-500 font-bold">
          OB 1%
        </span>
      </div>

      {/* Visualizador de Barras de Muros */}
      <div className="flex flex-col gap-2">
        {/* Leyenda y Datos numéricos */}
        <div className="flex justify-between items-center text-[10px] font-mono">
          <div className="flex flex-col">
            <span className="text-[8px] text-slate-500">BIDS</span>
            <span className="text-brand-green font-bold text-xs text-glow-green">
              {bids.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M
            </span>
          </div>
          <div className="text-center bg-slate-950 px-2 py-0.5 rounded border border-slate-900">
            <span className="text-[8px] text-slate-500 block">DIF</span>
            <span className={`text-[10px] font-bold ${isBidsDominant ? 'text-brand-green' : 'text-brand-red'}`}>
              {isBidsDominant ? '+' : ''}{(bids - asks).toLocaleString('en-US', { maximumFractionDigits: 1 })}M
            </span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[8px] text-slate-500">ASKS</span>
            <span className="text-brand-red font-bold text-xs text-glow-red">
              {asks.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M
            </span>
          </div>
        </div>

        {/* Barra de Progreso Doble */}
        <div className="h-3 w-full bg-slate-950 rounded overflow-hidden flex border border-slate-850 p-0.5">
          <div
            style={{ width: `${bidsPercent}%` }}
            className="bg-brand-green/85 h-full transition-all duration-500 ease-out rounded-l relative"
            title={`Bids: ${bidsPercent.toFixed(1)}%`}
          >
            <span className="absolute left-1 top-1/2 -translate-y-1/2 text-[7px] font-black text-black font-mono">
              {bidsPercent.toFixed(0)}%
            </span>
          </div>
          <div
            style={{ width: `${asksPercent}%` }}
            className="bg-brand-red/85 h-full transition-all duration-500 ease-out rounded-r relative"
            title={`Asks: ${asksPercent.toFixed(1)}%`}
          >
            <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[7px] font-black text-black font-mono">
              {asksPercent.toFixed(0)}%
            </span>
          </div>
        </div>
      </div>

      {/* Indicador compacto */}
      <div className="mt-2 pt-2 border-t border-slate-900">
        <div className={`p-2 rounded-lg border text-[9px] font-mono font-semibold flex items-center gap-1.5 ${
          isSafe 
            ? 'border-brand-green/20 bg-brand-green/5 text-brand-green animate-pulse' 
            : 'border-amber-500/20 bg-amber-500/5 text-amber-400'
        }`}>
          {isSafe ? (
            <ShieldCheck className="w-3 h-3 shrink-0" />
          ) : (
            <ShieldAlert className="w-3 h-3 shrink-0" />
          )}
          <span>{isSafe ? '✅ Respaldo institucional' : '⚠️ Muro débil'} — Ratio {ratio.toFixed(2)}x</span>
        </div>
      </div>
    </div>
  );
};
