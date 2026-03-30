import type { Metadata } from "next";
import { Analytics } from "@vercel/analytics/react";
import "@/index.css";

export const metadata: Metadata = {
  title: "Unagi — Swedish Electricity Price Forecast",
  description:
    "ML-powered 7-day electricity price forecast for Sweden (SE1–SE4). Free, open source, with published prediction accuracy.",
  openGraph: {
    title: "Unagi — Swedish Electricity Price Forecast",
    description:
      "The only Swedish electricity tool that publishes its own prediction accuracy.",
    url: "https://unagieel.net",
    siteName: "Unagi",
    type: "website",
    locale: "en_SE",
  },
  twitter: {
    card: "summary_large_image",
  },
  icons: {
    icon: "/logo/favicon.png",
  },
  manifest: "/manifest.json",
  other: {
    "theme-color": "#030712",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        {children}
        <Analytics />
        <ServiceWorkerRegistrar />
      </body>
    </html>
  );
}

/** Register service worker for Web Push — client-side only */
function ServiceWorkerRegistrar() {
  return (
    <script
      dangerouslySetInnerHTML={{
        __html: `
          if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js').catch(console.error);
          }
        `,
      }}
    />
  );
}
