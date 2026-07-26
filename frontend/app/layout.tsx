import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "DeckForge",
  description: "A local-first, agentic presentation workspace.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
    { media: "(prefers-color-scheme: dark)", color: "#0c0e12" },
  ],
};

/** Applies the stored colour scheme before first paint to avoid a flash. */
const THEME_BOOTSTRAP = `
(function () {
  try {
    var stored = localStorage.getItem("deckforge-appearance");
    var dark = stored ? stored === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="h-full overflow-hidden">{children}</body>
    </html>
  );
}
