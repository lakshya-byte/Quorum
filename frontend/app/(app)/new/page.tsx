import type { Metadata } from "next";
import NewClient from "./NewClient";

export const metadata: Metadata = { title: "Fix a bug" };

export default function NewPage() {
  return <NewClient />;
}
