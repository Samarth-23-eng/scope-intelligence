import type { Metadata, Viewport } from "next";
import { AppShell } from "@/components/AppShell";
import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Scope Intelligence",
    template: "%s | Scope Intelligence",
  },
  description: "Private company intelligence and evidence research workspace.",
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#080a0e",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body>
        <a className="skip-link" href="#main-content">Skip to Main Content</a>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
