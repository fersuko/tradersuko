import React, { useState, useEffect, useCallback } from 'react';
import { getTelemetria, API_BASE_URL, getPoc, getAlertas, getConfig, saveConfig, getRadar, getExecutorStatus, getPosition, getTrades } from '../services/api';
import type { TelemetriaRegistro, PocData, SystemAlert, SystemConfig, RadarData, ExecutorStatus, PositionData, TradeData } from '../types';
import { TradingPanel } from './TradingPanel';
import { RMultiplesHistory } from './RMultiplesHistory';
import { KPICard } from './KPICard';
import { CvdChart } from './CvdChart';
import { LiquidationsChart } from './LiquidationsChart';
import { ConfigCard } from './ConfigCard';
import { OrderBookDepthWidget } from './OrderBookDepthWidget';
import { AlertsLog } from './AlertsLog';
import { ConfirmationRadar } from './ConfirmationRadar';
import { MarketClocks } from './MarketClocks';
import { TradesChart } from './TradesChart';
import { 
  Wifi, 
  WifiOff, 
  RefreshCw, 
  Clock, 
  Layers, 
  ShieldAlert,
  Server
} from 'lucide-react';

export const Dashboard: React.FC = () => {
  const [data, setData] = useState<TelemetriaRegistro[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isMocked, setIsMocked] = useState<boolean>(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [limit, setLimit] = useState<number>(100);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [pocData, setPocData] = useState<PocData | null>(null);
  const [alerts, setAlerts] = useState<SystemAlert[]>([]);
  const [isAlertsMocked, setIsAlertsMocked] = useState<boolean>(false);
  const [radarData, setRadarData] = useState<RadarData | null>(null);
  const [executorStatus, setExecutorStatus] = useState<ExecutorStatus | null>(null);
  const [position, setPosition] = useState<PositionData | null>(null);
  const [trades, setTrades] = useState<TradeData[]>([]);
  const [isTradesLoading, setIsTradesLoading] = useState<boolean>(true);

  // Estados de configuración de calibración
  const [config, setConfig] = useState<SystemConfig>({
    umbralLiquidaciones: 200000,
    deltaCvd: 500000,
    leverage: 10,
    margenOperacion: 2.0,
    modoSistema: 'SIMULACION'
  });
  const [isConfigMocked, setIsConfigMocked] = useState<boolean>(false);
  const [configLoaded, setConfigLoaded] = useState<boolean>(false);
  const [isSavingConfig, setIsSavingConfig] = useState<boolean>(false);
  const [configSaveStatus, setConfigSaveStatus] = useState<'idle' | 'success' | 'error'>('idle');

  // Carga inicial de la configuración
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const result = await getConfig();
        setConfig(result.config);
        setIsConfigMocked(result.isMocked);
        setConfigLoaded(true);
      } catch (error) {
        console.error('Error al cargar configuración en Dashboard:', error);
      }
    };
    loadConfig();
  }, []);

  // Debouncing para autoguardar la configuración en la DB del VPS
  useEffect(() => {
    if (!configLoaded) return;

    setIsSavingConfig(true);
    setConfigSaveStatus('idle');

    const timer = setTimeout(async () => {
      try {
        const result = await saveConfig(config);
        if (result.success) {
          setConfigSaveStatus('success');
          setIsConfigMocked(result.isMocked);
          setTimeout(() => setConfigSaveStatus('idle'), 2000);
        } else {
          setConfigSaveStatus('error');
        }
      } catch (error) {
        console.error('Error al guardar configuración debounced:', error);
        setConfigSaveStatus('error');
      } finally {
        setIsSavingConfig(false);
      }
    }, 600); // 600ms de debounce

    return () => clearTimeout(timer);
  }, [config, configLoaded]);

  // Carga de datos optimizada
  const fetchData = useCallback(async (isManual = false) => {
    if (isManual) setIsRefreshing(true);
    try {
      const [result, pocResult, alertsResult, radarResult, executorResult, positionResult, tradesResult] = await Promise.all([
        getTelemetria(limit),
        getPoc(),
        getAlertas(25),
        getRadar(),
        getExecutorStatus(),
        getPosition(),
        getTrades()
      ]);
      
      // Ordenar datos cronológicamente (antiguo a nuevo) para que los gráficos rendericen correctamente de izquierda a derecha
      const sortedData = [...result.response.data].sort(
        (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
      );

      setData(sortedData);
      setPocData(pocResult.poc);
      setAlerts(alertsResult.alertas);
      setIsAlertsMocked(alertsResult.isMocked);
      setRadarData(radarResult.radar);
      setExecutorStatus(executorResult.status);
      setPosition(positionResult.position);
      setTrades(tradesResult.trades);
      setIsTradesLoading(false);
      setIsMocked(
        result.isMocked || 
        pocResult.isMocked || 
        alertsResult.isMocked || 
        radarResult.isMocked || 
        executorResult.isMocked || 
        positionResult.isMocked || 
        tradesResult.isMocked
      );
      setLastUpdate(new Date());
    } catch (err) {
      console.error('Error fetching telemetría en Dashboard:', err);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [limit]);

  // Efecto para el polling de 5 segundos
  useEffect(() => {
    fetchData(); // Carga inicial

    const interval = setInterval(() => {
      fetchData();
    }, 5000); // Cada 5 segundos

    return () => clearInterval(interval);
  }, [fetchData]);

  // Cálculos de KPIs basados en la data actual
  const getKpiMetrics = () => {
    if (data.length === 0) {
      return {
        ultimoPrecio: 0,
        precioChange: 0,
        precioChangeType: 'neutral' as const,
        precioSubtext: '$0.00',
        ultimoCvd: 0,
        cvdDelta: 0,
        cvdChangeType: 'neutral' as const,
        cvdSubtext: '0.00',
        ultimaPresion: '50.00',
        presionSubtext: 'Neutral',
        totalLongsLiq: 0,
        totalShortsLiq: 0,
        velocidadTps: 0,
        velocidadSubtext: 'Bajo'
      };
    }

    const latest = data[data.length - 1];
    const previous = data[Math.max(0, data.length - 2)];
    
    // 1. Precio
    const ultimoPrecio = latest.precio;
    const precioChange = ultimoPrecio - previous.precio;
    const precioChangePct = previous.precio !== 0 ? (precioChange / previous.precio) * 100 : 0;
    const precioChangeType = precioChangePct > 0 ? 'up' as const : precioChangePct < 0 ? 'down' as const : 'neutral' as const;
    const precioSubtext = `Ref: ${previous.precio.toLocaleString('en-US')}`;

    // 2. CVD
    const ultimoCvd = latest.cvd_binance;
    const cvdDelta = ultimoCvd - previous.cvd_binance;
    const cvdChangeType = cvdDelta > 0 ? 'up' as const : cvdDelta < 0 ? 'down' as const : 'neutral' as const;
    
    const formatMil = (val: number) => {
      const absVal = Math.abs(val);
      if (absVal >= 1000000) return `${(val / 1000000).toFixed(2)}M`;
      if (absVal >= 1000) return `${(val / 1000).toFixed(1)}k`;
      return val.toFixed(0);
    };
    const cvdSubtext = `Último Delta: ${cvdDelta >= 0 ? '+' : ''}${formatMil(cvdDelta)}`;

    // 3. Presión de Compra
    const ultimaPresion = latest.presion_compra.toFixed(2);
    let presionSubtext = 'Imbalance Neutral';
    if (latest.presion_compra > 55) presionSubtext = 'Presión de Compra';
    else if (latest.presion_compra < 45) presionSubtext = 'Presión de Venta';

    // 4. Liquidaciones acumuladas en el bloque visible
    const totalLongsLiq = data.reduce((acc, curr) => acc + curr.liquidaciones_longs, 0);
    const totalShortsLiq = data.reduce((acc, curr) => acc + curr.liquidaciones_shorts, 0);

    // 5. Velocidad (TPS)
    const velocidadTps = latest.trades_per_second || 0;
    const velocidadSubtext = velocidadTps > 100 
      ? 'Alta Actividad HFT' 
      : velocidadTps > 45 
      ? 'Actividad Moderada' 
      : 'Actividad Baja';

    return {
      ultimoPrecio,
      precioChange: precioChangePct,
      precioChangeType,
      precioSubtext,
      ultimoCvd,
      cvdDelta,
      cvdChangeType,
      cvdSubtext,
      ultimaPresion,
      presionSubtext,
      totalLongsLiq,
      totalShortsLiq,
      velocidadTps,
      velocidadSubtext
    };
  };

  const metrics = getKpiMetrics();

  return (
    <div className="min-h-screen bg-[#08090c] text-slate-300 flex flex-col font-sans selection:bg-brand-cyan/20 selection:text-brand-cyan">
      
      {/* 1. Header Premium */}
      <header className={`sticky top-0 z-50 backdrop-blur-md transition-all duration-500 border-b ${
        config.modoSistema === 'REAL' 
          ? 'bg-red-950/15 border-brand-red/30 shadow-[0_0_25px_rgba(255,82,82,0.2)]' 
          : config.modoSistema === 'DEMO'
          ? 'bg-amber-955/15 border-amber-500/30 shadow-[0_0_25px_rgba(245,158,11,0.15)]'
          : 'bg-slate-950/60 border-slate-900'
      }`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Logo o Icono del Sistema */}
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-brand-cyan to-purple-600 flex items-center justify-center font-orbitron text-xs font-black text-black select-none shadow-lg shadow-brand-cyan/10">
              TS
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-sm font-black tracking-wider text-white font-orbitron uppercase">
                  TraderSuko
                </h1>
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono tracking-widest">
                  V1.5
                </span>
              </div>
              <p className="text-[9px] text-slate-500 font-orbitron font-medium tracking-wide">
                TRADERSUKO PRO QUANT TERMINAL
              </p>
            </div>
          </div>

          {/* Estado de Conexión y Control */}
          <div className="flex items-center gap-3">
            
            {/* Indicador de Alerta de Capital en Riesgo */}
            {config.modoSistema === 'REAL' && (
              <div className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-brand-red/20 bg-brand-red/10 text-brand-red text-[10px] font-mono font-black tracking-wider animate-pulse">
                <ShieldAlert className="w-3.5 h-3.5 text-brand-red" />
                <span>REAL TIME TRADING ACTIVO - CAPITAL EN RIESGO</span>
              </div>
            )}
            {config.modoSistema === 'DEMO' && (
              <div className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-amber-500/20 bg-amber-500/10 text-amber-500 text-[10px] font-mono font-black tracking-wider animate-pulse">
                <ShieldAlert className="w-3.5 h-3.5 text-amber-500" />
                <span>DEMO TRADING ACTIVO - EJECUCIÓN SIMULADA EN VIVO</span>
              </div>
            )}

            {/* Estado de VPN / Tailscale */}
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-[10px] font-mono font-semibold transition-all duration-300 ${
              isMocked 
                ? 'bg-amber-500/5 text-amber-400 border-amber-500/15'
                : 'bg-brand-green/5 text-brand-green border-brand-green/15 text-glow-green'
            }`}>
              {isMocked ? (
                <>
                  <WifiOff className="w-3.5 h-3.5 animate-pulse" />
                  <span>VPN DESCONECTADA (EMULADOR)</span>
                </>
              ) : (
                <>
                  <Wifi className="w-3.5 h-3.5 text-brand-green text-glow-green" />
                  <span>VPN SEGURA ACTIVA (100.91.150.120)</span>
                </>
              )}
            </div>

            {/* Frecuencia / Polling Indicator */}
            <div className="hidden sm:flex items-center gap-1.5 text-slate-500 text-xs font-mono border border-slate-900 bg-slate-950 px-3 py-1.5 rounded-lg">
              <Clock className="w-3.5 h-3.5 text-slate-600" />
              <span>5s POLLING {lastUpdate ? `[${lastUpdate.toLocaleTimeString()}]` : ''}</span>
            </div>

            {/* Botón Refrescar Manual */}
            <button
              onClick={() => fetchData(true)}
              disabled={isRefreshing}
              className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 transition-all duration-200 cursor-pointer disabled:opacity-50 flex items-center justify-center"
              title="Sincronizar ahora"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-brand-cyan' : ''}`} />
            </button>
          </div>
        </div>
      </header>

      {/* 1.5. Market Clocks Globales */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 w-full -mt-4">
        <div className="p-3 rounded-xl border border-slate-800/40 bg-slate-950/40 backdrop-blur-sm">
          <MarketClocks />
        </div>
      </div>

      {/* 2. Main Content */}
      <main className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 w-full flex flex-col gap-6">
        
        {/* Banner de Advertencia de Fallback si es simulado */}
        {isMocked && (
          <div className="p-4 rounded-xl border border-amber-500/10 bg-amber-500/5 text-amber-300/95 flex items-start gap-3 text-xs leading-relaxed animate-fade-in">
            <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-bold text-white block mb-0.5">Modo de simulación activado</span>
              No se pudo establecer conexión directa con la API del VPS en <code className="bg-slate-950/80 px-1 py-0.5 rounded text-amber-400">100.91.150.120:8000</code>. Asegúrate de tener activa tu red privada de **Tailscale** y el backend corriendo. Mientras tanto, el panel opera en modo demostrativo con simulación de flujos algorítmicos.
            </div>
          </div>
        )}

        {/* 4. Grid de KPIs + Radar + Muro (todo informativo) */}
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          <KPICard
            title="Último Precio BTC"
            value={metrics.ultimoPrecio ? `$${metrics.ultimoPrecio.toLocaleString('en-US', { minimumFractionDigits: 1 })}` : '---'}
            subValue={metrics.precioSubtext}
            change={metrics.precioChange}
            changeType={metrics.precioChangeType}
            icon="price"
            isLoading={isLoading}
          />
          <KPICard
            title="CVD Binance Acumulado"
            value={metrics.ultimoCvd ? metrics.ultimoCvd.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '---'}
            subValue={metrics.cvdSubtext}
            change={metrics.cvdDelta}
            changeType={metrics.cvdChangeType}
            icon="cvd"
            isLoading={isLoading}
          />
          <KPICard
            title="Presión del Orderbook"
            value={metrics.ultimoPrecio ? `${metrics.ultimaPresion}%` : '---'}
            subValue={metrics.presionSubtext}
            change={parseFloat(metrics.ultimaPresion)}
            changeType={parseFloat(metrics.ultimaPresion) > 50 ? 'up' as const : parseFloat(metrics.ultimaPresion) < 50 ? 'down' as const : 'neutral' as const}
            icon="pressure"
            isLoading={isLoading}
          />
          <KPICard
            title="Velocidad de Cinta (HFT)"
            value={metrics.ultimoPrecio ? `${metrics.velocidadTps}` : '---'}
            subValue={metrics.velocidadSubtext}
            change={metrics.velocidadTps}
            changeType={metrics.velocidadTps > 100 ? 'up' as const : 'neutral' as const}
            icon="speed"
            isLoading={isLoading}
          />
          {/* Radar y Muro como cards informativas */}
          <ConfirmationRadar
            radarData={radarData}
            isLoading={isLoading}
          />
          <OrderBookDepthWidget 
            latestRecord={data[data.length - 1]} 
            isLoading={isLoading} 
          />
        </div>

        {/* Panel de configuración de ventana — entre KPIs y gráfico */}
        <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl glass-panel">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-brand-cyan" />
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400 font-mono">
              Configuración de Ventana de Visualización
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 font-medium">Límite de registros:</span>
            <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-900">
              {[50, 100, 150].map((val) => (
                <button
                  key={val}
                  onClick={() => setLimit(val)}
                  className={`px-3 py-1 rounded text-xs font-mono font-bold transition-all duration-200 cursor-pointer ${
                    limit === val
                      ? 'bg-brand-cyan/10 text-brand-cyan border border-brand-cyan/20'
                      : 'text-slate-500 hover:text-slate-300 border border-transparent'
                  }`}
                >
                  {val}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 4.5. Gráfica de Trades sobre Precio */}
        <div className="w-full rounded-xl border border-slate-800/60 bg-slate-950/40 backdrop-blur-sm">
          <TradesChart 
            telemetria={data} 
            trades={trades} 
            isLoading={isLoading || isTradesLoading}
          />
        </div>

        {/* 5. Área de Gráficos + Widgets interactivos */}
        <div className="flex flex-col gap-6">
          <div className="w-full">
            <CvdChart data={data} isLoading={isLoading} pocPrice={pocData?.pocPrecio} />
          </div>
          
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Columna Izquierda: Gráfico de Liquidaciones + Terminal de Logs */}
            <div className="lg:col-span-2 flex flex-col gap-6">
              
              {/* Gráfico de Liquidaciones */}
              <LiquidationsChart 
                data={data} 
                isLoading={isLoading} 
                totalLongsLiq={metrics.totalLongsLiq}
                totalShortsLiq={metrics.totalShortsLiq}
              />

              {/* Bitácora de Logs */}
              <AlertsLog 
                alerts={alerts} 
                isLoading={isLoading} 
                isMocked={isAlertsMocked} 
                onRefresh={() => fetchData(true)} 
              />
            </div>

            {/* Columna Derecha: Solo widgets interactivos (Executor, Position, Config) */}
            <div className="lg:col-span-1 flex flex-col gap-6">
              
              {/* TradingPanel fusionado (Executor + Position) */}
              <TradingPanel
                executor={executorStatus}
                position={position}
                isLoading={isLoading}
              />

              {/* Calibrador de Sensibilidad */}
              <ConfigCard 
                config={config}
                onConfigChange={setConfig}
                isSaving={isSavingConfig}
                saveStatus={configSaveStatus}
                isApiMocked={isConfigMocked}
              />
            </div>

          </div>

          {/* R-Results Financial Auditor Table */}
          <RMultiplesHistory
            trades={trades}
            isLoading={isTradesLoading}
          />
        </div>
      </main>

      {/* 6. Footer */}
      <footer className="border-t border-slate-900 bg-slate-950/40 py-6 mt-12 text-center text-xs font-mono text-slate-600">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row justify-between items-center gap-4">
          <div className="flex items-center gap-2">
            <Server className="w-3.5 h-3.5 text-slate-700" />
            <span>Target Node: {API_BASE_URL}</span>
          </div>
          <div>
            <span>TraderSuko Frontend System • Copiloto Antigravity 2026</span>
          </div>
        </div>
      </footer>
    </div>
  );
};
