import React from 'react';
import { Radio, Activity, Target, ShieldAlert } from 'lucide-react';
import type { RadarData } from '../types';

interface ConfirmationRadarProps {
  radarData: RadarData | null;
  isLoading: boolean;
}

export const ConfirmationRadar: React.FC<ConfirmationRadarProps> = ({
  radarData,
  isLoading
}) => {
  if (isLoading || !radarData) {
    return (
      <div className="glass-panel rounded-xl p-4 flex flex-col justify-center items-center h-full min-h-[160px] border border-slate-800">
        <div className="w-5 h-5 border-2 border-brand-cyan border-t-transparent rounded-full animate-spin mb-1" />
        <span className="text-[10px] text-slate-500 font-mono uppercase tracking-wider">Escaneando Radar...</span>
      </div>
    );
  }

  const {
    barridoLiquidez,
    barridoLiquidezUmbral,
    giroCvd,
    giroCvdUmbral,
    soporteObRatio,
    soporteObMinimo,
    estado,
    condicionesCumplidas,
    condicionesNecesarias
  } = radarData;

  const barridoDetectado = barridoLiquidez >= barridoLiquidezUmbral;
  const giroConfirmado = giroCvd >= giroCvdUmbral;
  const soporteConfirmado = soporteObRatio >= soporteObMinimo;

  const formatUsd = (val: number) => {
    if (Math.abs(val) >= 1000000) return `$${(val / 1000000).toFixed(2)}M`;
    if (Math.abs(val) >= 1000) return `$${(val / 1000).toFixed(0)}k`;
    return `$${val.toFixed(0)}`;
  };

  const isConfirmed = estado === 'CONFIRMADO';
  const isAttention = estado === 'ATENCION';

  return (
    <div className={`glass-panel rounded-xl p-4 border transition-all duration-300 h-full ${
      isConfirmed
        ? 'border-brand-green/35 bg-brand-green/[0.02] shadow-lg shadow-brand-green/5'
        : isAttention
        ? 'border-amber-500/25 bg-amber-500/[0.01]'
        : 'border-slate-800'
    }`}>
      {/* Cabecera */}
      <div className="flex items-center justify-between border-b border-slate-900 pb-2 mb-3">
        <div className="flex items-center gap-2">
          <Target className={`w-3.5 h-3.5 ${isConfirmed ? 'text-brand-green text-glow-green animate-spin' : isAttention ? 'text-amber-500 animate-pulse' : 'text-brand-cyan'}`} />
          <h4 className="text-xs font-bold text-white tracking-wide uppercase font-mono">
            Radar de Confirmación
          </h4>
        </div>
        <div className="flex items-center gap-1.5 font-mono text-[9px] font-bold text-slate-500">
          <Radio className={`w-3 h-3 ${isConfirmed ? 'text-brand-green animate-ping' : 'text-slate-600 animate-pulse'}`} />
          <span>{estado}</span>
        </div>
      </div>

      {/* Checklist Algorítmico */}
      <div className="flex flex-col gap-2 font-mono text-[10px] mb-3">
        
        {/* 1. Barrido de Liquidez */}
        <div className={`p-2.5 rounded-lg border transition-all duration-200 flex items-center justify-between ${
          barridoDetectado 
            ? 'bg-brand-green/5 border-brand-green/20 text-brand-green' 
            : 'bg-slate-950/40 border-slate-900 text-slate-400'
        }`}>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${barridoDetectado ? 'bg-brand-green text-glow-green animate-pulse' : 'bg-slate-700'}`} />
            <span>Barrido de Liquidez</span>
          </div>
          <span className="text-[10px] font-bold">
            {formatUsd(barridoLiquidez)} / {formatUsd(barridoLiquidezUmbral)}
          </span>
        </div>

        {/* 2. Giro de CVD */}
        <div className={`p-2.5 rounded-lg border transition-all duration-200 flex items-center justify-between ${
          giroConfirmado 
            ? 'bg-brand-green/5 border-brand-green/20 text-brand-green' 
            : 'bg-slate-950/40 border-slate-900 text-slate-400'
        }`}>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${giroConfirmado ? 'bg-brand-green text-glow-green animate-pulse' : 'bg-slate-700'}`} />
            <span>Giro de CVD Confirmado</span>
          </div>
          <span className="text-[10px] font-bold">
            {formatUsd(giroCvd)} / {formatUsd(giroCvdUmbral)}
          </span>
        </div>

        {/* 3. Soporte de Muros */}
        <div className={`p-2.5 rounded-lg border transition-all duration-200 flex items-center justify-between ${
          soporteConfirmado 
            ? 'bg-brand-green/5 border-brand-green/20 text-brand-green' 
            : 'bg-slate-950/40 border-slate-900 text-slate-400'
        }`}>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${soporteConfirmado ? 'bg-brand-green text-glow-green animate-pulse' : 'bg-slate-700'}`} />
            <span>Soporte de Muros (Ratio Bids/Asks)</span>
          </div>
          <span className="text-[10px] font-bold">
            {soporteObRatio.toFixed(2)}x / {soporteObMinimo.toFixed(2)}x
          </span>
        </div>

      </div>

      {/* Mensaje de Disparo / Alerta de Radar */}
      {isConfirmed ? (
        <div className="p-2 rounded-lg border border-brand-green/20 bg-brand-green/10 text-brand-green text-center font-mono font-black text-[9px] tracking-wider animate-pulse">
          <div className="flex items-center justify-center gap-1">
            <Activity className="w-3 h-3 text-brand-green animate-bounce" />
            <span>⚡ LISTO PARA DISPARO ⚡</span>
          </div>
        </div>
      ) : isAttention ? (
        <div className="p-2 rounded-lg border border-amber-500/20 bg-amber-500/5 text-amber-400 text-center font-mono font-bold text-[9px] tracking-wide flex items-center justify-center gap-1">
          <ShieldAlert className="w-3 h-3 text-amber-500 animate-pulse" />
          <span>ATENCIÓN: {condicionesCumplidas}/{condicionesNecesarias} condiciones</span>
        </div>
      ) : (
        <div className="p-2 rounded-lg border border-brand-red/20 bg-brand-red/5 text-brand-red text-center font-mono font-bold text-[9px] tracking-wide flex items-center justify-center gap-1">
          <ShieldAlert className="w-3 h-3 text-brand-red" />
          <span>BLOQUEADO ({condicionesCumplidas}/{condicionesNecesarias})</span>
        </div>
      )}
    </div>
  );
};
