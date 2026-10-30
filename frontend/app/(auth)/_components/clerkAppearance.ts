import type { ComponentProps } from "react";
import type { SignIn } from "@clerk/nextjs";

export const clerkAppearance: ComponentProps<typeof SignIn>["appearance"] = {
  variables: {
    colorPrimary: "#10b981",
    colorBackground: "transparent",
    colorForeground: "#ffffff",
    colorMutedForeground: "#9ca3af",
    colorInput: "rgba(255,255,255,0.04)",
    colorInputForeground: "#ffffff",
    colorNeutral: "#ffffff",
  },
  elements: {
    rootBox: "w-full",
    cardBox: "w-full shadow-none",
    card: "bg-transparent shadow-none border-0 p-0 w-full",
    footer: "bg-transparent",
  },
};
