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
      <div className="glass-panel rounded-xl p-5 flex flex-col justify-center items-center h-[160px]">
        <div className="w-6 h-6 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin mb-2" />
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
    <div className="glass-panel rounded-xl p-5 border border-slate-800 transition-all duration-300">
      {/* Cabecera */}
      <div className="flex items-center gap-2 mb-4 border-b border-slate-900 pb-3">
        <Layers className="w-4 h-4 text-brand-cyan text-glow-cyan" />
        <h4 className="text-sm font-bold text-white tracking-wide uppercase font-mono flex-1">
          Muros Institucionales (OB Depth 1%)
        </h4>
        <span className="text-[9px] font-mono text-slate-500 font-bold">
          LIVE TELEMETRY
        </span>
      </div>

      {/* Visualizador de Barras de Muros */}
      <div className="flex flex-col gap-3">
        {/* Leyenda y Datos numéricos */}
        <div className="flex justify-between items-center text-xs font-mono">
          <div className="flex flex-col">
            <span className="text-[10px] text-slate-500">BIDS (MURO COMPRA)</span>
            <span className="text-brand-green font-bold text-sm text-glow-green">
              {bids.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M
            </span>
          </div>
          <div className="text-center bg-slate-950 px-2 py-1 rounded border border-slate-900">
            <span className="text-[9px] text-slate-500 block">DIFERENCIAL</span>
            <span className={`text-xs font-bold ${isBidsDominant ? 'text-brand-green' : 'text-brand-red'}`}>
              {isBidsDominant ? '+' : ''}{(bids - asks).toLocaleString(undefined, { maximumFractionDigits: 1 })}M
            </span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[10px] text-slate-500">ASKS (MURO VENTA)</span>
            <span className="text-brand-red font-bold text-sm text-glow-red">
              {asks.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M
            </span>
          </div>
        </div>

        {/* Barra de Progreso Doble de Alto Contraste */}
        <div className="h-4 w-full bg-slate-950 rounded overflow-hidden flex border border-slate-850 p-0.5">
          <div
            style={{ width: `${bidsPercent}%` }}
            className="bg-brand-green/85 hover:bg-brand-green h-full transition-all duration-500 ease-out rounded-l relative"
            title={`Bids: ${bidsPercent.toFixed(1)}%`}
          >
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-[9px] font-black text-black font-mono">
              {bidsPercent.toFixed(0)}%
            </span>
          </div>
          <div
            style={{ width: `${asksPercent}%` }}
            className="bg-brand-red/85 hover:bg-brand-red h-full transition-all duration-500 ease-out rounded-r relative"
            title={`Asks: ${asksPercent.toFixed(1)}%`}
          >
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-black text-black font-mono">
              {asksPercent.toFixed(0)}%
            </span>
          </div>
        </div>
      </div>

      {/* Indicador de Filtro de Muros de Seguridad */}
      <div className="mt-4 pt-3 border-t border-slate-900">
        <span className="text-[9px] text-slate-500 font-mono font-bold block mb-1.5">
          FILTRO DE MUROS DE SEGURIDAD
        </span>

        {isSafe ? (
          <div className="p-3 rounded-lg border border-brand-green/20 bg-brand-green/5 text-brand-green flex items-start gap-2.5 text-xs font-mono font-semibold animate-pulse shadow-lg shadow-brand-green/5">
            <ShieldCheck className="w-4 h-4 text-brand-green shrink-0 mt-0.5 text-glow-green" />
            <div className="flex-1 leading-normal">
              <span className="text-white font-bold block text-[10px]">RESPALDADO POR LIQUIDEZ INSTITUCIONAL</span>
              <span>Trade seguro. Ratio de imbalance actual: {ratio.toFixed(2)}x (mínimo 1.5x)</span>
            </div>
          </div>
        ) : (
          <div className="p-3 rounded-lg border border-amber-500/20 bg-amber-500/5 text-amber-400 flex items-start gap-2.5 text-xs font-mono font-semibold">
            <ShieldAlert className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
            <div className="flex-1 leading-normal">
              <span className="text-white font-bold block text-[10px]">BLOQUEADO POR FALTA DE LIQUIDEZ INSTITUCIONAL</span>
              <span>Liquidez neutral/riesgosa. Ratio actual: {ratio.toFixed(2)}x (muro débil)</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
