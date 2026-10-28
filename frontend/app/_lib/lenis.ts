import type Lenis from "lenis";

let instance: Lenis | null = null;

export function setLenis(lenis: Lenis | null) {
  instance = lenis;
}

export function getLenis() {
  return instance;
}

export function smoothScrollTo(target: string | HTMLElement) {
  const lenis = getLenis();
  if (lenis) {
    lenis.scrollTo(target, { duration: 1.1 });
  } else {
    const el = typeof target === "string" ? document.querySelector(target) : target;
    el?.scrollIntoView({ behavior: "smooth" });
  }
}
