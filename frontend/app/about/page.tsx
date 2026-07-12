import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About — Unagi",
  description:
    "What Unagi predicts, how accurate it is, the method behind it, and where its data comes from.",
};

const GITHUB = "https://github.com/mugime-shi/Unagi";
const CONTACT = "hello@unagieel.net";

const DATA_SOURCES: { name: string; provides: string }[] = [
  {
    name: "ENTSO-E",
    provides:
      "Generation mix, cross-border flows and hydro reservoir levels for SE1–SE4.",
  },
  {
    name: "SMHI / Open-Meteo",
    provides: "Wind, temperature and solar/radiation — forecasts and history.",
  },
  { name: "eSett", provides: "Nordic imbalance settlement prices." },
  {
    name: "Riksbank",
    provides: "EUR/SEK reference rates for converting market data.",
  },
  {
    name: "Skatteverket",
    provides: "Electricity tax and VAT (moms) rates for the cost breakdown.",
  },
  {
    name: "Energimarknadsinspektionen (Ei)",
    provides: "Network-tariff and retailer reference data.",
  },
];

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <h2 className="text-base font-medium text-content-primary">{title}</h2>
      <div className="text-sm text-content-secondary leading-relaxed space-y-2">
        {children}
      </div>
    </section>
  );
}

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-surface-page text-content-primary">
      <main className="w-full max-w-2xl mx-auto px-4 py-8 space-y-8">
        <div className="space-y-1">
          <Link
            href="/"
            className="text-xs text-content-muted underline hover:text-content-secondary transition-colors"
          >
            ← Back to Unagi
          </Link>
          <h1 className="text-2xl font-semibold text-content-primary pt-2">
            About Unagi
          </h1>
          <p className="text-sm text-content-secondary leading-relaxed">
            Unagi is a free, open-source dashboard that forecasts day-ahead
            electricity prices for Sweden and publishes how accurate those
            forecasts turn out to be. It reads public data and translates it
            into one readable view — nothing here is behind a login.
          </p>
        </div>

        <Section title="What we predict">
          <ul className="list-disc pl-5 space-y-1">
            <li>All four Swedish bidding zones: SE1, SE2, SE3, SE4.</li>
            <li>
              Daily-average and hourly prices from tomorrow out to seven days
              ahead (d+1 to d+7).
            </li>
            <li>An 80% prediction interval around each forecast.</li>
          </ul>
        </Section>

        <Section title="Accuracy">
          <p>
            We publish our accuracy live rather than describe it. For each zone
            we show the trailing 28-day mean absolute error (MAE) next to a
            same-weekday-average baseline, and how often the actual price landed
            inside the 80% interval.
          </p>
          <p>
            These numbers are visible on the{" "}
            <Link
              href="/"
              className="underline hover:text-content-primary transition-colors"
            >
              forecast itself
            </Link>
            , so the forecast and its track record sit side by side.
          </p>
        </Section>

        <Section title="Method">
          <p>
            Prices are predicted with LightGBM (gradient-boosted trees),
            retrained daily on recent history in a walk-forward setup. The 80%
            interval comes from conformalized quantile regression (CQR).
            Horizons beyond d+1 are produced recursively.
          </p>
          <p>
            Main inputs: forecast demand, wind and weather, hydro reservoir
            levels, German (DE) day-ahead prices, calendar effects, nuclear
            availability and recent price history.
          </p>
          <p>
            Everything is open source on{" "}
            <a
              href={GITHUB}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary transition-colors"
            >
              GitHub
            </a>
            .
          </p>
        </Section>

        <Section title="Data sources">
          <ul className="space-y-1.5">
            {DATA_SOURCES.map((s) => (
              <li key={s.name}>
                <span className="text-content-primary font-medium">
                  {s.name}
                </span>{" "}
                — {s.provides}
              </li>
            ))}
          </ul>
        </Section>

        <Section title="Public API & MCP">
          <p>
            A public API and an MCP server (for asking Unagi questions from an
            AI assistant) are planned but not released yet. If you have a
            concrete use case — a Home Assistant sensor, a research project —
            email{" "}
            <a
              href={`mailto:${CONTACT}`}
              className="underline hover:text-content-primary transition-colors"
            >
              {CONTACT}
            </a>{" "}
            and tell us what you need.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions, corrections or data-source suggestions are welcome at{" "}
            <a
              href={`mailto:${CONTACT}`}
              className="underline hover:text-content-primary transition-colors"
            >
              {CONTACT}
            </a>
            , or open an issue on{" "}
            <a
              href={GITHUB}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-content-primary transition-colors"
            >
              GitHub
            </a>
            .
          </p>
        </Section>
      </main>
    </div>
  );
}
