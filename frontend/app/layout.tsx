import type { Metadata } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";
import SmoothScroll from "./_components/SmoothScroll";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "PatchLoop — bugs fixed, proven, before you see them",
  description:
    "A team of AI agents proposes bug fixes in parallel, each tested in an isolated Nebius Sandbox. The tests decide, guardrails check every step, and a human merges the pull request.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${jetbrainsMono.variable} h-full dark`}
    >
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full flex flex-col bg-bg text-on-surface antialiased selection:bg-primary/20 selection:text-primary">
        <SmoothScroll />
        {children}
      </body>
    </html>
  );
}
