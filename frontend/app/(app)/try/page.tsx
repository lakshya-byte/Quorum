import type { Metadata } from "next";
import TryClient from "./TryClient";

export const metadata: Metadata = {
  title: "Try PatchLoop — live demo",
  description: "Pick a bug and watch an agent team propose fixes in parallel sandboxes. Tests decide what is good.",
};

export default function TryPage() {
  return <TryClient />;
}
