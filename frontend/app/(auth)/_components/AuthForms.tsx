"use client";

import { Icon } from "../../_ui";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { ApiError, authApi, errorMessage } from "../../_lib/api";

const INPUT =
  "block w-full pl-10 pr-3.5 py-2.5 text-sm rounded-lg text-white placeholder-on-surface-variant/70 bg-surface-container-lowest/65 border border-white/[0.07] transition-all duration-200 focus:outline-none focus:border-primary/60 focus:bg-surface-container-lowest/95 focus:shadow-[0_0_0_2px_rgba(16,185,129,0.18),0_0_16px_-2px_rgba(16,185,129,0.25)] hover:border-white/[0.14]";

const PRIMARY =
  "w-full rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-black shadow-[0_0_20px_rgba(16,185,129,0.25)] hover:bg-[#34d399] transition-all duration-200 active:scale-[0.99] disabled:opacity-60 flex items-center justify-center gap-2";

/** Where to go after signing in: ?next=/path (same-origin paths only). */
function nextPath(): string {
  if (typeof window === "undefined") return "/dashboard";
  const n = new URLSearchParams(window.location.search).get("next");
  return n && n.startsWith("/") && !n.startsWith("//") ? n : "/dashboard";
}

function Field({
  id,
  label,
  icon,
  children,
  aside,
}: {
  id: string;
  label: string;
  icon: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-medium text-on-surface" htmlFor={id}>
          {label}
        </label>
        {aside}
      </div>
      <div className="relative rounded-lg shadow-sm">
        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-on-surface-variant">
          <Icon name={icon} size={16} />
        </div>
        {children}
      </div>
    </div>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" data-testid="auth-error" className="rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-[13px] text-error flex items-start gap-2">
      <Icon name="alert" size={16} className="mt-px" />
      <span>{message}</span>
    </div>
  );
}

export function OtpForm({ email, onBack }: { email: string; onBack?: () => void }) {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(60);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const verify = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.verifyOtp(email, code.trim());
      router.push(nextPath());
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  const resend = async () => {
    setError(null);
    setInfo(null);
    try {
      const r = await authApi.resendOtp(email);
      setInfo(r.message || "A new code has been sent.");
      setCooldown(60);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <form className="space-y-4" onSubmit={verify} data-testid="otp-form">
      <div className="text-center">
        <div className="mx-auto w-12 h-12 rounded-full bg-primary/10 border border-primary/40 flex items-center justify-center text-primary">
          <Icon name="mail" size={24} />
        </div>
        <h2 className="mt-3 text-lg font-semibold text-white">Check your email</h2>
        <p className="mt-1 text-[13px] text-on-surface-variant">We sent a 6-digit code to the address you entered.</p>
      </div>
      <Field id="otp-code" label="Verification code" icon="key">
        <input
          id="otp-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          required
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          placeholder="123456"
          className={`${INPUT} font-mono tracking-[0.4em]`}
        />
      </Field>
      <FormError message={error} />
      {info && <p className="text-[12.5px] text-primary">{info}</p>}
      <button type="submit" disabled={busy || code.length !== 6} className={PRIMARY}>
        {busy ? "Verifying…" : "Verify and continue"}
      </button>
      <div className="flex items-center justify-between text-[12px] text-on-surface-variant">
        {onBack ? (
          <button type="button" onClick={onBack} className="hover:text-white">
            ← Change email
          </button>
        ) : (
          <span />
        )}
        <button type="button" onClick={resend} disabled={cooldown > 0} className="hover:text-white disabled:opacity-60">
          {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
        </button>
      </div>
    </form>
  );
}

export function SignInForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsOtp, setNeedsOtp] = useState(false);

  if (needsOtp) return <OtpForm email={email} onBack={() => setNeedsOtp(false)} />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.login(email.trim(), password);
      router.push(nextPath());
    } catch (err) {
      if (err instanceof ApiError && err.code === "EMAIL_NOT_VERIFIED") {
        try {
          await authApi.resendOtp(email.trim());
        } catch {
          // the OTP screen offers a resend button
        }
        setNeedsOtp(true);
      } else {
        setError(errorMessage(err));
      }
      setBusy(false);
    }
  };

  return (
    <form className="space-y-4" onSubmit={submit}>
      <Field id="work-email" label="Email" icon="mail">
        <input
          autoComplete="email"
          id="work-email"
          required
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
          className={INPUT}
        />
      </Field>
      <Field id="password" label="Password" icon="lock">
        <input
          autoComplete="current-password"
          id="password"
          required
          type={show ? "text" : "password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Enter your password"
          className={`${INPUT} pr-10`}
        />
        <button
          type="button"
          aria-label="Toggle password visibility"
          onClick={() => setShow((v) => !v)}
          className={`absolute inset-y-0 right-0 pr-3 flex items-center ${show ? "text-primary" : "text-on-surface-variant hover:text-on-surface"}`}
        >
          <Icon name={show ? "eye-off" : "eye"} size={16} />
        </button>
      </Field>
      <FormError message={error} />
      <button type="submit" disabled={busy} className={PRIMARY}>
        {busy ? "Signing in…" : "Sign in"}
        {!busy && <Icon name="arrow-right" size={16} />}
      </button>
    </form>
  );
}

export function SignUpForm() {
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<"form" | "otp">("form");

  if (step === "otp") return <OtpForm email={email.trim()} onBack={() => setStep("form")} />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.signup(email.trim(), password, company.trim());
      setStep("otp");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="space-y-4" onSubmit={submit} data-testid="signup-form">
      <Field id="corporate-email" label="Work email" icon="mail">
        <input
          id="corporate-email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
          className={INPUT}
        />
      </Field>
      <Field id="org-name" label="Company name" icon="layers">
        <input
          id="org-name"
          type="text"
          required
          maxLength={200}
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          placeholder="Your company"
          className={INPUT}
        />
      </Field>
      <Field id="new-password" label="Password" icon="lock" aside={<span className="text-[11px] text-on-surface-variant">8+ characters</span>}>
        <input
          id="new-password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Choose a password"
          className={INPUT}
        />
      </Field>
      <FormError message={error} />
      <button type="submit" disabled={busy} className={PRIMARY}>
        {busy ? "Creating account…" : "Create account"}
        {!busy && <Icon name="arrow-right" size={16} />}
      </button>
    </form>
  );
}
