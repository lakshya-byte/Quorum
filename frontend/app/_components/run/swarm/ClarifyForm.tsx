"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { answersApi, errorMessage } from "../../../_lib/api";
import type { ClarifyQuestion } from "../../../_lib/swarm";
import { Button, Card, ErrorNote, Field, Icon, Textarea } from "../../../_ui";

/** needs_input: the planner could not size the work and asks. Answers re-run the task. */
export default function ClarifyForm({ runId, questions }: { runId: string; questions: ClarifyQuestion[] }) {
  const router = useRouter();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ok = questions.length > 0 && questions.every((q) => (answers[q.id] || "").trim().length > 0);
  const send = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await answersApi.send(runId, Object.fromEntries(Object.entries(answers).map(([k, v]) => [k, v.trim()])));
      if (r?.runId && r.runId !== runId) router.push(`/runs/${r.runId}`);
      else window.location.reload();
    } catch (e) {
      setErr(errorMessage(e));
      setBusy(false);
    }
  };
  return (
    <Card className="flex flex-col gap-4 border-secondary/40 p-5" data-testid="clarify-form">
      <div className="flex items-start gap-3">
        <Icon name="info" size={22} className="mt-0.5 text-secondary" />
        <div>
          <h2 className="text-[15px] font-semibold text-secondary">PatchLoop needs a little more to plan this</h2>
          <p className="mt-0.5 text-[13px] leading-5 text-on-surface-variant">Nothing was changed and nothing was declined. Answer below and the task runs again with your answers.</p>
        </div>
      </div>
      {questions.map((q, i) => (
        <Field key={q.id} label={`${i + 1}. ${q.text}`}>
          {(p) => <Textarea {...p} value={answers[q.id] || ""} onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))} maxLength={1000} className="min-h-[84px]" data-testid={`answer-${q.id}`} />}
        </Field>
      ))}
      {err && <ErrorNote>{err}</ErrorNote>}
      <div>
        <Button icon="send" onClick={send} loading={busy} disabled={!ok} data-testid="answers-send">
          Send answers and run
        </Button>
      </div>
    </Card>
  );
}
