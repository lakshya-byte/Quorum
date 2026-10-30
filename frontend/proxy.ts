import { NextResponse } from "next/server";
import { clerkMiddleware } from "@clerk/nextjs/server";

// Runs Clerk on every page; route guarding stays client-side (RequireAuth),
// and the Go API verifies the session token itself.
// NEXT_PUBLIC_MOCK_AUTH=1 (offline mock-backend e2e builds only) skips Clerk entirely.
export default process.env.NEXT_PUBLIC_MOCK_AUTH === "1" ? () => NextResponse.next() : clerkMiddleware();

export const config = {
  matcher: [
    // Skip Next internals and static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
