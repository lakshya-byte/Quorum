import { clerkMiddleware } from "@clerk/nextjs/server";

// Runs Clerk on every page; route guarding stays client-side (RequireAuth),
// and the Go API verifies the session token itself.
export default clerkMiddleware();

export const config = {
  matcher: [
    // Skip Next internals and static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
