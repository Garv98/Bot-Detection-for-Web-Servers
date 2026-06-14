import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ToastProvider } from "@/components/Toast";
import { CommandPalette } from "@/components/CommandPalette";
import { PageTransition } from "@/components/motion";

export const metadata: Metadata = {
  title: "BotSentry — Web Robot Detection",
  description:
    "Real-time bot detection over 4M+ access logs: Spark ETL, ML scoring, HBase, FastAPI.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <script dangerouslySetInnerHTML={{ __html: "try{if(localStorage.getItem('botsentry-theme')==='dark')document.documentElement.setAttribute('data-theme','dark');}catch(e){}" }} />
      </head>
      <body>
        <ToastProvider>
          <CommandPalette />
          <div style={{ display: "flex", minHeight: "100vh" }}>
            <Sidebar />
            <main style={{ flex: 1, minWidth: 0, padding: "28px 32px", maxWidth: 1680, marginInline: "auto", width: "100%" }}>
              <ErrorBoundary>
                <PageTransition>{children}</PageTransition>
              </ErrorBoundary>
            </main>
          </div>
        </ToastProvider>
      </body>
    </html>
  );
}
