"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "@/components/AppProvider";
import MathContent from "@/components/MathContent";
import BookGradePicker from "@/components/BookGradePicker";
import { phase5ErrorMessage, toPersianDigits, type DeepSolveSession } from "@/lib/phase5";

const ACTION_LABEL: Record<string, string> = {
  hint1: "راهنمای ۱",
  hint2: "راهنمای ۲",
  reveal_step: "نمایش گام فعلی",
  full_solution: "پاسخ کامل",
};

export default function DeepSolveWorkspace() {
  const { authFetch } = useAppContext();
  const [problem, setProblem] = useState("");
  const [bookId, setBookId] = useState<number | null>(null);
  const [session, setSession] = useState<DeepSolveSession | null>(null);
  const [history, setHistory] = useState<Array<{ id: string; problem_text: string; status: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await authFetch("/api/v1/deep-solve/sessions");
      if (!res.ok || cancelled) return;
      const payload = (await res.json()) as { items: Array<{ id: string; problem_text: string; status: string }> };
      if (!cancelled) setHistory(payload.items ?? []);
    })();
    return () => {
      cancelled = true;
    };
  }, [authFetch, session]);

  const create = async () => {
    if (!problem.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch("/api/v1/deep-solve/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ problem_text: problem.trim(), book_id: bookId }),
      });
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setError(phase5ErrorMessage(payload, "ایجاد جلسه انجام نشد."));
        return;
      }
      setSession(payload as DeepSolveSession);
    } finally {
      setBusy(false);
    }
  };

  const act = async (action: string) => {
    if (!session) return;
    setBusy(true);
    try {
      const res = await authFetch(`/api/v1/deep-solve/sessions/${session.id}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setError(phase5ErrorMessage(payload, "عملیات انجام نشد."));
        return;
      }
      setError(null);
      setSession(payload as DeepSolveSession);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div dir="rtl" style={{ display: "grid", gap: 16 }}>
      <section className="glass-panel" style={{ padding: 16, display: "grid", gap: 10 }}>
        <label style={{ display: "grid", gap: 6 }}>
          مسئلهٔ چندمرحله‌ای (ریاضی، فیزیک یا شیمی)
          <textarea rows={4} value={problem} onChange={(e) => setProblem(e.target.value)} placeholder="مسئله را با نمادهای LaTeX یا متن ساده بنویسید…" />
        </label>
        <BookGradePicker value={bookId} onChange={setBookId} />
        <button type="button" className="btn-primary" disabled={busy || !problem.trim()} onClick={() => void create()}>
          شروع حل گام‌به‌گام
        </button>
        {error ? <div role="alert">{error}</div> : null}
      </section>

      {session ? (
        <section className="glass-panel" style={{ padding: 16, display: "grid", gap: 12 }}>
          <div>
            گام {toPersianDigits(Math.min(session.current_step + 1, session.total_steps))} از {toPersianDigits(session.total_steps)}
            {session.topic ? ` · ${session.topic}` : ""}
          </div>
          <ol style={{ display: "grid", gap: 10, paddingInlineStart: 20 }}>
            {session.steps.map((step) => (
              <li key={step.index} style={{ opacity: step.state === "pending" ? 0.5 : 1 }}>
                <strong>{step.title}</strong>
                {step.state === "pending" ? " (قفل)" : ""}
                {step.hint1 ? <div style={{ fontSize: 14 }}>راهنمای ۱: <MathContent content={step.hint1} /></div> : null}
                {step.hint2 ? <div style={{ fontSize: 14 }}>راهنمای ۲: <MathContent content={step.hint2} /></div> : null}
                {step.explanation ? <div><MathContent content={step.explanation} /></div> : null}
                {step.result ? <div>نتیجه: <MathContent content={step.result} /></div> : null}
              </li>
            ))}
          </ol>
          {session.status === "active" ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {session.available_actions.map((action) => (
                <button key={action} type="button" className="btn-ghost" disabled={busy} onClick={() => void act(action)}>
                  {ACTION_LABEL[action] ?? action}
                </button>
              ))}
            </div>
          ) : (
            <div role="status">
              <strong>پاسخ نهایی:</strong> <MathContent content={session.final_answer ?? ""} />
            </div>
          )}
        </section>
      ) : null}

      {history.length ? (
        <section className="glass-panel" style={{ padding: 16 }}>
          <h3>جلسه‌های قبلی</h3>
          <ul>
            {history.map((item) => (
              <li key={item.id}>
                <button type="button" className="btn-ghost" onClick={() => void openSession(item.id)}>
                  {item.problem_text.slice(0, 80)} ({item.status === "completed" ? "کامل‌شده" : "در حال حل"})
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );

  async function openSession(id: string) {
    const res = await authFetch(`/api/v1/deep-solve/sessions/${id}`);
    const payload = await res.json().catch(() => null);
    if (res.ok) setSession(payload as DeepSolveSession);
  }
}
