import type { Metadata } from "next";
import { Playfair_Display, Syne, JetBrains_Mono } from "next/font/google";
import { Navbar } from "@/components/layout/Navbar";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import "./globals.css";

const websiteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "SteamPulse",
  url: "https://steampulse.io",
  description: "Player intelligence across 100,000+ Steam games — sentiment, trends, and competitive insights.",
  potentialAction: {
    "@type": "SearchAction",
    target: {
      "@type": "EntryPoint",
      urlTemplate: "https://steampulse.io/search?q={search_term_string}",
    },
    "query-input": "required name=search_term_string",
  },
};

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "SteamPulse",
  url: "https://steampulse.io",
  description:
    "AI-powered Steam game intelligence — synthesised review reports, audience overlap, and genre insights for the Steam catalog.",
  sameAs: ["https://twitter.com/steampulse"],
};

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  display: "swap",
});

const syne = Syne({
  variable: "--font-syne",
  subsets: ["latin"],
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "SteamPulse — Steam Game Intelligence",
    template: "%s | SteamPulse",
  },
  description:
    "Player intelligence across 100,000+ Steam games. Sentiment analysis, competitive insights, market trends, and deep review reports — for gamers and game makers.",
  metadataBase: new URL("https://steampulse.io"),
  openGraph: {
    siteName: "SteamPulse",
    type: "website",
    locale: "en_US",
    title: "SteamPulse — Steam Game Intelligence",
    description:
      "What players really think about every Steam game. Sentiment, trends, and competitive intelligence.",
    url: "https://steampulse.io",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "SteamPulse — Steam Game Intelligence",
    description:
      "What players really think about every Steam game. Sentiment, trends, and competitive intelligence.",
    images: ["/og-default.png"],
    creator: "@steampulse",
  },
  alternates: {
    canonical: "https://steampulse.io",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${playfair.variable} ${syne.variable} ${jetbrains.variable}`}
    >
      <body className="antialiased min-h-screen bg-background text-foreground">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteJsonLd) }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(organizationJsonLd) }}
        />
        <NuqsAdapter>
          <Navbar />
          {children}
        </NuqsAdapter>
      </body>
    </html>
  );
}
