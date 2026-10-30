import type { Metadata } from "next";
import NewClient from "./NewClient";

export const metadata: Metadata = { title: "New task" };

export default function NewPage() {
  return <NewClient />;
}
