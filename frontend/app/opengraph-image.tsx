import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Unagi — ML-powered Swedish electricity price forecast";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OgImage() {
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        width: "100%",
        height: "100%",
        background:
          "linear-gradient(135deg, #030712 0%, #0a1628 50%, #030712 100%)",
        fontFamily: "system-ui, sans-serif",
        color: "#f9fafb",
        padding: "60px 80px",
      }}
    >
      {/* Title */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: "16px",
        }}
      >
        <span style={{ fontSize: 80, fontWeight: 800, letterSpacing: "-2px" }}>
          Unagi
        </span>
        <span style={{ fontSize: 48, color: "#22d3ee", fontWeight: 300 }}>
          eel
        </span>
      </div>

      {/* Tagline */}
      <p
        style={{
          fontSize: 28,
          color: "#9ca3af",
          marginTop: 16,
          fontWeight: 400,
        }}
      >
        Swedish Electricity Price Forecast
      </p>

      {/* Separator */}
      <div
        style={{
          display: "flex",
          width: 120,
          height: 2,
          background:
            "linear-gradient(90deg, transparent, #22d3ee, transparent)",
          marginTop: 32,
          marginBottom: 32,
        }}
      />

      {/* Features */}
      <div
        style={{
          display: "flex",
          gap: "40px",
          fontSize: 20,
          color: "#6b7280",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ color: "#22d3ee" }}>7-day</span> ML forecast
        </span>
        <span style={{ color: "#374151" }}>|</span>
        <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          Published
          <span style={{ color: "#22d3ee" }}>accuracy</span>
        </span>
        <span style={{ color: "#374151" }}>|</span>
        <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ color: "#22d3ee" }}>Open</span> source
        </span>
      </div>

      {/* URL */}
      <p
        style={{
          fontSize: 18,
          color: "#374151",
          marginTop: 40,
          letterSpacing: "1px",
        }}
      >
        unagieel.net
      </p>
    </div>,
    { ...size },
  );
}
