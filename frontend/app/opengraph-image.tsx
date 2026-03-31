import { ImageResponse } from "next/og";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const alt = "Unagi — ML-powered Swedish electricity price forecast";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Stylized price curve points (decorative, not real data)
const CHART_POINTS = [
  0.32, 0.28, 0.25, 0.22, 0.2, 0.19, 0.21, 0.3, 0.52, 0.65, 0.72, 0.78, 0.8,
  0.76, 0.7, 0.62, 0.68, 0.82, 0.88, 0.75, 0.58, 0.45, 0.38, 0.34,
];

function chartPath(): { fill: string; line: string } {
  const w = 1200;
  const h = 160;
  const yBase = 630;
  const padX = 80;
  const plotW = w - padX * 2;
  const min = Math.min(...CHART_POINTS);
  const max = Math.max(...CHART_POINTS);

  const pts = CHART_POINTS.map((v, i) => ({
    x: padX + (i / (CHART_POINTS.length - 1)) * plotW,
    y: yBase - 10 - ((v - min) / (max - min)) * (h - 20),
  }));

  // Build smooth cubic bezier path (Catmull-Rom → Bezier conversion)
  const tension = 0.3;
  let line = `M${pts[0].x},${pts[0].y}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(i - 1, 0)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(i + 2, pts.length - 1)];
    const cp1x = p1.x + (p2.x - p0.x) * tension;
    const cp1y = p1.y + (p2.y - p0.y) * tension;
    const cp2x = p2.x - (p3.x - p1.x) * tension;
    const cp2y = p2.y - (p3.y - p1.y) * tension;
    line += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2.x},${p2.y}`;
  }

  const last = pts[pts.length - 1];
  const fill = `${line} L${last.x},${yBase} L${pts[0].x},${yBase} Z`;
  return { fill, line };
}

export default async function OgImage() {
  const logoBuffer = await readFile(
    join(process.cwd(), "public", "logo", "unagi_log.png"),
  );
  const logoBase64 = `data:image/png;base64,${Buffer.from(logoBuffer).toString("base64")}`;

  return new ImageResponse(
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        width: "100%",
        height: "100%",
        background:
          "linear-gradient(170deg, #030712 0%, #0a1628 40%, #071320 100%)",
        fontFamily: "system-ui, sans-serif",
        color: "#f9fafb",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Chart area fill (decorative) */}
      <svg
        width="1200"
        height="630"
        viewBox="0 0 1200 630"
        style={{ position: "absolute", top: 0, left: 0 }}
      >
        <defs>
          <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="chartLine" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.3" />
            <stop offset="50%" stopColor="#22d3ee" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.3" />
          </linearGradient>
        </defs>
        <path d={chartPath().fill} fill="url(#chartFill)" />
        <path
          d={chartPath().line}
          fill="none"
          stroke="url(#chartLine)"
          strokeWidth="2.5"
        />
        {/* Grid lines */}
        {[0.25, 0.5, 0.75].map((pct) => (
          <line
            key={pct}
            x1="80"
            y1={630 - 30 - pct * 240}
            x2="1120"
            y2={630 - 30 - pct * 240}
            stroke="#1e3a5f"
            strokeWidth="0.5"
            strokeDasharray="6 4"
          />
        ))}
      </svg>

      {/* Content layer */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          padding: "60px 80px",
          position: "relative",
          flex: 1,
        }}
      >
        {/* Logo + Title row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "20px",
          }}
        >
          <img src={logoBase64} style={{ width: 180, height: 96 }} />
        </div>

        {/* Tagline */}
        <p
          style={{
            fontSize: 32,
            color: "#d1d5db",
            marginTop: 24,
            fontWeight: 400,
            letterSpacing: "-0.5px",
          }}
        >
          Swedish Electricity Price Forecast
        </p>

        {/* Feature pills */}
        <div
          style={{
            display: "flex",
            gap: "16px",
            marginTop: 32,
          }}
        >
          {["7-day ML forecast", "Published accuracy", "Open source"].map(
            (label) => (
              <div
                key={label}
                style={{
                  display: "flex",
                  padding: "8px 20px",
                  borderRadius: "24px",
                  border: "1px solid rgba(34, 211, 238, 0.25)",
                  background: "rgba(34, 211, 238, 0.06)",
                  fontSize: 18,
                  color: "#94a3b8",
                }}
              >
                {label}
              </div>
            ),
          )}
        </div>

        {/* URL */}
        <p
          style={{
            fontSize: 18,
            color: "#475569",
            marginTop: 28,
            letterSpacing: "1.5px",
          }}
        >
          unagieel.net
        </p>
      </div>
    </div>,
    { ...size },
  );
}
