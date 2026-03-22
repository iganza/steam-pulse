import type { Metadata } from "next";
import { Playfair_Display, Syne, JetBrains_Mono } from "next/font/google";
import { Navbar } from "@/components/layout/Navbar";
import "./globals.css";

const websiteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "SteamPulse",
  url: "https://steampulse.io",
  description: "Deep review intelligence for Steam games.",
  potentialAction: {
    "@type": "SearchAction",
    target: {
      "@type": "EntryPoint",
      urlTemplate: "https://steampulse.io/search?q={search_term_string}",
    },
    "query-input": "required name=search_term_string",
  },
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
    default: "SteamPulse: Steam Game Intelligence",
    template: "%s | SteamPulse",
  },
  description:
    "Deep review intelligence for Steam games. Discover what players love, hate, and want next.",
  metadataBase: new URL("https://steampulse.io"),
  openGraph: {
    siteName: "SteamPulse",
    type: "website",
    locale: "en_US",
    title: "SteamPulse: Steam Game Intelligence",
    description:
      "Deep review intelligence for Steam games. Discover what players love, hate, and want next.",
    url: "https://steampulse.io",
    images: [{ url: "/og-default.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "SteamPulse: Steam Game Intelligence",
    description:
      "Deep review intelligence for Steam games. Discover what players love, hate, and want next.",
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
        <Navbar />
        {children}
      </body>
    </html>
  );
}
