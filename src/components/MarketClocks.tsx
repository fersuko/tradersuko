import React, { useState, useEffect } from 'react';

interface MarketClock {
  city: string;
  flag: string;
  timezone: string;
  utcOffset: number;
  isActive: boolean;
  sessionLabel: string;
}

const MARKETS: MarketClock[] = [
  {
    city: 'México',
    flag: '🇲🇽',
    timezone: 'America/Mexico_City',
    utcOffset: -6,
    isActive: false,
    sessionLabel: '',
  },
  {
    city: 'New York',
    flag: '🇺🇸',
    timezone: 'America/New_York',
    utcOffset: -5,
    isActive: false,
    sessionLabel: '',
  },
  {
    city: 'Londres',
    flag: '🇬🇧',
    timezone: 'Europe/London',
    utcOffset: 0,
    isActive: false,
    sessionLabel: '',
  },
  {
    city: 'Hong Kong',
    flag: '🇭🇰',
    timezone: 'Asia/Hong_Kong',
    utcOffset: 8,
    isActive: false,
    sessionLabel: '',
  },
];

// Horarios de sesiones cripto (UTC)
// Se considera "alta actividad" cuando hay traslape entre mercados o sesiones principales
function getCryptoSessionInfo(now: Date): { isActive: boolean; label: string }[] {
  const utcHour = now.getUTCHours();
  const utcMin = now.getUTCMinutes();
  const utcTotalMin = utcHour * 60 + utcMin;

  const results: { isActive: boolean; label: string }[] = [];

  // Mexico City (UTC-6, sin dst por simplicidad)
  const mxTotalMin = (utcTotalMin + 18 * 60) % (24 * 60); // UTC-6
  const mxHour = Math.floor(mxTotalMin / 60);
  const isMXActive = mxHour >= 7 && mxHour < 18; // 7:00-18:00 CDMX
  results.push({ isActive: isMXActive, label: isMXActive ? 'Sesión activa 🌤️' : 'Fuera de horario 🌙' });

  // New York (UTC-5)
  const nyTotalMin = (utcTotalMin + 19 * 60) % (24 * 60);
  const nyHour = Math.floor(nyTotalMin / 60);
  const isNYActive = nyHour >= 8 && nyHour < 17; // 8:00-17:00 NY
  results.push({ isActive: isNYActive, label: isNYActive ? 'Sesión activa 🏛️' : 'Mercado cerrado 🌙' });

  // London (UTC+0)
  const ldnTotalMin = (utcTotalMin + 24 * 60) % (24 * 60);
  const ldnHour = Math.floor(ldnTotalMin / 60);
  const isLdnActive = ldnHour >= 8 && ldnHour < 17; // 8:00-17:00 London
  results.push({ isActive: isLdnActive, label: isLdnActive ? 'Sesión activa 🇬🇧' : 'Fuera de horario 🌙' });

  // Hong Kong (UTC+8)
  const hkTotalMin = (utcTotalMin + 8 * 60) % (24 * 60);
  const hkHour = Math.floor(hkTotalMin / 60);
  const isHKActive = hkHour >= 9 && hkHour < 17; // 9:00-17:00 HK
  results.push({ isActive: isHKActive, label: isHKActive ? 'Sesión activa 🏯' : 'Fuera de horario 🌙' });

  return results;
}

function formatTime(date: Date, tz: string): string {
  try {
    return date.toLocaleTimeString('en-US', {
      timeZone: tz,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return '--:--:--';
  }
}

function formatDate(date: Date, tz: string): string {
  try {
    return date.toLocaleDateString('en-US', {
      timeZone: tz,
      weekday: 'short',
      day: 'numeric',
      month: 'short',
    });
  } catch {
    return '---';
  }
}

export const MarketClocks: React.FC = () => {
  const [now, setNow] = useState<Date>(new Date());

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(new Date());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const sessionInfo = getCryptoSessionInfo(now);

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {MARKETS.map((market, idx) => {
        const info = sessionInfo[idx];
        return (
          <div
            key={market.city}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[11px] font-mono transition-all duration-300 ${
              info.isActive
                ? 'bg-brand-green/5 text-brand-green border-brand-green/20 shadow-[0_0_12px_rgba(34,197,94,0.1)]'
                : 'bg-slate-950/40 text-slate-500 border-slate-800/60'
            }`}
            title={`${market.city} (UTC${market.utcOffset >= 0 ? '+' : ''}${market.utcOffset})`}
          >
            {/* Indicador de estado (pulso verde cuando activo, gris cuando no) */}
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                info.isActive
                  ? 'bg-brand-green animate-pulse shadow-[0_0_6px_rgba(34,197,94,0.6)]'
                  : 'bg-slate-700'
              }`}
            />

            {/* Banderín y ciudad */}
            <span className="font-semibold tracking-wide">
              {market.flag} {market.city}
            </span>

            {/* Hora */}
            <span className="font-bold text-white/90 tabular-nums">
              {formatTime(now, market.timezone)}
            </span>

            {/* Fecha compacta */}
            <span className="text-[9px] text-slate-500 hidden sm:inline">
              {formatDate(now, market.timezone)}
            </span>

            {/* Label de sesión (solo cuando activo) */}
            {info.isActive && (
              <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-brand-green/10 text-brand-green border border-brand-green/20 ml-1 hidden md:inline">
                {info.label.split(' ').pop()?.replace('🏛️', '').replace('🇬🇧', '').replace('🏯', '').trim() || 'ACTIVO'}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
};
