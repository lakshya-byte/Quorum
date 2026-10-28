import type { Metadata } from "next";
import SignUpCard from "../_components/SignUpCard";

export const metadata: Metadata = {
  title: "Sign Up — PatchLoop",
};

export default function SignUpPage() {
  return <SignUpCard />;
}
