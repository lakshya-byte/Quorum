import type { Metadata } from "next";
import RunClient from "./RunClient";

export const metadata: Metadata = { title: "Run" };

export default async function RunPage({ params }: PageProps<"/runs/[id]">) {
  const { id } = await params;
  return <RunClient id={id} />;
}
