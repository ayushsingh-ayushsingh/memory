import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Roboto, Roboto_Serif, Roboto_Mono } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { cn } from "@/lib/utils";
import { TooltipProvider } from "@cloudflare/kumo";

const sans = Roboto({
  variable: "--font-sans",
  subsets: ["latin"],
});

const serif = Roboto_Serif({
  variable: "--font-serif",
  subsets: ["latin"],
});

const mono = Roboto_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Kumo UI showcase",
  description:
    "A living dashboard built entirely from @cloudflare/kumo. Every page is interactive and persists to local storage.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      data-theme="fedramp"
      className={cn(
        "h-full",
        "antialiased",
        "font-mono",
        sans.variable,
        serif.variable,
        mono.variable,
      )}
      suppressHydrationWarning
    >
      <body className="bg-kumo-canvas">
        <ThemeProvider
          attribute="data-mode"
          defaultTheme="system"
          enableSystem
          enableColorScheme
          disableTransitionOnChange
        >
          <TooltipProvider>{children}</TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
