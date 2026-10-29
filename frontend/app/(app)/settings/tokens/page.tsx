import type { Metadata } from "next";
import TokensClient from "./TokensClient";

export const metadata: Metadata = { title: "API tokens — PatchLoop" };

export default function TokensPage() {
  return <TokensClient />;
}
