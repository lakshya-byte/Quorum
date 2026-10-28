import type { MDXComponents } from "mdx/types";
import Link from "next/link";

export function useMDXComponents(components: MDXComponents): MDXComponents {
  return {
    h1: (props) => (
      <h1
        className="text-3xl sm:text-4xl font-semibold tracking-tight text-white mt-0 mb-4"
        {...props}
      />
    ),
    h2: (props) => (
      <h2
        className="text-xl sm:text-2xl font-semibold tracking-tight text-white mt-12 mb-4 pt-6 border-t border-outline-variant/50 first:mt-0 first:pt-0 first:border-t-0"
        {...props}
      />
    ),
    h3: (props) => (
      <h3
        className="text-base sm:text-lg font-semibold text-white mt-8 mb-3"
        {...props}
      />
    ),
    p: (props) => (
      <p className="text-[15px] leading-relaxed text-on-surface-variant mb-4" {...props} />
    ),
    a: ({ href, ...props }) => {
      const isInternal = href?.startsWith("/") || href?.startsWith("#");
      if (isInternal && href) {
        return (
          <Link
            href={href}
            className="text-primary hover:text-primary/80 underline underline-offset-2 transition-colors"
            {...props}
          />
        );
      }
      return (
        <a
          href={href}
          className="text-primary hover:text-primary/80 underline underline-offset-2 transition-colors"
          target="_blank"
          rel="noopener noreferrer"
          {...props}
        />
      );
    },
    ul: (props) => (
      <ul className="list-disc list-outside pl-5 space-y-1.5 text-[15px] text-on-surface-variant mb-4" {...props} />
    ),
    ol: (props) => (
      <ol className="list-decimal list-outside pl-5 space-y-1.5 text-[15px] text-on-surface-variant mb-4" {...props} />
    ),
    li: (props) => <li className="leading-relaxed marker:text-primary/60" {...props} />,
    strong: (props) => <strong className="text-on-surface font-semibold" {...props} />,
    blockquote: (props) => (
      <blockquote
        className="border-l-2 border-primary/40 pl-4 py-0.5 my-4 text-on-surface-variant italic"
        {...props}
      />
    ),
    hr: (props) => <hr className="border-outline-variant/50 my-8" {...props} />,
    code: (props) => (
      <code
        className="font-mono text-[13px] text-primary bg-surface-container px-1.5 py-0.5 rounded"
        {...props}
      />
    ),
    pre: (props) => (
      <pre
        className="font-mono text-[13px] leading-relaxed bg-surface-container-lowest border border-outline-variant/60 rounded-lg p-4 overflow-x-auto mb-5 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-on-surface"
        {...props}
      />
    ),
    table: (props) => (
      <div className="overflow-x-auto mb-6 rounded-lg border border-outline-variant/60">
        <table className="w-full text-left text-[13px] border-collapse" {...props} />
      </div>
    ),
    thead: (props) => <thead className="bg-surface-container-low" {...props} />,
    th: (props) => (
      <th
        className="px-3.5 py-2.5 font-mono text-[11px] uppercase tracking-wide text-on-surface-variant border-b border-outline-variant/60"
        {...props}
      />
    ),
    td: (props) => (
      <td
        className="px-3.5 py-2.5 text-on-surface-variant border-b border-outline-variant/30 align-top"
        {...props}
      />
    ),
    ...components,
  };
}
