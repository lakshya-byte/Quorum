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
    "PatchLoop reads a failing test, reasons about the cause, writes a fix, and runs it in a sandbox until the test actually passes. Not a suggestion. A proof.",
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
