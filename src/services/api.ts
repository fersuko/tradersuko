import type { TelemetriaResponse, TelemetriaRegistro, SystemConfig, PocData, SystemAlert, RadarData, ExecutorStatus, ModoSistema, PositionData, TradeData } from '../types';

// URL base de la API desde las variables de entorno de Vite o fallback a la IP de Tailscale provista
export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://100.91.150.120:8000';

// Configuración simulada inicial
let localConfig: SystemConfig = {
  umbralLiquidaciones: 150000,
  deltaCvd: 750000,
  leverage: 10,
  margenOperacion: 2.5,
  modoSistema: 'SIMULACION'
};

// Generador de datos simulados para fallback en desarrollo/pruebas
let simulatedData: TelemetriaRegistro[] = [];

const generateMockData = (count: number): TelemetriaRegistro[] => {
  const data: TelemetriaRegistro[] = [];
  let basePrice = 64000;
  let baseCvd = -110000000;
  const now = new Date();

  for (let i = count; i >= 0; i--) {
    const time = new Date(now.getTime() - i * 5000); // 5 segundos entre registros
    const priceChange = (Math.random() - 0.49) * 45; // Sesgo leve alcista
    basePrice += priceChange;
    
    // CVD correlacionado parcialmente con el precio
    const cvdChange = priceChange * 150000 + (Math.random() - 0.5) * 500000;
    baseCvd += cvdChange;

    // Liquidaciones ocasionales
    const hasLongLiquidation = Math.random() > 0.92;
    const hasShortLiquidation = Math.random() > 0.94;
    
    const liquidaciones_longs = hasLongLiquidation ? Math.round(Math.random() * 850000) : 0;
    const liquidaciones_shorts = hasShortLiquidation ? Math.round(Math.random() * 600000) : 0;

    // Presión de compra (orderbook imbalance)
    const presion_compra = Math.min(100, Math.max(0, 50 + (priceChange * 0.8) + (Math.random() - 0.5) * 10));

    data.push({
      id: 3000 - i,
      timestamp: time.toISOString(),
      precio: Math.round(basePrice * 10) / 10,
      cvd_binance: Math.round(baseCvd * 100) / 100,
      presion_compra: Math.round(presion_compra * 100) / 100,
      liquidaciones_longs,
      liquidaciones_shorts,
      orderbook_depth_buyer: Math.round((20 + Math.random() * 80) * 100) / 100,
      orderbook_depth_seller: Math.round((20 + Math.random() * 80) * 100) / 100,
      trades_per_second: Math.round(15 + Math.random() * 45)
    });
  }
  return data;
};

// Inicializar datos simulados
simulatedData = generateMockData(100);

// Función para actualizar datos simulados agregando una nueva vela en cada polling
const tickSimulatedData = () => {
  const lastIndex = simulatedData.length - 1;
  const lastItem = simulatedData[lastIndex];
  
  const now = new Date();
  const priceChange = (Math.random() - 0.48) * 60; // Sesgo leve alcista
  const nextPrice = Math.round((lastItem.precio + priceChange) * 10) / 10;
  const cvdChange = priceChange * 160000 + (Math.random() - 0.5) * 600000;
  const nextCvd = Math.round((lastItem.cvd_binance + cvdChange) * 100) / 100;
  
  const hasLongLiquidation = Math.random() > 0.91;
  const hasShortLiquidation = Math.random() > 0.93;
  const liquidaciones_longs = hasLongLiquidation ? Math.round(Math.random() * 950000) : 0;
  const liquidaciones_shorts = hasShortLiquidation ? Math.round(Math.random() * 750000) : 0;

  const presion_compra = Math.min(100, Math.max(0, 50 + (priceChange * 0.8) + (Math.random() - 0.5) * 12));

  // Simular profundidad de order book con un 1% de desviación (muros de TRDR)
  const buyerDepth = Math.round((20 + Math.random() * 100) * 100) / 100;
  // A veces hacemos que un muro domine (>1.5x) para disparar el filtro visual
  const forceImbalance = Math.random() > 0.5;
  const sellerDepth = forceImbalance
    ? Math.round((buyerDepth * (Math.random() > 0.5 ? 1.6 : 0.5)) * 100) / 100
    : Math.round((20 + Math.random() * 100) * 100) / 100;

  // Simular trades_per_second disparados ante liquidaciones o alta volatilidad (HFTs)
  const isHighActivity = liquidaciones_longs > 0 || liquidaciones_shorts > 0 || Math.abs(priceChange) > 25;
  const tps = isHighActivity 
    ? Math.round(120 + Math.random() * 230) // HFTs ingresando
    : Math.round(10 + Math.random() * 50);

  const newRecord: TelemetriaRegistro = {
    id: lastItem.id + 1,
    timestamp: now.toISOString(),
    precio: nextPrice,
    cvd_binance: nextCvd,
    presion_compra: Math.round(presion_compra * 100) / 100,
    liquidaciones_longs,
    liquidaciones_shorts,
    orderbook_depth_buyer: buyerDepth,
    orderbook_depth_seller: sellerDepth,
    trades_per_second: tps
  };

  simulatedData.push(newRecord);
  if (simulatedData.length > 150) {
    simulatedData.shift(); // Mantener un límite manejable
  }
};

/**
 * Obtiene los registros de telemetría de la API del VPS.
 * Si la petición falla (por ejemplo, por no estar conectado a Tailscale en desarrollo),
 * hace fallback transparente a datos simulados hermosos.
 */
export const getTelemetria = async (limit: number = 100): Promise<{ response: TelemetriaResponse; isMocked: boolean }> => {
  try {
    // Intentar fetching real con un timeout corto para no ralentizar el UI si la VPN está caída
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500); // 2.5 segundos de timeout

    const response = await fetch(`${API_BASE_URL}/api/v1/telemetria?limit=${limit}`, {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json',
      }
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data: TelemetriaResponse = await response.json();
    return { response: data, isMocked: false };
  } catch (error) {
    // Si la conexión falla o el host es inalcanzable, usamos datos simulados
    console.warn('Conexión con el VPS fallida. Usando datos simulados de telemetría.', error);
    
    // Generar un nuevo registro simulado para reflejar cambios en tiempo real
    tickSimulatedData();
    
    const sliceData = simulatedData.slice(-limit);
    
    return {
      response: {
        ok: true,
        count: sliceData.length,
        total_registros: 3000 + sliceData.length,
        data: sliceData
      },
      isMocked: true
    };
  }
};

/**
 * Obtiene la configuración actual del bot desde el VPS.
 * Fallback a configuración local simulada si no hay conexión.
 */
export const getConfig = async (): Promise<{ config: SystemConfig; isMocked: boolean }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);

    const response = await fetch(`${API_BASE_URL}/api/v1/config`, {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json'
      }
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const rawData = await response.json();
    
    // Sliders de calibración consumen response.calibration
    const source = rawData.calibration || rawData.data || rawData;
    
    // Traducir de snake_case (FastAPI) a camelCase (React/TypeScript)
    const config: SystemConfig = {
      umbralLiquidaciones: Number(source.umbral_liquidaciones),
      deltaCvd: Number(source.delta_cvd_confirmacion),
      leverage: Number(source.apalancamiento),
      margenOperacion: Number(source.margen_operacion),
      modoSistema: (source.modo_sistema as ModoSistema) || 'SIMULACION'
    };

    localConfig = config;
    return { config, isMocked: false };
  } catch (error) {
    console.warn('Fallo al obtener configuración del VPS. Usando configuración simulada.', error);
    return { config: localConfig, isMocked: true };
  }
};

/**
 * Guarda la configuración en la base de datos de Docker del VPS.
 * Fallback local si falla la red.
 */
export const saveConfig = async (config: SystemConfig): Promise<{ success: boolean; isMocked: boolean }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);

    // Traducir de camelCase (React) a snake_case (FastAPI/Postgres)
    const rawConfig = {
      umbral_liquidaciones: config.umbralLiquidaciones,
      delta_cvd_confirmacion: config.deltaCvd,
      apalancamiento: config.leverage,
      margen_operacion: config.margenOperacion,
      modo_sistema: config.modoSistema
    };

    const response = await fetch(`${API_BASE_URL}/api/v1/config`, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify(rawConfig)
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const rawData = await response.json();
    const source = rawData.calibration || rawData.data || rawData;

    // Actualizar localConfig si viene la respuesta del server
    if (source && source.umbral_liquidaciones) {
      localConfig = {
        umbralLiquidaciones: Number(source.umbral_liquidaciones),
        deltaCvd: Number(source.delta_cvd_confirmacion),
        leverage: Number(source.apalancamiento),
        margenOperacion: Number(source.margen_operacion),
        modoSistema: (source.modo_sistema as ModoSistema) || 'SIMULACION'
      };
    } else {
      localConfig = config;
    }

    return { success: true, isMocked: false };
  } catch (error) {
    console.warn('Fallo al guardar configuración en VPS. Guardando localmente.', error);
    localConfig = config;
    return { success: true, isMocked: true };
  }
};

/**
 * Obtiene el Point of Control (POC) de volumen desde el VPS.
 * Fallback a POC simulado si no hay conexión.
 */
export const getPoc = async (): Promise<{ poc: PocData; isMocked: boolean }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);

    const response = await fetch(`${API_BASE_URL}/api/v1/poc`, {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json'
      }
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const rawData = await response.json();
    const poc: PocData = {
      pocPrecio: Number(rawData.poc_precio),
      pocVolumen: Number(rawData.poc_volumen)
    };

    return { poc, isMocked: false };
  } catch (error) {
    // Fallback a POC simulado cercano al último precio simulado
    const lastPrice = simulatedData.length > 0 ? simulatedData[simulatedData.length - 1].precio : 64000;
    // Colocar el POC un poco desplazado por debajo del precio actual como soporte
    const pocPrecio = Math.round((lastPrice * 0.9991) * 10) / 10;
    
    return {
      poc: {
        pocPrecio,
        pocVolumen: Math.round(2200 + Math.random() * 1200)
      },
      isMocked: true
    };
  }
};

// Alertas simuladas iniciales
let simulatedAlerts: SystemAlert[] = [
  { id: 1, timestamp: new Date(Date.now() - 40000).toISOString(), tipo: 'INFO', mensaje: 'Sistema de Ingestión de Datos Hermes inicializado con éxito.' },
  { id: 2, timestamp: new Date(Date.now() - 30000).toISOString(), tipo: 'INFO', mensaje: 'Bucle analítico del Brain iniciado en modo DRY RUN (Simulación).' },
  { id: 3, timestamp: new Date(Date.now() - 20000).toISOString(), tipo: 'INFO', mensaje: 'Buscando ineficiencias y desbalances en la cotización de BTC/USDT...' }
];

const addSimulatedAlert = () => {
  const types: ('INFO' | 'WARNING' | 'TRADE_LONG' | 'TRADE_SHORT' | 'BLOCK')[] = ['INFO', 'WARNING', 'BLOCK', 'INFO'];
  const type = types[Math.floor(Math.random() * types.length)];
  const now = new Date();
  let msg = '';
  
  if (type === 'INFO') {
    const msgs = [
      'Heartbeat: Conexión WebSocket con Binance estable. Latencia 12ms.',
      'Mapeo de volumen profile completado. POC recalculado en zona de soporte.',
      'Heartbeat del Brain: Esperando anomalías en CVD de Binance...',
      'Monitoreando muros institucionales al 1%. Estabilidad detectada.'
    ];
    msg = msgs[Math.floor(Math.random() * msgs.length)];
  } else if (type === 'WARNING') {
    const msgs = [
      'Anomalía detectada: Agresión vendedora inusitada detectada en CVD.',
      'Pico de volatilidad registrado: Trades por segundo superan 120 tps.',
      'Barrido de liquidez detectado en zona de soporte local.'
    ];
    msg = msgs[Math.floor(Math.random() * msgs.length)];
  } else if (type === 'BLOCK') {
    msg = `Filtro de Muros: Disparo por CVD cancelado. Muros débiles. Ratio de Bids actual: ${(1.1 + Math.random() * 0.3).toFixed(2)}x < 1.5x.`;
  } else {
    msg = `Orden simulada: Compra de LONG ejecutada con apalancamiento 10x a precio de mercado.`;
  }
  
  simulatedAlerts.push({
    id: simulatedAlerts.length + 1,
    timestamp: now.toISOString(),
    tipo: type,
    mensaje: msg
  });
  
  if (simulatedAlerts.length > 25) {
    simulatedAlerts.shift();
  }
};

/**
 * Obtiene las alertas de decisión más recientes del bot desde el VPS.
 * Fallback a alertas locales simuladas si no hay conexión.
 */
export const getAlertas = async (limit: number = 10): Promise<{ alertas: SystemAlert[]; isMocked: boolean }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);

    const response = await fetch(`${API_BASE_URL}/api/v1/alertas?limit=${limit}`, {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json'
      }
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const rawData = await response.json();
    const rawAlerts: any[] = rawData.data || [];

    // Mapear asegurando fallbacks para id y timestamp si no vienen en el JSON
    const alertas: SystemAlert[] = rawAlerts.map((item: any, index: number) => ({
      id: item.id || index + 1,
      timestamp: item.timestamp || new Date().toISOString(),
      tipo: String(item.tipo),
      mensaje: String(item.mensaje)
    }));

    return { alertas, isMocked: false };
  } catch (error) {
    // Añadir una nueva alerta simulada el 40% de las veces que se consulta
    if (Math.random() > 0.6) {
      addSimulatedAlert();
    }
    
    const sliceAlerts = [...simulatedAlerts].reverse().slice(0, limit);
    return { alertas: sliceAlerts, isMocked: true };
  }
};

/**
 * Obtiene el estado del Radar de Confirmación desde el VPS.
 * Fallback a datos simulados si no hay conexión.
 */
export const getRadar = async (): Promise<{ radar: RadarData; isMocked: boolean }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);

    const response = await fetch(`${API_BASE_URL}/api/v1/radar`, {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json'
      }
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const rawData = await response.json();
    const rawRadar = rawData.radar;

    const radar: RadarData = {
      barridoLiquidez: Number(rawRadar.barrido_liquidez),
      barridoLiquidezUmbral: Number(rawRadar.barrido_liquidez_umbral),
      giroCvd: Number(rawRadar.giro_cvd),
      giroCvdUmbral: Number(rawRadar.giro_cvd_umbral),
      soporteObRatio: Number(rawRadar.soporte_ob_ratio),
      soporteObMinimo: Number(rawRadar.soporte_ob_minimo),
      estado: rawRadar.estado,
      condicionesCumplidas: Number(rawRadar.condiciones_cumplidas),
      condicionesNecesarias: Number(rawRadar.condiciones_necesarias)
    };

    return { radar, isMocked: false };
  } catch (error) {
    // Generar valores simulados realistas coherentes con localConfig
    const totalLiq = Math.random() > 0.85 
      ? Math.round(localConfig.umbralLiquidaciones * (1.1 + Math.random() * 0.4)) 
      : Math.round(localConfig.umbralLiquidaciones * (0.1 + Math.random() * 0.7));
    const cvd = Math.random() > 0.75 
      ? Math.round(localConfig.deltaCvd * (1.05 + Math.random() * 0.5)) 
      : Math.round(localConfig.deltaCvd * (0.3 + Math.random() * 0.6));
    const ratio = Math.round((0.8 + Math.random() * 1.1) * 100) / 100;

    const meetsLiq = totalLiq >= localConfig.umbralLiquidaciones;
    const meetsCvd = cvd >= localConfig.deltaCvd;
    const meetsRatio = ratio >= 1.5;

    let cumplidas = 0;
    if (meetsLiq) cumplidas++;
    if (meetsCvd) cumplidas++;
    if (meetsRatio) cumplidas++;

    let estado: 'BLOQUEADO' | 'ATENCION' | 'CONFIRMADO' = 'BLOQUEADO';
    if (cumplidas === 3) {
      estado = 'CONFIRMADO';
    } else if (cumplidas > 0) {
      estado = 'ATENCION';
    }

    return {
      radar: {
        barridoLiquidez: totalLiq,
        barridoLiquidezUmbral: localConfig.umbralLiquidaciones,
        giroCvd: cvd,
        giroCvdUmbral: localConfig.deltaCvd,
        soporteObRatio: ratio,
        soporteObMinimo: 1.5,
        estado,
        condicionesCumplidas: cumplidas,
        condicionesNecesarias: 3
      },
      isMocked: true
    };
  }
};

/**
 * Obtiene el estado del Executor desde el VPS.
 * Fallback a datos simulados si no hay conexión.
 */
export const getExecutorStatus = async (): Promise<{ status: ExecutorStatus; isMocked: boolean }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);

    const response = await fetch(`${API_BASE_URL}/api/v1/executor/status`, {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json'
      }
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const rawData = await response.json();
    const raw = rawData.executor;

    const status: ExecutorStatus = {
      modo: raw.modo as ModoSistema,
      keys: {
        real: Boolean(raw.keys.real),
        demo: Boolean(raw.keys.demo)
      },
      tradesHoy: Number(raw.trades_hoy),
      circuitBreaker: {
        bloqueado: Boolean(raw.circuit_breaker.bloqueado),
        disponibles: Number(raw.circuit_breaker.disponibles)
      },
      ultimoTrade: raw.ultimo_trade ? {
        timestamp: String(raw.ultimo_trade.timestamp || new Date().toISOString()),
        tipo: String(raw.ultimo_trade.tipo || raw.ultimo_trade.side || raw.ultimo_trade.tipo_orden || 'TRADE'),
        precio: Number(raw.ultimo_trade.precio || raw.ultimo_trade.price || 0),
        mensaje: raw.ultimo_trade.mensaje ? String(raw.ultimo_trade.mensaje) : undefined
      } : null,
      ultimaSenal: raw.ultima_senal ? {
        timestamp: String(raw.ultima_senal.timestamp || new Date().toISOString()),
        tipo: String(raw.ultima_senal.tipo || raw.ultima_senal.tipo_senal || 'SIGNAL'),
        mensaje: raw.ultima_senal.mensaje ? String(raw.ultima_senal.mensaje) : undefined
      } : null,
      ultimoInicio: raw.ultimo_inicio ? {
        timestamp: String(raw.ultimo_inicio.timestamp || new Date().toISOString()),
        version: raw.ultimo_inicio.version ? String(raw.ultimo_inicio.version) : undefined
      } : null
    };

    return { status, isMocked: false };
  } catch (error) {
    const now = new Date();
    
    const hasTrade = localConfig.modoSistema !== 'SIMULACION';
    const mockTrade = hasTrade ? {
      timestamp: new Date(now.getTime() - 3600000).toISOString(),
      tipo: 'BUY_LONG',
      precio: 64120.5,
      mensaje: 'Ejecución exitosa de orden LONG en Binance'
    } : null;

    const mockSenal = {
      timestamp: new Date(now.getTime() - 120000).toISOString(),
      tipo: 'CVD_SIGNAL',
      mensaje: 'Fuerte giro alcista institucional detectado en CVD delta'
    };

    return {
      status: {
        modo: localConfig.modoSistema,
        keys: {
          real: true,
          demo: true
        },
        tradesHoy: localConfig.modoSistema === 'SIMULACION' ? 0 : 1,
        circuitBreaker: {
          bloqueado: false,
          disponibles: 3
        },
        ultimoTrade: mockTrade,
        ultimaSenal: mockSenal,
        ultimoInicio: {
          timestamp: new Date(now.getTime() - 86400000).toISOString(),
          version: '1.2.0'
        }
      },
      isMocked: true
    };
  }
};

/**
 * Obtiene la posición activa actual desde el VPS.
 */
export const getPosition = async (): Promise<{ position: PositionData | null; isMocked: boolean }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);

    const response = await fetch(`${API_BASE_URL}/api/v1/position`, {
      signal: controller.signal,
      headers: { 'Accept': 'application/json' }
    });

    clearTimeout(timeoutId);

    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

    const rawData = await response.json();
    const raw = rawData.position;

    if (!raw) return { position: null, isMocked: false };

    const position: PositionData = {
      id: Number(raw.id),
      symbol: String(raw.symbol),
      side: raw.side as 'LONG' | 'SHORT',
      entryPrice: Number(raw.entry_price || raw.entryPrice || 0),
      markPrice: Number(raw.mark_price || raw.markPrice || 0),
      size: Number(raw.size || 0),
      leverage: Number(raw.leverage || 10),
      pnl: Number(raw.pnl || 0),
      stopLoss: Number(raw.stop_loss || raw.stopLoss || 0),
      takeProfit: raw.take_profit ? Number(raw.take_profit) : null,
      rActive: Number(raw.r_active ?? raw.rActive ?? 0),
      rDistance: Number(raw.r_distance ?? raw.rDistance ?? 0),
      pnlType: String(raw.pnl_type || raw.pnlType || 'MARK_TO_MARKET')
    };

    return { position, isMocked: false };
  } catch (error) {
    console.warn('Fallo al obtener posición del VPS. Usando mock.', error);
    
    const isSimulatedActive = localConfig.modoSistema !== 'SIMULACION';
    if (!isSimulatedActive) {
      return { position: null, isMocked: true };
    }

    const lastPrice = simulatedData.length > 0 ? simulatedData[simulatedData.length - 1].precio : 65000;
    const entryPrice = 65142.20;
    const stopLoss = 64842.20;
    const pnl = (lastPrice - entryPrice) * 0.0155;
    
    const riskAmount = 300.0;
    const rActive = pnl / riskAmount;
    const rDistance = (lastPrice - stopLoss) / (entryPrice - stopLoss) - 1.0;

    return {
      position: {
        id: 71,
        symbol: 'BTCUSDT',
        side: 'LONG',
        entryPrice,
        markPrice: lastPrice,
        size: 0.0155,
        leverage: 10,
        pnl: Math.round(pnl * 100) / 100,
        stopLoss,
        takeProfit: null,
        rActive: Math.round(rActive * 100) / 100,
        rDistance: Math.round(rDistance * 100) / 100,
        pnlType: 'MARK_TO_MARKET'
      },
      isMocked: true
    };
  }
};

/**
 * Obtiene el historial de trades desde el VPS.
 */
export const getTrades = async (): Promise<{ trades: TradeData[]; isMocked: boolean }> => {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);

    const response = await fetch(`${API_BASE_URL}/api/v1/trades`, {
      signal: controller.signal,
      headers: { 'Accept': 'application/json' }
    });

    clearTimeout(timeoutId);

    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

    const rawData = await response.json();
    const rawTrades: any[] = rawData.trades || [];

    const trades: TradeData[] = rawTrades.map((raw) => ({
      id: Number(raw.id),
      timestamp: String(raw.timestamp || raw.time || new Date().toISOString()),
      side: (raw.side || raw.tipo) as 'LONG' | 'SHORT',
      entryPrice: Number(raw.entry_price || raw.entryPrice || 0),
      rMultiple: Number(raw.r_multiple ?? raw.rMultiple ?? 0),
      pnl: Number(raw.pnl ?? raw.pnl_realizado ?? 0)
    }));

    return { trades, isMocked: false };
  } catch (error) {
    console.warn('Fallo al obtener trades del VPS. Usando mock.', error);
    
    const now = new Date();
    const mockTrades: TradeData[] = [
      { id: 71, timestamp: new Date(now.getTime() - 300000).toISOString(), side: 'LONG', entryPrice: 65142.20, rMultiple: -0.05, pnl: -0.30 },
      { id: 70, timestamp: new Date(now.getTime() - 900000).toISOString(), side: 'LONG', entryPrice: 65074.5, rMultiple: 0.01, pnl: 3.25 },
      { id: 69, timestamp: new Date(now.getTime() - 1800000).toISOString(), side: 'LONG', entryPrice: 64915.0, rMultiple: 0.01, pnl: 3.10 },
      { id: 68, timestamp: new Date(now.getTime() - 3600000).toISOString(), side: 'LONG', entryPrice: 64200.0, rMultiple: 0.04, pnl: 13.40 },
      { id: 67, timestamp: new Date(now.getTime() - 7200000).toISOString(), side: 'SHORT', entryPrice: 64510.2, rMultiple: -0.05, pnl: -15.00 },
      { id: 66, timestamp: new Date(now.getTime() - 14400000).toISOString(), side: 'LONG', entryPrice: 63980.0, rMultiple: 2.10, pnl: 630.00 },
      { id: 65, timestamp: new Date(now.getTime() - 28800000).toISOString(), side: 'SHORT', entryPrice: 64120.0, rMultiple: -1.00, pnl: -300.00 }
    ];

    return { trades: mockTrades, isMocked: true };
  }
};


