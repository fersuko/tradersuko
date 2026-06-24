import React from 'react';
import type { ExecutorStatus, ModoSistema, ActiveTradeDetail } from '../types';
import { Cpu, ShieldCheck, Key, Play, AlertTriangle, RefreshCw, Clock, TrendingUp, TrendingDown } from 'lucide-react';

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

  const { modo, keys, tradesHoy, circuitBreaker, ultimoTrade, ultimaSenal, tradesActivos, tradesActivosLista, pnlDia } = status;

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

      <div className="flex flex-col gap-3 font-mono text-xs">
        
        {/* 1. Selector de Modo */}
        <div className="flex items-center justify-between">
          <span className="text-slate-400">Modo Operativo:</span>
          <div className="relative">
            <select
              value={modo}
              onChange={(e) => onModeChange(e.target.value as ModoSistema)}
              disabled={isSaving}
              className={`bg-slate-950 border text-[11px] rounded px-2.5 py-1 text-white font-bold cursor-pointer focus:outline-none focus:ring-1 focus:ring-brand-cyan transition-colors ${
                modo === 'REAL'
                  ? 'border-brand-red/40 text-brand-red text-glow-red'
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
        </div>

        {/* 2. API Keys Configured */}
        <div className="flex items-center justify-between border-t border-slate-900/60 pt-2.5">
          <span className="text-slate-400 flex items-center gap-1.5">
            <Key className="w-3.5 h-3.5 text-slate-500" /> API Keys:
          </span>
          <div className="flex gap-3 text-[10px] font-bold">
            <span className="flex items-center gap-1">
              REAL {keys.real ? <span className="text-brand-green">✅</span> : <span className="text-brand-red">❌</span>}
            </span>
            <span className="flex items-center gap-1 border-l border-slate-800 pl-3">
              DEMO {keys.demo ? <span className="text-brand-green">✅</span> : <span className="text-brand-red">❌</span>}
            </span>
          </div>
        </div>

        {/* 3. SUMMARY BAR: Trades Activos + Trades Hoy + P&L Día */}
        <div className="grid grid-cols-3 gap-2 border-t border-slate-900/60 pt-2.5">
          {/* Trades Activos */}
          <div className="bg-slate-950/50 rounded-lg p-2 text-center border border-slate-900">
            <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">Activos</div>
            <div className={`text-sm font-black ${tradesActivos > 0 ? 'text-amber-400' : 'text-slate-600'}`}>
              {tradesActivos}
            </div>
          </div>
          {/* Trades Hoy */}
          <div className="bg-slate-950/50 rounded-lg p-2 text-center border border-slate-900">
            <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">Hoy</div>
            <div className="text-sm font-black text-brand-cyan">{tradesHoy}/{maxTrades}</div>
          </div>
          {/* P&L Día */}
          <div className="bg-slate-950/50 rounded-lg p-2 text-center border border-slate-900">
            <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">P&L Día</div>
            <div className={`text-sm font-black flex items-center justify-center gap-1 ${
              pnlDia > 0 ? 'text-brand-green' : pnlDia < 0 ? 'text-brand-red' : 'text-slate-600'
            }`}>
              {pnlDia > 0 ? <TrendingUp className="w-3 h-3" /> : pnlDia < 0 ? <TrendingDown className="w-3 h-3" /> : null}
              ${pnlDia.toFixed(2)}
            </div>
          </div>
        </div>

        {/* 4. Active Trades List (if any) */}
        {tradesActivosLista.length > 0 && (
          <div className="border-t border-slate-900/60 pt-2.5">
            <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              TRADES ACTIVOS
            </div>
            <div className="flex flex-col gap-1.5 max-h-[180px] overflow-y-auto">
              {tradesActivosLista.map((trade: ActiveTradeDetail) => (
                <div key={trade.id} className="bg-slate-950/60 rounded-lg p-2 border border-slate-900 text-[10px]">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5">
                      <span className={`font-black ${trade.lado === 'LONG' ? 'text-brand-green' : 'text-brand-red'}`}>
                        #{trade.id} {trade.lado}
                      </span>
                      <span className="text-slate-500">|</span>
                      <span className="text-slate-400">{formatHoras(trade.edad_horas)}</span>
                    </div>
                    <span className="text-white font-bold">${trade.precio_entrada.toLocaleString('en-US')}</span>
                  </div>
                  <div className="flex justify-between text-slate-500">
                    <span>SL: <span className="text-brand-red/80">${trade.stop_loss.toLocaleString('en-US')}</span></span>
                    <span>TP: <span className="text-brand-green/80">{trade.take_profit > 0 ? `$${trade.take_profit.toLocaleString('en-US')}` : '---'}</span></span>
                    <span>{trade.cantidad_btc.toFixed(4)} BTC</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 5. Trades Ejecutados hoy */}
        <div className="flex items-center justify-between border-t border-slate-900/60 pt-2.5">
          <span className="text-slate-400">Trades Hoy:</span>
          <div className="flex items-center gap-2">
            <span className="text-brand-cyan font-bold tracking-widest text-sm">
              {progressBarString}
            </span>
            <span className="text-[10px] text-slate-500 font-bold">
              {tradesHoy}/{maxTrades}
            </span>
          </div>
        </div>

        {/* 6. Circuit Breaker */}
        <div className="flex items-center justify-between border-t border-slate-900/60 pt-2.5">
          <span className="text-slate-400">Circuit Breaker:</span>
          <span className={`flex items-center gap-1 font-bold text-[10px] px-2 py-0.5 rounded ${
            circuitBreaker.bloqueado 
              ? 'bg-brand-red/10 border border-brand-red/20 text-brand-red text-glow-red animate-pulse' 
              : 'bg-brand-green/10 border border-brand-green/20 text-brand-green text-glow-green'
          }`}>
            {circuitBreaker.bloqueado ? (
              <>
                <AlertTriangle className="w-3 h-3 text-brand-red" />
                <span>BLOQUEADO</span>
              </>
            ) : (
              <>
                <ShieldCheck className="w-3 h-3 text-brand-green" />
                <span>DESBLOQUEADO</span>
              </>
            )}
          </span>
        </div>

        {/* 7. Última señal */}
        <div className="flex flex-col gap-1 border-t border-slate-900/60 pt-2.5">
          <div className="flex justify-between text-slate-500 text-[10px]">
            <span>ÚLTIMA SEÑAL RECIBIDA</span>
            {ultimaSenal && <span>{formatTimeAgo(ultimaSenal.timestamp)}</span>}
          </div>
          <div className="text-[11px] font-bold text-slate-300 break-all bg-slate-950/40 p-1.5 rounded border border-slate-900">
            {ultimaSenal ? (
              <div className="flex items-center gap-1">
                <Play className="w-3 h-3 text-brand-cyan" />
                <span className="text-brand-cyan font-extrabold">{ultimaSenal.tipo}</span>
                {ultimaSenal.mensaje && <span className="text-slate-400 font-medium truncate ml-1">- {ultimaSenal.mensaje}</span>}
              </div>
            ) : (
              <span className="text-slate-600 italic">Ninguna señal registrada</span>
            )}
          </div>
        </div>

        {/* 8. Último trade ejecutado */}
        <div className="flex flex-col gap-1 border-t border-slate-900/60 pt-2.5">
          <div className="flex justify-between text-slate-500 text-[10px]">
            <span>ÚLTIMA EJECUCIÓN DIRECTA</span>
            {ultimoTrade && <span>{formatTimeAgo(ultimoTrade.timestamp)}</span>}
          </div>
          <div className="text-[11px] font-bold text-slate-300 break-all bg-slate-950/40 p-1.5 rounded border border-slate-900">
            {ultimoTrade ? (
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between">
                  <span className={(ultimoTrade.tipo || '').includes('BUY') || (ultimoTrade.tipo || '').includes('LONG') ? 'text-brand-green' : 'text-brand-red'}>
                    {ultimoTrade.tipo || 'DESCONOCIDO'}
                  </span>
                  <span className="text-white font-bold">
                    {ultimoTrade.precio && !isNaN(ultimoTrade.precio) ? `$${ultimoTrade.precio.toLocaleString('en-US')}` : '---'}
                  </span>
                </div>
                {ultimoTrade.mensaje && <span className="text-[10px] text-slate-500 font-normal">{ultimoTrade.mensaje}</span>}
              </div>
            ) : (
              <span className="text-slate-600 italic">Sin ejecuciones aún</span>
            )}
          </div>
        </div>

      </div>
    </div>
  );
};
