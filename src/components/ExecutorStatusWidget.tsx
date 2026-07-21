import React from 'react';
import type { ExecutorStatus, ModoSistema, ActiveTradeDetail } from '../types';
import { Cpu, Play, RefreshCw, Clock } from 'lucide-react';

interface ExecutorStatusWidgetProps {
  status: ExecutorStatus | null;
  isLoading: boolean;
  onModeChange: (newMode: ModoSistema) => void;
  isSaving: boolean;
}

export const ExecutorStatusWidget: React.FC<ExecutorStatusWidgetProps> = ({
  status,
  isLoading,
  onModeChange,
  isSaving
}) => {
  if (isLoading || !status) {
    return (
      <div className="glass-panel rounded-xl p-5 flex flex-col justify-center items-center h-[240px] border border-slate-800">
        <div className="w-6 h-6 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin mb-2" />
        <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Cargando Executor...</span>
      </div>
    );
  }

  const { modo, tradesHoy, circuitBreaker, ultimoTrade, ultimaSenal, tradesActivos, tradesActivosLista } = status;

  // Barra de progreso retro en caracteres block
  const maxTrades = circuitBreaker.disponibles || 3;
  const blocksFilled = Math.min(maxTrades, Math.max(0, tradesHoy));
  const blocksEmpty = Math.max(0, maxTrades - blocksFilled);
  const progressBarString = '▰'.repeat(blocksFilled) + '▱'.repeat(blocksEmpty);

  // Formateador de tiempo relativo simple
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

  const formatHoras = (horas: number) => {
    if (horas < 1) return `${Math.round(horas * 60)}m`;
    return `${horas.toFixed(1)}h`;
  };

  return (
    <div className={`glass-panel rounded-xl p-5 border transition-all duration-300 ${
      modo === 'REAL' 
        ? 'border-brand-red/35 bg-brand-red/[0.01] shadow-lg shadow-brand-red/5' 
        : modo === 'DEMO'
        ? 'border-amber-500/25 bg-amber-500/[0.01]'
        : 'border-slate-800'
    }`}>
      
      {/* Cabecera */}
      <div className="flex items-center justify-between border-b border-slate-900 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <Cpu className={`w-4 h-4 ${modo === 'REAL' ? 'text-brand-red animate-pulse' : modo === 'DEMO' ? 'text-amber-500 animate-pulse' : 'text-brand-cyan'}`} />
          <h4 className="text-sm font-bold text-white tracking-wide uppercase font-mono">
            Executor Status
          </h4>
        </div>
        
        {/* Guardando status */}
        {isSaving && (
          <span className="flex items-center gap-1 text-[9px] font-mono text-amber-500 animate-pulse">
            <RefreshCw className="w-2.5 h-2.5 animate-spin" />
            <span>SINCRONIZANDO MODO...</span>
          </span>
        )}
      </div>

      <div className="flex flex-col gap-2.5 font-mono text-xs">
        
        {/* Fila 1: Selector modo ancho + stats a la derecha */}
        <div className="flex items-center gap-3">
          {/* Selector de Modo — ocupa todo el espacio disponible */}
          <div className="flex-1">
            <div className="text-[8px] text-slate-500 uppercase tracking-wider mb-0.5">Modo Operativo</div>
            <select
              value={modo}
              onChange={(e) => onModeChange(e.target.value as ModoSistema)}
              disabled={isSaving}
              className={`w-full bg-slate-950 border text-[10px] rounded px-2 py-1.5 text-white font-bold cursor-pointer focus:outline-none focus:ring-1 focus:ring-brand-cyan ${
                modo === 'REAL'
                  ? 'border-brand-red/40 text-brand-red animate-pulse'
                  : modo === 'DEMO'
                  ? 'border-amber-500/40 text-amber-400'
                  : 'border-slate-800 text-slate-300'
              }`}
            >
              <option value="SIMULACION">● SIMULACIÓN</option>
              <option value="DEMO">● DEMO TRADING</option>
              <option value="REAL">🔥 REAL TIME</option>
            </select>
          </div>
          {/* Stats compactas: solo Activos + Disponibles */}
          <div className="flex gap-4 shrink-0 pt-4">
            <div className="text-center">
              <div className="text-[8px] text-slate-500 uppercase tracking-wider">Activos</div>
              <div className={`text-sm font-black ${tradesActivos > 0 ? 'text-amber-400' : 'text-slate-600'}`}>{tradesActivos}</div>
            </div>
            <div className="text-center">
              <div className="text-[8px] text-slate-500 uppercase tracking-wider">Disponibles</div>
              <div className="text-sm font-black text-brand-cyan">{circuitBreaker.disponibles}</div>
            </div>
          </div>
          {isSaving && <RefreshCw className="w-4 h-4 text-amber-500 animate-spin shrink-0 pt-4" />}
        </div>

        {/* Barra de progreso de trades hoy */}
        <div className="flex items-center gap-2 border-t border-slate-900/60 pt-2">
          <span className="text-[8px] text-slate-500 uppercase tracking-wider">Trades Hoy:</span>
          <span className="text-brand-cyan font-bold tracking-widest text-xs">{progressBarString}</span>
          <span className="text-[10px] text-slate-400 font-bold">{tradesHoy}/{maxTrades}</span>
          <span className={`ml-auto inline-flex items-center gap-1 text-[9px] font-bold px-2 py-0.5 rounded ${
            circuitBreaker.bloqueado 
              ? 'bg-brand-red/10 border border-brand-red/20 text-brand-red animate-pulse' 
              : 'bg-brand-green/10 border border-brand-green/20 text-brand-green'
          }`}>
            {circuitBreaker.bloqueado ? '🔒 BLOQUEADO' : '🔓 DESBLOQUEADO'}
          </span>
        </div>

        {/* Active Trades List (compacto) */}
        {tradesActivosLista.length > 0 && (
          <div className="border-t border-slate-900/60 pt-2">
            <div className="text-[8px] text-slate-500 uppercase tracking-wider mb-1 flex items-center gap-1">
              <Clock className="w-2.5 h-2.5" />
              TRADES ACTIVOS
            </div>
            <div className="flex flex-col gap-1 max-h-[120px] overflow-y-auto">
              {tradesActivosLista.map((trade: ActiveTradeDetail) => (
                <div key={trade.id} className="bg-slate-950/60 rounded-lg p-1.5 border border-slate-900 text-[9px]">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1">
                      <span className={`font-black ${trade.lado === 'LONG' ? 'text-brand-green' : 'text-brand-red'}`}>
                        #{trade.id} {trade.lado}
                      </span>
                      <span className="text-slate-500">| {formatHoras(trade.edad_horas)}</span>
                    </div>
                    <span className="text-white font-bold">${trade.precio_entrada.toLocaleString('en-US')}</span>
                  </div>
                  <div className="flex justify-between text-slate-500 mt-0.5">
                    <span>SL: <span className="text-brand-red/80">${trade.stop_loss.toLocaleString('en-US')}</span></span>
                    <span>TP: <span className="text-brand-green/80">{trade.take_profit > 0 ? `$${trade.take_profit.toLocaleString('en-US')}` : '---'}</span></span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Fila 3: Última señal + Última ejecución */}
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
