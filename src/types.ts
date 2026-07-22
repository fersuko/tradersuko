export interface TelemetriaRegistro {
  id: number;
  timestamp: string;
  precio: number;
  cvd_binance: number;
  presion_compra: number;
  liquidaciones_longs: number;
  liquidaciones_shorts: number;
  orderbook_depth_buyer: number;
  orderbook_depth_seller: number;
  trades_per_second: number;
}

export interface TelemetriaResponse {
  ok: boolean;
  count: number;
  total_registros: number;
  data: TelemetriaRegistro[];
}

export type ModoSistema = 'SIMULACION' | 'DEMO' | 'REAL';

export interface SystemConfig {
  umbralLiquidaciones: number;
  deltaCvd: number;
  leverage: number;
  margenOperacion: number;
  modoSistema: ModoSistema;
}

export interface ActiveTradeDetail {
  id: number;
  lado: string;
  precio_entrada: number;
  cantidad_btc: number;
  stop_loss: number;
  take_profit: number;
  edad_horas: number;
  timestamp: string;
}

export interface ExecutorStatus {
  modo: ModoSistema;
  keys: {
    real: boolean;
    demo: boolean;
  };
  tradesHoy: number;
  circuitBreaker: {
    bloqueado: boolean;
    disponibles: number;
  };
  tradesActivos: number;
  tradesActivosLista: ActiveTradeDetail[];
  pnlDia: number;
  ultimoTrade: {
    timestamp: string;
    tipo: string;
    precio: number;
    lado: string;
    precio_entrada: number;
    apalancamiento_usado: number;
    mensaje?: string;
  } | null;
  ultimaSenal: {
    timestamp: string;
    tipo: string;
    mensaje?: string;
  } | null;
  ultimoInicio: {
    timestamp: string;
    version?: string;
  } | null;
}

export interface PocData {
  pocPrecio: number;
  pocVolumen: number;
}

export interface SystemAlert {
  id: number;
  timestamp: string;
  tipo: string;
  mensaje: string;
}

export interface RadarData {
  barridoLiquidez: number;
  barridoLiquidezUmbral: number;
  giroCvd: number;
  giroCvdUmbral: number;
  soporteObRatio: number;
  soporteObMinimo: number;
  estado: 'BLOQUEADO' | 'ATENCION' | 'CONFIRMADO';
  condicionesCumplidas: number;
  condicionesNecesarias: number;
}

export interface PositionData {
  id: number;
  symbol: string;
  side: 'LONG' | 'SHORT';
  entryPrice: number;
  markPrice: number;
  size: number;
  leverage: number;
  pnl: number;
  stopLoss: number;
  takeProfit: number | null;
  rActive: number;
  riskUsd: number;       // Riesgo real en USD (SL_dist * size)
  marginUsd: number;     // Margen real usado (entry * size / leverage)
  riskPerBtc: number;    // Distancia al SL en $ por BTC
  pnlType: string;
}

export interface TradeData {
  id: number;
  timestamp: string;
  side: 'LONG' | 'SHORT';
  entryPrice: number;
  exitPrice: number | null;
  rMultiple: number;
  pnl: number;
  estado: string;
  modo: string;
  amountBtc: number;
  apalancamiento: number;
}



