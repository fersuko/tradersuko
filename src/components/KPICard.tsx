import { ArrowUpRight, ArrowDownRight, Activity, DollarSign, TrendingUp, Compass, Zap } from 'lucide-react';

interface KPICardProps {
  title: string;
  value: string | number;
  subValue?: string | number;
  change?: number; // Porcentaje o cambio nominal
  changeType?: 'up' | 'down' | 'neutral';
  icon: 'price' | 'cvd' | 'pressure' | 'speed';
  isLoading?: boolean;
}

export const KPICard: React.FC<KPICardProps> = ({
  title,
  value,
  subValue,
  change,
  changeType = 'neutral',
  icon,
  isLoading = false
}) => {
  const getIcon = () => {
    switch (icon) {
      case 'price':
        return <DollarSign className="w-5 h-5 text-brand-cyan text-glow-cyan" />;
      case 'cvd':
        return <TrendingUp className="w-5 h-5 text-purple-400" />;
      case 'pressure':
        return <Compass className="w-5 h-5 text-brand-green text-glow-green" />;
      case 'speed':
        return <Zap className="w-5 h-5 text-amber-500 animate-pulse" />;
      default:
        return <Activity className="w-5 h-5 text-slate-400" />;
    }
  };

  const getBorderColorClass = () => {
    if (icon === 'price') return 'glass-panel-cyan';
    return 'glass-panel';
  };

  return (
    <div className={`p-5 rounded-xl transition-all duration-300 ${getBorderColorClass()}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold tracking-wider text-slate-400 uppercase">
          {title}
        </span>
        <div className="p-2 rounded-lg bg-slate-900/60 border border-slate-800">
          {isLoading ? (
            <div className="w-5 h-5 border-2 border-slate-500 border-t-transparent rounded-full animate-spin" />
          ) : (
            getIcon()
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        {isLoading ? (
          <div className="h-9 w-36 bg-slate-800/50 animate-pulse rounded" />
        ) : (
          <div className="text-2xl font-bold font-mono tracking-tight text-white">
            {value}
          </div>
        )}

        <div className="flex items-center justify-between mt-1 text-xs">
          {isLoading ? (
            <div className="h-4 w-20 bg-slate-800/40 animate-pulse rounded" />
          ) : (
            <>
              {/* Subvalor descriptivo */}
              <span className="text-slate-500 font-medium">{subValue}</span>

              {/* Indicador de cambio */}
              {change !== undefined && (
                <span
                  className={`flex items-center gap-0.5 font-bold font-mono px-1.5 py-0.5 rounded ${
                    changeType === 'up'
                      ? 'text-brand-green bg-brand-green/10'
                      : changeType === 'down'
                      ? 'text-brand-red bg-brand-red/10'
                      : 'text-slate-400 bg-slate-800'
                  }`}
                >
                  {changeType === 'up' ? (
                    <ArrowUpRight className="w-3.5 h-3.5" />
                  ) : changeType === 'down' ? (
                    <ArrowDownRight className="w-3.5 h-3.5" />
                  ) : null}
                  {changeType === 'up' && '+'}
                  {change > 1000 || change < -1000 
                    ? change.toLocaleString(undefined, { maximumFractionDigits: 0 }) 
                    : change.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  {icon === 'pressure' ? '%' : icon === 'speed' ? ' tps' : ''}
                </span>
              )}
            </>
          )}
        </div>
      </div>

      {/* Gráfico o visualizador simple para Presión de Compra */}
      {icon === 'pressure' && !isLoading && typeof value === 'string' && (
        <div className="mt-4">
          <div className="flex justify-between text-[10px] text-slate-500 mb-1 font-semibold">
            <span>SELL PRES.</span>
            <span>BUY PRES.</span>
          </div>
          <div className="h-1.5 w-full bg-slate-900 rounded-full overflow-hidden flex border border-slate-850">
            <div
              style={{ width: `${100 - parseFloat(value)}%` }}
              className="bg-brand-red h-full transition-all duration-500 ease-out"
            />
            <div
              style={{ width: `${parseFloat(value)}%` }}
              className="bg-brand-green h-full transition-all duration-500 ease-out"
            />
          </div>
        </div>
      )}

      {/* Visualizador para Velocidad de Cinta (TPS) */}
      {icon === 'speed' && !isLoading && (
        <div className="mt-4">
          <div className="flex justify-between text-[10px] text-slate-500 mb-1 font-semibold">
            <span>ACTIVIDAD HFT</span>
            <span>INTENSIDAD TPS</span>
          </div>
          <div className="h-1.5 w-full bg-slate-900 rounded-full overflow-hidden border border-slate-850">
            <div
              style={{ width: `${Math.min(100, (parseFloat(String(value)) / 250) * 100)}%` }}
              className={`h-full transition-all duration-500 ease-out ${
                parseFloat(String(value)) > 100 
                  ? 'bg-brand-red animate-pulse' 
                  : parseFloat(String(value)) > 45 
                  ? 'bg-amber-500' 
                  : 'bg-brand-cyan'
              }`}
            />
          </div>
        </div>
      )}
    </div>
  );
};
