import type { NextConfig } from "next";
import createMDX from "@next/mdx";

const nextConfig: NextConfig = {
  pageExtensions: ["ts", "tsx", "mdx"],
};

const withMDX = createMDX({
  options: {
    // Passed as a module specifier (not an imported function) so Turbopack
    // can serialize the loader options across the Rust/JS boundary.
    remarkPlugins: ["remark-gfm"],
  },
});

export default withMDX(nextConfig);
