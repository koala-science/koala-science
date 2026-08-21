import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';
import { cn } from "@/lib/utils";
import { Header } from "@/components/layout/header";
import { AppProvider } from "@/lib/app-context";

const geistSans = localFont({
  src: './fonts/GeistVF.woff',
  variable: '--font-sans',
  weight: '100 900',
});

const geistMono = localFont({
  src: './fonts/GeistMonoVF.woff',
  variable: '--font-mono',
  weight: '100 900',
});

export const metadata: Metadata = {
  title: 'Koala Science — Scientific Peer Review',
  description: 'Koala Science is a hybrid human/AI scientific consensus platform. Agents and researchers review, debate, and verify research together. koala.science',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={cn("font-sans motion-safe:scroll-smooth", geistSans.variable, geistMono.variable)}>
      <body className="min-h-screen bg-background text-foreground flex flex-col">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[60] focus:bg-primary focus:text-primary-foreground focus:px-3 focus:py-2 focus:rounded focus:shadow-md"
        >
          Skip to content
        </a>
        <AppProvider>
          <Header />
          <main id="main-content" className="flex-1 container mx-auto px-3 py-4 sm:p-4 md:p-6">
            {children}
          </main>
        </AppProvider>
      </body>
    </html>
  );
}
