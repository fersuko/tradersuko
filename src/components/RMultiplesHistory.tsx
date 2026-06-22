import React from 'react';
import type { TradeData } from '../types';
import { CalendarRange, TrendingUp, TrendingDown } from 'lucide-react';

interface RMultiplesHistoryProps {
  trades: TradeData[];
  isLoading: boolean;
}

export const RMultiplesHistory: React.FC<RMultiplesHistoryProps> = ({
  trades,
  isLoading
}) => {
  if (isLoading) {
    return (
      <div className="glass-panel rounded-xl p-5 flex flex-col justify-center items-center h-[260px] border border-slate-800">
        <div className="w-6 h-6 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin mb-2" />
        <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Cargando Historial R...</span>
      </div>
    );
  }

  // Cálculos estadísticos
  const totalTrades = trades.length;
  const profitableTrades = trades.filter(t => t.rMultiple > 0).length;
  
  const winRate = totalTrades > 0 
    ? Math.round((profitableTrades / totalTrades) * 100) 
    : 0;

  const rMultiplesList = trades.map(t => t.rMultiple);
  const bestR = rMultiplesList.length > 0 ? Math.max(...rMultiplesList) : 0;
  const worstR = rMultiplesList.length > 0 ? Math.min(...rMultiplesList) : 0;

  // Formateador de tiempo corto
  const formatShortTime = (timestampStr: string) => {
    try {
      const date = new Date(timestampStr);
      return date.toLocaleTimeString(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
      });
    } catch {
      return timestampStr;
    }
  };

  return (
    <div className="glass-panel rounded-xl p-5 border border-slate-800 w-full transition-all duration-300">
      
      {/* Cabecera y Resumen */}
      <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-slate-900 pb-4 mb-4 gap-4">
        
        {/* Título */}
        <div className="flex items-center gap-2">
          <CalendarRange className="w-4 h-4 text-brand-cyan" />
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider font-mono">
              R-Resultados Históricos
            </h3>
            <p className="text-[9px] text-slate-500 font-mono mt-0.5">
              Auditoría cuantitativa de riesgo-retorno
            </p>
          </div>
        </div>

        {/* Tarjetas de Estadísticas Rápidas */}
        <div className="grid grid-cols-3 gap-6 font-mono text-center">
          
          <div className="bg-slate-950/50 border border-slate-900 rounded px-4 py-1.5 min-w-[90px]">
            <span className="text-[8px] text-slate-500 block uppercase font-bold">Win Rate</span>
            <span className={`text-sm font-black ${winRate >= 50 ? 'text-brand-green' : 'text-slate-300'}`}>
              {winRate}%
            </span>
          </div>

          <div className="bg-slate-950/50 border border-slate-900 rounded px-4 py-1.5 min-w-[90px]">
            <span className="text-[8px] text-slate-500 block uppercase font-bold">Mejor R</span>
            <span className={`text-sm font-black flex items-center justify-center gap-0.5 ${bestR > 0 ? 'text-purple-400 text-glow-purple' : 'text-slate-400'}`}>
              <TrendingUp className="w-3.5 h-3.5 text-purple-400" />
              {bestR >= 0 ? '+' : ''}{bestR.toFixed(1)}R
            </span>
          </div>

          <div className="bg-slate-950/50 border border-slate-900 rounded px-4 py-1.5 min-w-[90px]">
            <span className="text-[8px] text-slate-500 block uppercase font-bold">Peor R</span>
            <span className={`text-sm font-black flex items-center justify-center gap-0.5 ${worstR < 0 ? 'text-brand-red' : 'text-slate-400'}`}>
              <TrendingDown className="w-3.5 h-3.5 text-brand-red" />
              {worstR >= 0 ? '+' : ''}{worstR.toFixed(1)}R
            </span>
          </div>

        </div>

      </div>

      {/* Tabla del Historial de Operaciones */}
      <div className="overflow-x-auto bg-slate-950/40 rounded border border-slate-900 font-mono text-[10px]">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-950 border-b border-slate-900 text-slate-500 uppercase tracking-wider font-bold">
              <th className="px-4 py-2 border-r border-slate-900 w-12 text-center">#</th>
              <th className="px-4 py-2 border-r border-slate-900 w-16">Hora</th>
              <th className="px-4 py-2 border-r border-slate-900 w-12 text-center">S</th>
              <th className="px-4 py-2 border-r border-slate-900">Entry Price</th>
              <th className="px-4 py-2 border-r border-slate-900 text-center w-24">R-Múltiple</th>
              <th className="px-4 py-2 text-right w-28">P&L (USD)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900 text-slate-300">
            {totalTrades === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-600 italic">
                  Ningún trade registrado en el historial
                </td>
              </tr>
            ) : (
              trades.slice(0, 15).map((trade) => {
                const isWin = trade.rMultiple >= 0;
                return (
                  <tr key={trade.id} className="hover:bg-slate-900/40 transition-colors">
                    <td className="px-4 py-2 border-r border-slate-900 text-slate-600 text-center">{trade.id}</td>
                    <td className="px-4 py-2 border-r border-slate-900 text-slate-400">{formatShortTime(trade.timestamp)}</td>
                    <td className="px-4 py-2 border-r border-slate-900 text-center font-bold">
                      <span className={trade.side === 'LONG' ? 'text-brand-green' : 'text-brand-red'}>
                        {trade.side === 'LONG' ? 'L' : 'S'}
                      </span>
                    </td>
                    <td className="px-4 py-2 border-r border-slate-900 font-bold">${trade.entryPrice.toLocaleString(undefined, { minimumFractionDigits: 1 })}</td>
                    <td className="px-4 py-2 border-r border-slate-900 text-center font-black">
                      <span className={isWin ? 'text-brand-green' : 'text-brand-red'}>
                        {trade.rMultiple >= 0 ? '+' : ''}{trade.rMultiple.toFixed(2)}R
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-black">
                      <span className={isWin ? 'text-brand-green' : 'text-brand-red'}>
                        {isWin ? '+' : ''}${trade.pnl.toLocaleString(undefined, { minimumFractionDigits: 1 })}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Nota aclaratoria */}
      <div className="flex justify-between items-center mt-3 text-[8px] text-slate-600 font-mono">
        <span>R = Retorno / Riesgo ($300 por trade fijado en configuración)</span>
        {totalTrades > 15 && <span>* Mostrando últimas 15 ejecuciones</span>}
      </div>

    </div>
  );
};
