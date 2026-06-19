import React from 'react';
import type { SystemAlert } from '../types';
import { Terminal, ShieldAlert, Zap, Cpu, Ban, RefreshCw } from 'lucide-react';

interface AlertsLogProps {
  alerts: SystemAlert[];
  isLoading: boolean;
  isMocked: boolean;
  onRefresh: () => void;
}

export const AlertsLog: React.FC<AlertsLogProps> = ({ alerts, isLoading, isMocked, onRefresh }) => {
  const getBadgeColors = (tipo: string) => {
    const t = tipo.toUpperCase();
    if (t.includes('TRADE') || t === 'LIQUIDATION_SHORTS') {
      return 'text-brand-green bg-brand-green/10 border-brand-green/20';
    }
    if (t === 'BLOCK' || t.includes('BLOCK') || t === 'LIQUIDATION_LONGS') {
      return 'text-brand-red bg-brand-red/10 border-brand-red/20';
    }
    if (t.includes('SIGNAL') || t.includes('PRESSURE') || t === 'WARNING') {
      return 'text-amber-400 bg-amber-400/10 border-amber-400/20';
    }
    return 'text-slate-400 bg-slate-800/40 border-slate-700/30';
  };

  const getIcon = (tipo: string) => {
    const t = tipo.toUpperCase();
    if (t.includes('TRADE') || t === 'LIQUIDATION_SHORTS') {
      return <Zap className="w-3.5 h-3.5 text-brand-green" />;
    }
    if (t === 'BLOCK' || t.includes('BLOCK') || t === 'LIQUIDATION_LONGS') {
      return <Ban className="w-3.5 h-3.5 text-brand-red" />;
    }
    if (t.includes('SIGNAL') || t.includes('PRESSURE') || t === 'WARNING') {
      return <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />;
    }
    return <Cpu className="w-3.5 h-3.5 text-slate-500" />;
  };

  const formatTime = (timestampStr: string) => {
    try {
      const date = new Date(timestampStr);
      return date.toLocaleTimeString(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      });
    } catch {
      return timestampStr;
    }
  };

  return (
    <div className="glass-panel rounded-xl p-5 border border-slate-800 flex flex-col h-[680px]">
      
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-900 pb-3 mb-3 shrink-0">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-brand-cyan text-glow-cyan" />
          <h4 className="text-sm font-bold text-white tracking-wide uppercase font-mono">
            Bitácora de Decisiones (Hermes Brain)
          </h4>
        </div>
        
        <div className="flex items-center gap-2">
          <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${
            isMocked ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-brand-green/10 text-brand-green border border-brand-green/20'
          }`}>
            {isMocked ? 'LOGS MOCK' : 'LIVE LOGS'}
          </span>
          <button 
            onClick={onRefresh}
            className="p-1 rounded bg-slate-900 border border-slate-800 text-slate-500 hover:text-white transition-all cursor-pointer"
            title="Sincronizar bitácora"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Terminal Output */}
      <div className="flex-1 overflow-y-auto bg-slate-950/70 border border-slate-900/80 rounded-lg p-3 font-mono text-xs flex flex-col gap-2.5">
        {isLoading ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-600 gap-2">
            <div className="w-4 h-4 border-2 border-slate-600 border-t-transparent rounded-full animate-spin" />
            <span>Consultando bitácora...</span>
          </div>
        ) : alerts.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-slate-600">
            <span>Ningún log registrado en este ciclo.</span>
          </div>
        ) : (
          alerts.map((alert) => (
            <div key={alert.id} className="flex items-start gap-2.5 leading-relaxed border-b border-slate-900/40 pb-2 last:border-0 last:pb-0">
              {/* Timestamp */}
              <span className="text-[10px] text-slate-500 shrink-0 select-none mt-0.5">
                [{formatTime(alert.timestamp)}]
              </span>

              {/* Icon / Badge */}
              <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] font-black uppercase tracking-wider shrink-0 select-none ${getBadgeColors(alert.tipo)}`}>
                {getIcon(alert.tipo)}
                <span>{alert.tipo.replace('_', ' ')}</span>
              </div>

              {/* Message */}
              <span className="text-slate-300 font-medium break-words">
                {alert.mensaje}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
