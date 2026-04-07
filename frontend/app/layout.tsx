import type { Metadata } from "next";
import { Analytics } from "@vercel/analytics/react";
import { ThemeProvider } from "next-themes";
import "@/index.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://unagieel.net"),
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
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <meta
          name="theme-color"
          media="(prefers-color-scheme: dark)"
          content="#060e1f"
        />
        <meta
          name="theme-color"
          media="(prefers-color-scheme: light)"
          content="#f8fafc"
        />
      </head>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
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
