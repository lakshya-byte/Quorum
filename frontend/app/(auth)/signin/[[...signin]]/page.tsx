import type { Metadata } from "next";
import SignInCard from "../../_components/SignInCard";

export const metadata: Metadata = {
  title: "Sign In — PatchLoop",
};

export default function SignInPage() {
  return <SignInCard />;
}
