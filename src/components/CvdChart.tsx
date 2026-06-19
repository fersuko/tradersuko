import React from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine
} from 'recharts';
import type { TelemetriaRegistro } from '../types';

interface CvdChartProps {
  data: TelemetriaRegistro[];
  isLoading: boolean;
  pocPrice?: number;
}

export const CvdChart: React.FC<CvdChartProps> = ({ data, isLoading, pocPrice }) => {
  // Formatear el timestamp para el eje X (solo hora y minutos/segundos)
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

  const formatCvd = (value: number) => {
    if (Math.abs(value) >= 1000000) {
      return `${(value / 1000000).toFixed(2)}M`;
    }
    return value.toLocaleString();
  };

  const formatPrice = (value: number) => {
    return `$${value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`;
  };

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const record = payload[0].payload as TelemetriaRegistro;
      return (
        <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/90 backdrop-blur-md shadow-2xl">
          <p className="text-xs font-semibold text-slate-500 mb-2">
            {new Date(record.timestamp).toLocaleString()}
          </p>
          <div className="flex flex-col gap-1.5 font-mono text-sm">
            <div className="flex items-center justify-between gap-8">
              <span className="text-slate-400 flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-brand-cyan" />
                Precio BTC:
              </span>
              <span className="text-white font-bold">
                {formatPrice(record.precio)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-8">
              <span className="text-slate-400 flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-purple-500" />
                CVD Binance:
              </span>
              <span className={`font-bold ${record.cvd_binance >= 0 ? 'text-brand-green' : 'text-brand-red'}`}>
                {record.cvd_binance.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </span>
            </div>
            <div className="flex items-center justify-between gap-8">
              <span className="text-slate-400 flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-400" />
                Delta CVD:
              </span>
              <span className="text-amber-400 font-bold">
                {/* Calculamos diferencia con el anterior si es posible en el tooltip, o mostramos el CVD total */}
                {formatCvd(record.cvd_binance)}
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
      <div className="h-[400px] w-full glass-panel rounded-xl flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-4 border-brand-cyan border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-slate-400 font-semibold tracking-wider animate-pulse">
            {isLoading ? 'CARGANDO TELEMETRÍA DE CVD...' : 'ESPERANDO REGISTROS DE TELEMETRÍA...'}
          </span>
        </div>
      </div>
    );
  }

  // Encontrar el precio mínimo y máximo para que la escala del eje Y sea óptima y no plana
  const prices = data.map(d => d.precio);
  const minPrice = Math.min(...prices) * 0.9998;
  const maxPrice = Math.max(...prices) * 1.0002;

  // Encontrar el CVD mínimo y máximo para escalado óptimo
  const cvds = data.map(d => d.cvd_binance);
  const minCvd = Math.min(...cvds) * 1.0001;
  const maxCvd = Math.max(...cvds) * 0.9999;

  return (
    <div className="glass-panel rounded-xl p-5 w-full transition-all duration-300">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <h3 className="text-base font-bold text-white tracking-wide">
            CVD Acumulado vs Precio BTC
          </h3>
          <p className="text-xs text-slate-500 mt-1">
            Visualiza absorciones institucionales y divergencias en tiempo real
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-1 bg-brand-cyan rounded-full" />
            <span className="text-slate-400">PRECIO</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-1 bg-purple-500 rounded-full" />
            <span className="text-slate-400">CVD ACC.</span>
          </div>
        </div>
      </div>

      <div className="h-[350px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 10, right: 5, left: -15, bottom: 0 }}>
            <defs>
              <linearGradient id="colorCvd" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#c084fc" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#c084fc" stopOpacity={0.0} />
              </linearGradient>
              <linearGradient id="colorPrecio" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#00e5ff" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#00e5ff" stopOpacity={0.0} />
              </linearGradient>
            </defs>
            
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" opacity={0.3} />
            
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatXAxis}
              stroke="#475569"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: '#334155', opacity: 0.5 }}
            />
            
            {/* Eje Y Izquierdo - Precio */}
            <YAxis
              yAxisId="left"
              domain={[minPrice, maxPrice]}
              tickFormatter={(v) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              stroke="#475569"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: '#334155', opacity: 0.5 }}
            />
            
            {/* Eje Y Derecho - CVD */}
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[minCvd, maxCvd]}
              tickFormatter={formatCvd}
              stroke="#475569"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: '#334155', opacity: 0.5 }}
            />
            
            <Tooltip content={<CustomTooltip />} />
            
            {/* Área del CVD */}
            <Area
              yAxisId="right"
              type="monotone"
              dataKey="cvd_binance"
              stroke="#c084fc"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#colorCvd)"
              name="CVD Binance"
            />

            {/* Área del Precio */}
            <Area
              yAxisId="left"
              type="monotone"
              dataKey="precio"
              stroke="#00e5ff"
              strokeWidth={1.5}
              fillOpacity={1}
              fill="url(#colorPrecio)"
              name="Precio BTC"
            />

            {/* Línea de Soporte del POC Institucional */}
            {pocPrice && pocPrice > 0 && (
              <ReferenceLine
                yAxisId="left"
                y={pocPrice}
                stroke="#e2e8f0"
                strokeWidth={1}
                strokeDasharray="4 4"
                label={{
                  value: `POC INSTITUCIONAL: $${pocPrice.toLocaleString()}`,
                  fill: '#f59e0b',
                  fontSize: 9,
                  fontWeight: 'bold',
                  position: 'insideBottomLeft',
                  offset: 10,
                  className: 'font-mono'
                }}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
