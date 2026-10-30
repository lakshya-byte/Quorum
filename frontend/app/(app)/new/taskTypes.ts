import type { TaskType } from "../../_lib/api";
import type { IconName } from "../../_ui";

export type TypeInfo = {
  id: TaskType;
  label: string;
  icon: IconName;
  /** One honest line: what actually decides success for this kind of task. */
  how: string;
  examples: string[];
  placeholder: string;
};

export const TASK_TYPES: TypeInfo[] = [
  {
    id: "auto",
    label: "Auto",
    icon: "sparkles",
    how: "PatchLoop picks the type from your description, then writes the checks for it. If the description is too vague to plan, it asks you questions instead of guessing.",
    examples: ["Improve the UI of this React app", "Add bulk discount tiers", "Split the monolithic module, keep the public API"],
    placeholder: "e.g. Improve the UI of this React app",
  },
  {
    id: "bugfix",
    label: "Bug fix",
    icon: "bug",
    how: "A reproducer test is written first and must fail on the original code and pass now. Your existing tests must keep passing.",
    examples: [
      "Checkout totals are wrong when a percentage coupon is used: the discount also reduces shipping and rounds down.",
      "Word counts are wrong: 'The' and 'the' are counted separately and contractions like don't are split in two.",
      "Back-to-back bookings are rejected as conflicts: booking 10-11 right after 9-10 raises ConflictError.",
    ],
    placeholder: "e.g. Pagination returns the wrong last page when the item count is an exact multiple of the page size.",
  },
  {
    id: "feature",
    label: "Feature",
    icon: "plus",
    how: "Acceptance tests are written from your description before any code. They must fail on the original and pass now, and nothing that passed may break.",
    examples: ["Add bulk discount tiers", "Add CSV export to the report command", "Support percentage and fixed-amount coupons"],
    placeholder: "e.g. Add bulk discount tiers: 10+ items 5%, 50+ items 10%.",
  },
  {
    id: "refactor",
    label: "Refactor",
    icon: "split",
    how: "Characterization tests are generated against the original code and must pass before and after. The public API surface must not change, lint no worse, and any size target you state is measured.",
    examples: ["Split the monolithic module, keep the public API", "Extract the pricing rules into their own module", "Remove the duplicated parsing code"],
    placeholder: "e.g. Split the monolithic module, keep the public API.",
  },
  {
    id: "ui",
    label: "UI/UX",
    icon: "panel",
    how: "Build passes, no console errors, no horizontal overflow at 375/768/1280 px, no new axe violations, and a key-flow script passes before and after. How good it looks is a model's opinion: advisory only.",
    examples: ["Improve the UI of this React app", "Make the todo list usable on a phone", "Add visible focus styles and labels to the form"],
    placeholder: "e.g. Improve the UI of this React app.",
  },
  {
    id: "tests",
    label: "Tests",
    icon: "flask",
    how: "The planner writes at least one executable check, for example that the new tests run and pass on the original code. No existing test may be edited. Otherwise the result is marked Partial.",
    examples: ["Add tests for the coupon rounding rules", "Raise coverage of the booking module"],
    placeholder: "e.g. Add tests for the coupon rounding rules.",
  },
  {
    id: "perf",
    label: "Performance",
    icon: "gauge",
    how: "A benchmark script with a threshold is synthesized and must pass, and behavior tests must not regress. Timings from a shared sandbox are noisy, so the threshold is set conservatively.",
    examples: ["Speed up word counting on large inputs", "Cut the list endpoint's query count"],
    placeholder: "e.g. Speed up word counting on large inputs.",
  },
  {
    id: "deps",
    label: "Dependencies",
    icon: "layers",
    how: "Install and build succeed with the new versions, existing tests pass, and the audit or lockfile check is no worse than before.",
    examples: ["Upgrade React to the latest minor", "Replace the unmaintained date library"],
    placeholder: "e.g. Upgrade React to the latest minor version.",
  },
  {
    id: "docs",
    label: "Docs",
    icon: "book",
    how: "Build and the link checker must pass. Whether the writing reads well cannot be proven by code, so that part is advisory and the result is marked Partial.",
    examples: ["Write a migration guide for the new API", "Document the environment variables"],
    placeholder: "e.g. Document the environment variables.",
  },
  {
    id: "other",
    label: "Other",
    icon: "code",
    how: "The planner proposes at least one executable check. If none can exist, only build, no-regression, policy and security gates apply and the result is Partial, with the PR saying what was not verified.",
    examples: ["Add a health-check script and wire it into the README", "Rename the config keys and update every use"],
    placeholder: "Describe the change you want.",
  },
];

export const TYPE_BY_ID: Record<string, TypeInfo> = Object.fromEntries(TASK_TYPES.map((t) => [t.id, t]));
