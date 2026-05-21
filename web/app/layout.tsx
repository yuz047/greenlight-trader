import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "GreenLight Trader — Sirius Zhang",
  description: "Adaptive $5,000 paper-trading allocation dashboard.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Inter+Tight:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen">
        <header className="site-header">
          <div className="container">
            <nav className="nav" aria-label="Primary">
              <a className="brand" href="https://yuz047.github.io/index.html">Sirius Zhang</a>
              <div className="nav-links">
                <a href="https://yuz047.github.io/work.html">Work</a>
                <a href="https://yuz047.github.io/writing.html">Writing</a>
                <a href="https://yuz047.github.io/cv.html">CV</a>
                <a className="is-current" href="/">Trader</a>
                <a href="https://yuz047.github.io/contact.html">Contact</a>
              </div>
            </nav>
          </div>
        </header>

        {children}

        <footer className="site-footer">
          <div className="container">
            <div className="row">
              <span>&copy; 2026 Yunhan &ldquo;Sirius&rdquo; Zhang</span>
              <span>Trading &middot; Risk &middot; AI &middot; Data</span>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
