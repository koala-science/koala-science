import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';
import { cn } from "@/lib/utils";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
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
    <html lang="en" className={cn("font-sans", geistSans.variable, geistMono.variable)}>
      <body className="min-h-screen bg-background text-foreground flex flex-col">
        <AppProvider>
          <Header />
          <div className="flex flex-1 overflow-hidden">
            <Sidebar className="w-64 hidden md:block shrink-0" />
            <main className="flex-1 overflow-y-auto container mx-auto p-4 md:p-6">
              {children}
            </main>
          </div>
        </AppProvider>
      </body>
    </html>
  );
}
