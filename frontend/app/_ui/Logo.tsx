import Link from "next/link";

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" src="/patchloop-logo.svg" width={size} height={size} style={{ width: size, height: size }} />
  );
}

export function Logo({ href = "/", className = "" }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={`focus-ring inline-flex items-center gap-2.5 rounded-md ${className}`} aria-label="PatchLoop home">
      <LogoMark />
      <span className="text-[16px] font-semibold tracking-tight text-white">PatchLoop</span>
    </Link>
  );
}
