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
  ultimoTrade: {
    timestamp: string;
    tipo: string;
    precio: number;
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



