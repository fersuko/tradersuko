import React from 'react';
import type { SystemConfig, ModoSistema } from '../types';
import { Sliders, ShieldAlert, Cpu, RefreshCw, Check, AlertCircle } from 'lucide-react';

interface ConfigCardProps {
  config: SystemConfig;
  onConfigChange: (newConfig: SystemConfig) => void;
  isSaving: boolean;
  saveStatus: 'idle' | 'success' | 'error';
  isApiMocked: boolean;
}

export const ConfigCard: React.FC<ConfigCardProps> = ({
  config,
  onConfigChange,
  isSaving,
  saveStatus,
  isApiMocked
}) => {

  const handleSliderChange = (key: keyof Omit<SystemConfig, 'modoSistema'>, value: number) => {
    onConfigChange({
      ...config,
      [key]: value
    });
  };

  const handleModoChange = (mode: ModoSistema) => {
    onConfigChange({
      ...config,
      modoSistema: mode
    });
  };

  const formatUsd = (val: number) => {
    if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`;
    return `$${(val / 1000).toFixed(0)}k`;
  };

  return (
    <div className="glass-panel rounded-xl p-5 flex flex-col justify-between h-full border border-slate-800 transition-all duration-300">
      <div>
        {/* Cabecera del Panel */}
        <div className="flex items-center justify-between mb-4 border-b border-slate-900 pb-3">
          <div className="flex items-center gap-2">
            <Sliders className="w-4 h-4 text-brand-cyan" />
            <h4 className="text-sm font-bold text-white tracking-wide uppercase font-mono">
              Calibración de Sensibilidad
            </h4>
          </div>
          
          <div className="flex items-center gap-2">
            {/* Status de Sincronización en tiempo real (Autoguardado debounced) */}
            {isSaving ? (
              <span className="flex items-center gap-1 text-[9px] font-mono text-amber-500 animate-pulse">
                <RefreshCw className="w-2.5 h-2.5 animate-spin" />
                <span>GUARDANDO...</span>
              </span>
            ) : saveStatus === 'success' ? (
              <span className="flex items-center gap-1 text-[9px] font-mono text-brand-green font-bold">
                <Check className="w-3 h-3 text-glow-green" />
                <span>SINCRONIZADO</span>
              </span>
            ) : saveStatus === 'error' ? (
              <span className="flex items-center gap-1 text-[9px] font-mono text-brand-red font-bold animate-bounce">
                <AlertCircle className="w-3 h-3 text-glow-red" />
                <span>ERR CONEXIÓN</span>
              </span>
            ) : (
              <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${
                isApiMocked ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-brand-green/10 text-brand-green border border-brand-green/20'
              }`}>
                {isApiMocked ? 'EMULADO LOCAL' : 'VPS CONECTADO'}
              </span>
            )}
          </div>
        </div>

        {/* Sliders y Controles */}
        <div className="flex flex-col gap-4">
          
          {/* 1. Umbral de Liquidaciones */}
          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between items-center text-xs font-mono">
              <span className="text-slate-400">Umbral de Liquidación Mín.</span>
              <span className="text-brand-cyan font-bold">{formatUsd(config.umbralLiquidaciones)} USD</span>
            </div>
            <input
              type="range"
              min={10000}
              max={1000000}
              step={10000}
              value={config.umbralLiquidaciones}
              onChange={(e) => handleSliderChange('umbralLiquidaciones', Number(e.target.value))}
              className="w-full h-1 bg-slate-950 rounded-lg appearance-none cursor-pointer accent-brand-cyan"
            />
          </div>

          {/* 2. Delta CVD */}
          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between items-center text-xs font-mono">
              <span className="text-slate-400">Delta CVD Requerido</span>
              <span className="text-purple-400 font-bold">{formatUsd(config.deltaCvd)} USD</span>
            </div>
            <input
              type="range"
              min={100000}
              max={2000000}
              step={50000}
              value={config.deltaCvd}
              onChange={(e) => handleSliderChange('deltaCvd', Number(e.target.value))}
              className="w-full h-1 bg-slate-950 rounded-lg appearance-none cursor-pointer accent-purple-400"
            />
          </div>

          {/* 3. Apalancamiento / Leverage */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between items-center text-xs font-mono">
                <span className="text-slate-400">Apalancamiento</span>
                <span className="text-white font-bold">{config.leverage}x</span>
              </div>
              <input
                type="range"
                min={1}
                max={25}
                step={1}
                value={config.leverage}
                onChange={(e) => handleSliderChange('leverage', Number(e.target.value))}
                className="w-full h-1 bg-slate-950 rounded-lg appearance-none cursor-pointer accent-slate-300"
              />
            </div>

            {/* 4. Margen de Operación */}
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between items-center text-xs font-mono">
                <span className="text-slate-400">Margen Trigger</span>
                <span className="text-white font-bold">{config.margenOperacion.toFixed(1)}%</span>
              </div>
              <input
                type="range"
                min={0.5}
                max={10.0}
                step={0.1}
                value={config.margenOperacion}
                onChange={(e) => handleSliderChange('margenOperacion', Number(e.target.value))}
                className="w-full h-1 bg-slate-950 rounded-lg appearance-none cursor-pointer accent-slate-300"
              />
            </div>
          </div>

          {/* 5. Selector de Modo Sistema */}
          <div className="mt-2 p-3 rounded-lg bg-slate-950/50 border border-slate-900 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Cpu className={`w-4 h-4 ${
                config.modoSistema === 'REAL' 
                  ? 'text-brand-red animate-pulse' 
                  : config.modoSistema === 'DEMO'
                  ? 'text-amber-500 animate-pulse' 
                  : 'text-slate-500'
              }`} />
              <div className="flex flex-col">
                <span className="text-xs font-bold text-white font-mono">MODO OPERATIVO</span>
                <span className="text-[9px] text-slate-500 font-mono">Ejecución del Brain</span>
              </div>
            </div>

            <div className="flex bg-slate-950 p-0.5 rounded border border-slate-900 font-mono text-[9px] font-bold">
              {(['SIMULACION', 'DEMO', 'REAL'] as ModoSistema[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => handleModoChange(mode)}
                  className={`px-2 py-1 rounded transition-colors duration-200 cursor-pointer ${
                    config.modoSistema === mode
                      ? mode === 'REAL'
                        ? 'bg-brand-red text-white'
                        : mode === 'DEMO'
                        ? 'bg-amber-500 text-black'
                        : 'bg-brand-cyan text-black'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {mode === 'SIMULACION' ? 'SIM' : mode === 'DEMO' ? 'DEMO' : 'LIVE'}
                </button>
              ))}
            </div>
          </div>

        </div>
      </div>

      {/* Indicador de Advertencia de capital en tiempo real */}
      <div className="mt-4 pt-3 border-t border-slate-900 flex flex-col gap-2">
        {config.modoSistema === 'REAL' ? (
          <div className="flex items-center gap-1.5 text-[10px] text-brand-red font-mono font-bold bg-brand-red/5 p-2 rounded border border-brand-red/10 animate-pulse">
            <ShieldAlert className="w-3.5 h-3.5 shrink-0 text-glow-red" />
            <span>ADVERTENCIA: EJECUCIÓN DIRECTA EN LIVE API</span>
          </div>
        ) : config.modoSistema === 'DEMO' ? (
          <div className="flex items-center gap-1.5 text-[10px] text-amber-500 font-mono font-bold bg-amber-500/5 p-2 rounded border border-amber-500/10 animate-pulse">
            <ShieldAlert className="w-3.5 h-3.5 shrink-0 text-amber-500" />
            <span>EJECUCIÓN DEMO: OPERACIONES DE PRUEBA EN VIVO</span>
          </div>
        ) : (
          <div className="text-[9px] text-slate-500 font-mono italic text-center">
            Cambios aplicados de forma automática vía debounce en Tailscale
          </div>
        )}
      </div>
    </div>
  );
};
