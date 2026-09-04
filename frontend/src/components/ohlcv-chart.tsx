"use client";

import { useMemo, useState } from "react";
import type { DemoScenario } from "../lib/schemas";

type Timeframe = "15m" | "1h" | "4h";

const timeframes: Timeframe[] = ["15m", "1h", "4h"];
const chartWidth = 760;
const chartHeight = 280;
const chartPadding = 24;

type MarketHistory = DemoScenario["selectedPairEvidence"]["market_history"];

export function OhlcvChart({ history }: { history: MarketHistory }) {
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const candles = useMemo(() => history[timeframe]?.candles ?? [], [history, timeframe]);
  const chart = useMemo(() => {
    const prices = candles.flatMap((candle) => [Number(candle.high), Number(candle.low)]);
    const highest = Math.max(...prices, 1);
    const lowest = Math.min(...prices, highest);
    const range = highest - lowest || 1;
    const innerWidth = chartWidth - chartPadding * 2;
    const innerHeight = chartHeight - chartPadding * 2;
    const slot = innerWidth / Math.max(candles.length, 1);
    const y = (price: number) => chartPadding + ((highest - price) / range) * innerHeight;
    return { highest, lowest, innerHeight, slot, y };
  }, [candles]);

  return (
    <div className="chart-card">
      <div className="chart-heading">
        <div>
          <p className="eyebrow">CLOSED OHLCV EVIDENCE</p>
          <h3>{timeframe} · {candles.length} candles</h3>
        </div>
        <div className="chart-switcher" role="group" aria-label="OHLCV timeframe">
          {timeframes.map((item) => (
            <button
              className={timeframe === item ? "chart-switch active" : "chart-switch"}
              type="button"
              key={item}
              onClick={() => setTimeframe(item)}
              aria-pressed={timeframe === item}
            >
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="chart-viewport">
        <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={`${timeframe} candlestick chart`}>
        <line className="chart-gridline" x1={chartPadding} x2={chartWidth - chartPadding} y1={chartPadding} y2={chartPadding} />
        <line className="chart-gridline" x1={chartPadding} x2={chartWidth - chartPadding} y1={chartHeight / 2} y2={chartHeight / 2} />
        <line className="chart-gridline" x1={chartPadding} x2={chartWidth - chartPadding} y1={chartHeight - chartPadding} y2={chartHeight - chartPadding} />
          {candles.map((candle, index) => {
            const open = Number(candle.open);
            const close = Number(candle.close);
            const high = Number(candle.high);
            const low = Number(candle.low);
            const x = chartPadding + chart.slot * index + chart.slot / 2;
            const bodyTop = chart.y(Math.max(open, close));
            const bodyBottom = chart.y(Math.min(open, close));
            const bodyHeight = Math.max(2, bodyBottom - bodyTop);
            const rising = close >= open;
            return (
              <g key={`${candle.open_time}-${index}`} className={rising ? "candle rising" : "candle falling"}>
                <line x1={x} x2={x} y1={chart.y(high)} y2={chart.y(low)} />
                <rect x={x - Math.max(2, chart.slot * 0.28)} y={bodyTop} width={Math.max(4, chart.slot * 0.56)} height={bodyHeight} rx="1" />
              </g>
            );
          })}
        </svg>
        <div className="chart-scale"><span>{chart.highest.toLocaleString()}</span><span>{chart.lowest.toLocaleString()}</span></div>
      </div>
      <p className="panel-note">Recorded closed candles from the backend fixture. No indicators or live order signal are derived here.</p>
    </div>
  );
}
