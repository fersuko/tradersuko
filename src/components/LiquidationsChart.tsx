import React from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid
} from 'recharts';
import type { TelemetriaRegistro } from '../types';

interface LiquidationsChartProps {
  data: TelemetriaRegistro[];
  isLoading: boolean;
  totalLongsLiq: number;
  totalShortsLiq: number;
}

export const LiquidationsChart: React.FC<LiquidationsChartProps> = ({ 
  data, 
  isLoading,
  totalLongsLiq,
  totalShortsLiq
}) => {
  // Formatear el timestamp para el eje X
  const formatXAxis = (timestampStr: string) => {
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

  const formatVolume = (value: number) => {
    if (value === 0) return '0';
    if (value >= 1000000) {
      return `$${(value / 1000000).toFixed(1)}M`;
    }
    if (value >= 1000) {
      return `$${(value / 1000).toFixed(0)}k`;
    }
    return `$${value}`;
  };

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const record = payload[0].payload as TelemetriaRegistro;
      const totalLiq = record.liquidaciones_longs + record.liquidaciones_shorts;
      
      return (
        <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/90 backdrop-blur-md shadow-2xl">
          <p className="text-xs font-semibold text-slate-500 mb-2">
            {new Date(record.timestamp).toLocaleString()}
          </p>
          <div className="flex flex-col gap-1.5 font-mono text-sm">
            <div className="flex items-center justify-between gap-8 text-brand-red">
              <span className="flex items-center gap-1.5 font-sans text-slate-400">
                <span className="w-2.5 h-2.5 rounded-sm bg-brand-red" />
                Liquidaciones Longs (Ventas):
              </span>
              <span className="font-bold">
                ${record.liquidaciones_longs.toLocaleString()}
              </span>
            </div>
            <div className="flex items-center justify-between gap-8 text-brand-green">
              <span className="flex items-center gap-1.5 font-sans text-slate-400">
                <span className="w-2.5 h-2.5 rounded-sm bg-brand-green" />
                Liquidaciones Shorts (Compras):
              </span>
              <span className="font-bold">
                ${record.liquidaciones_shorts.toLocaleString()}
              </span>
            </div>
            <div className="border-t border-slate-800 my-1 pt-1 flex items-center justify-between gap-8 text-white">
              <span className="font-sans text-slate-300">Total Liquidado:</span>
              <span className="font-bold">
                ${totalLiq.toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      );
    }
    return null;
  };

  if (isLoading || data.length === 0) {
    return (
      <div className="h-[250px] w-full glass-panel rounded-xl flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-3 border-brand-red border-t-transparent rounded-full animate-spin" />
          <span className="text-xs text-slate-400 font-semibold tracking-wider animate-pulse">
            {isLoading ? 'CARGANDO LIQUIDACIONES...' : 'ESPERANDO REGISTROS DE LIQUIDACIONES...'}
          </span>
        </div>
      </div>
    );
  }

  // Filtrar si hay liquidaciones en el set de datos para poner contexto,
  const hasLiquidations = data.some(d => d.liquidaciones_longs > 0 || d.liquidaciones_shorts > 0);

  return (
    <div className="glass-panel rounded-xl p-5 w-full transition-all duration-300">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div>
          <h3 className="text-base font-bold text-white tracking-wide flex items-center gap-2">
            Liquidaciones Forzadas (Cascadas)
            {hasLiquidations && (
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand-red opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-brand-red"></span>
              </span>
            )}
          </h3>
          <p className="text-xs text-slate-500 mt-1">
            Volumen de cierres forzados por el motor de liquidación de Binance
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-brand-red" />
            <span className="text-slate-400">LONGS (VENTA)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-brand-green" />
            <span className="text-slate-400">SHORTS (COMPRA)</span>
          </div>
        </div>
      </div>

      <div className="h-[180px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 5, right: 5, left: -20, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.2} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatXAxis}
              stroke="#475569"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: '#334155', opacity: 0.5 }}
            />
            <YAxis
              tickFormatter={formatVolume}
              stroke="#475569"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: '#334155', opacity: 0.5 }}
            />
            <Tooltip content={<CustomTooltip />} />
            
            {/* Barras apiladas */}
            <Bar dataKey="liquidaciones_longs" stackId="a" fill="#ff5252" radius={[0, 0, 0, 0]} />
            <Bar dataKey="liquidaciones_shorts" stackId="a" fill="#00e676" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Resumen Acumulado de Liquidaciones al pie */}
      {!isLoading && (
        <div className="mt-4 pt-3 border-t border-slate-900/60 flex flex-wrap items-center justify-between gap-3 font-mono text-[10px]">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="text-slate-500 font-bold">HISTÓRICO VISIBLE:</span>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-red" />
              <span className="text-slate-400">LONGS LIQ:</span>
              <span className="text-brand-red font-bold">${totalLongsLiq.toLocaleString()}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-green" />
              <span className="text-slate-400">SHORTS LIQ:</span>
              <span className="text-brand-green font-bold">${totalShortsLiq.toLocaleString()}</span>
            </div>
          </div>
          <span className="text-[9px] text-slate-500">
            💡 Absorción reactiva de stop-loss minorista
          </span>
        </div>
      )}
    </div>
  );
};
