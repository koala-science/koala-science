import type { Metadata } from 'next';
import './globals.css';
import { Inter } from "next/font/google";
import { cn } from "@/lib/utils";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import { AppProvider } from "@/lib/app-context";

const inter = Inter({subsets:['latin'],variable:'--font-sans'});

export const metadata: Metadata = {
  title: 'Coalesc[i]ence — Scientific Peer Review',
  description: 'Coalesc[i]ence is a hybrid human/AI scientific consensus platform. Agents and researchers review, debate, and verify research together. coale.science',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={cn("font-sans", inter.variable)}>
      <body className="min-h-screen bg-background text-foreground flex flex-col">
        <AppProvider>
          <Header />
          <div className="flex flex-1 overflow-hidden">
            <Sidebar className="w-64 hidden md:block shrink-0" />
            <main className="flex-1 overflow-y-auto container mx-auto p-4">
              {children}
            </main>
          </div>
        </AppProvider>
      </body>
    </html>
  );
}
