import type { Metadata } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
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
  title: { default: "PatchLoop: bug fixes proven by your tests", template: "%s | PatchLoop" },
  description:
    "Describe a bug. A team of AI agents reads your repo, proposes fixes in parallel sandboxes, and opens a pull request only when your tests pass. A human reviews and merges.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <ClerkProvider signInUrl="/signin" signUpUrl="/signup" signInFallbackRedirectUrl="/dashboard" signUpFallbackRedirectUrl="/dashboard">
    <html
      lang="en"
      className={`${geistSans.variable} ${jetbrainsMono.variable} h-full dark`}
    >
      <body className="min-h-full flex flex-col bg-bg text-on-surface antialiased selection:bg-primary/20 selection:text-primary">
        {children}
      </body>
    </html>
    </ClerkProvider>
  );
}
