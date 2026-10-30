import type { Metadata } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { MOCK_AUTH } from "./_lib/api";
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
  title: { default: "PatchLoop: engineering tasks, verified by its own checks", template: "%s | PatchLoop" },
  description:
    "Describe a bug, a feature, a refactor or a UI change. PatchLoop spawns a swarm sized to the task, runs it all in sandboxes, and opens a pull request only when its own checks pass. You merge.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  const page = (
    <html
      lang="en"
      className={`${geistSans.variable} ${jetbrainsMono.variable} h-full dark`}
    >
      <body className="min-h-full flex flex-col bg-bg text-on-surface antialiased selection:bg-primary/20 selection:text-primary">
        {children}
      </body>
    </html>
  );
  // MOCK_AUTH is only set for offline mock-backend builds (e2e); production always runs under Clerk.
  if (MOCK_AUTH) return page;
  return (
    <ClerkProvider signInUrl="/signin" signUpUrl="/signup" signInFallbackRedirectUrl="/dashboard" signUpFallbackRedirectUrl="/dashboard">
      {page}
    </ClerkProvider>
  );
}
