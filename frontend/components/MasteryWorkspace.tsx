"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import { useAppContext } from "@/components/AppProvider";
import BookGradePicker from "@/components/BookGradePicker";
import {
  MASTERY_STATUS_LABEL,
  phase5ErrorMessage,
  toPersianDigits,
  type MasteryTree,
  type ObjectiveMasteryItem,
  type ObjectiveMasteryTree,
} from "@/lib/phase5";

const OBJECTIVE_STATUS_LABEL: Record<string, string> = {
  locked: "قفل؛ پیش‌نیاز کامل نشده",
  not_started: "شروع‌نشده",
  submitted_for_review: "ارسال‌شده؛ در انتظار بازبینی",
  needs_support: "نیازمند پشتیبانی",
  developing: "در حال پیشرفت",
  mastered: "تسلط تأییدشده",
};

const QUALITATIVE_LEVELS = [
  ["needs_support", "نیازمند پشتیبانی"],
  ["developing", "در حال پیشرفت"],
  ["proficient", "مسلط"],
  ["advanced", "پیشرفته"],
  ["not_observed", "هنوز مشاهده نشده"],
] as const;

const SOURCE_TYPES = [
  ["self_assessment", "خودارزیابی"],
  ["reading", "مطالعه و توضیح"],
  ["performance_task", "فعالیت عملکردی"],
] as const;

export default function MasteryWorkspace() {
  const { authFetch } = useAppContext();
  const [bookId, setBookId] = useState<number | null>(null);
  const [tree, setTree] = useState<MasteryTree | null>(null);
  const [objectiveTree, setObjectiveTree] = useState<ObjectiveMasteryTree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [objectiveError, setObjectiveError] = useState<string | null>(null);
  const [savingObjectiveId, setSavingObjectiveId] = useState<number | null>(null);
  const [submissionMessage, setSubmissionMessage] = useState<string | null>(null);

  const refreshObjectiveTree = useCallback(async (selectedBookId: number) => {
    const response = await authFetch(
      `/api/v1/mastery/books/${selectedBookId}/objectives`,
    );
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(phase5ErrorMessage(payload, "اهداف یادگیری در دسترس نیستند."));
    }
    setObjectiveTree(payload as ObjectiveMasteryTree);
  }, [authFetch]);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    setError(null);
    setObjectiveError(null);
    setSubmissionMessage(null);
    (async () => {
      const [chapterResponse, objectiveResponse] = await Promise.all([
        authFetch(`/api/v1/mastery/books/${bookId}`),
        authFetch(`/api/v1/mastery/books/${bookId}/objectives`),
      ]);
      const [chapterPayload, objectivePayload] = await Promise.all([
        chapterResponse.json().catch(() => null),
        objectiveResponse.json().catch(() => null),
      ]);
      if (cancelled) return;
      if (chapterResponse.ok) setTree(chapterPayload as MasteryTree);
      else {
        setTree(null);
        setError(phase5ErrorMessage(chapterPayload, "مسیر تسلط در دسترس نیست."));
      }
      if (objectiveResponse.ok) setObjectiveTree(objectivePayload as ObjectiveMasteryTree);
      else {
        setObjectiveTree(null);
        setObjectiveError(phase5ErrorMessage(objectivePayload, "اهداف یادگیری در دسترس نیستند."));
      }
    })().catch(() => {
      if (!cancelled) {
        setError("دریافت اطلاعات مسیر تسلط انجام نشد.");
        setObjectiveError("دریافت اهداف یادگیری انجام نشد.");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [authFetch, bookId]);

  const submitEvidence = async (
    event: FormEvent<HTMLFormElement>,
    objective: ObjectiveMasteryItem,
  ) => {
    event.preventDefault();
    if (!bookId) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const scoreText = String(data.get("score") ?? "").trim();
    const qualitativeLevel = String(data.get("qualitative_level") ?? "").trim();
    const feedback = String(data.get("feedback") ?? "").trim();
    const sourceType = String(data.get("source_type") ?? "self_assessment");

    if (objective.assessment_profile === "written" && !scoreText) {
      setObjectiveError("برای این هدف، ثبت نمره الزامی است.");
      return;
    }
    if (
      ["qualitative_descriptive", "performance"].includes(objective.assessment_profile) &&
      !qualitativeLevel
    ) {
      setObjectiveError("برای این هدف، انتخاب سطح ارزیابی توصیفی الزامی است.");
      return;
    }
    if (
      objective.assessment_profile === "mixed" &&
      !scoreText &&
      !qualitativeLevel
    ) {
      setObjectiveError("برای ثبت شاهد این هدف، نمره یا سطح ارزیابی را وارد کنید.");
      return;
    }

    setSavingObjectiveId(objective.id);
    setObjectiveError(null);
    setSubmissionMessage(null);
    try {
      const response = await authFetch("/api/v1/mastery/evidence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          objective_id: objective.id,
          book_id: bookId,
          source_type: sourceType,
          score: scoreText ? Number(scoreText) : null,
          qualitative_level: qualitativeLevel || null,
          rubric: {},
          feedback: feedback || null,
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setObjectiveError(phase5ErrorMessage(payload, "ثبت شاهد یادگیری انجام نشد."));
        return;
      }
      form.reset();
      await refreshObjectiveTree(bookId);
      setSubmissionMessage(
        "شاهد یادگیری ثبت شد و تا زمان بازبینی، تسلط قطعی محسوب نمی‌شود.",
      );
    } catch {
      setObjectiveError("ارتباط با سرویس ثبت شواهد برقرار نشد.");
    } finally {
      setSavingObjectiveId(null);
    }
  };

  // Derived from the selected book so a previous book's tree is never shown
  // while the next request is loading.
  const shownTree = bookId && tree?.book.id === bookId ? tree : null;
  const shownObjectiveTree =
    bookId && objectiveTree?.book.id === bookId ? objectiveTree : null;

  return (
    <div dir="rtl" style={{ display: "grid", gap: 16 }}>
      <BookGradePicker
        value={bookId}
        onChange={(nextBookId) => {
          setBookId(nextBookId);
          setTree(null);
          setObjectiveTree(null);
          setError(null);
          setObjectiveError(null);
          setSubmissionMessage(null);
        }}
      />
      {!bookId ? (
        <div className="glass-panel" style={{ padding: 20 }}>
          برای مشاهدهٔ مسیر تسلط و اهداف یادگیری، یک کتاب رسمی انتخاب کنید.
        </div>
      ) : null}
      {error ? <div className="glass-panel" role="alert" style={{ padding: 16 }}>{error}</div> : null}
      {shownTree ? (
        <>
          <div className="glass-panel" style={{ padding: 16, display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "space-between" }}>
            <span>
              {shownTree.book.title} · {toPersianDigits(shownTree.mastered_count)} از {toPersianDigits(shownTree.chapters.length)} فصل تسلط یافته
            </span>
            <span>
              آستانهٔ تسلط: {toPersianDigits(Math.round(shownTree.threshold * 100))}٪ · حالت: {shownTree.unlock_mode === "sequential" ? "ترتیبی" : "باز"}
            </span>
            <Link href={`/study/${shownTree.book.id}`}>مطالعهٔ کتاب</Link>
          </div>
          <ol className="mastery-timeline" aria-label="مسیر فصل‌های تسلط">
            {shownTree.chapters.map((chapter) => {
              const percent = chapter.score === null ? null : Math.round(chapter.score * 100);
              return (
                <li key={chapter.chapter_number} className="glass-panel mastery-node" data-status={chapter.status} style={{ padding: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                    <strong>
                      فصل {toPersianDigits(chapter.chapter_number)}: {chapter.chapter_title}
                    </strong>
                    <span>{MASTERY_STATUS_LABEL[chapter.status]}</span>
                  </div>
                  <div
                    role="progressbar"
                    aria-valuenow={percent ?? 0}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    style={{ height: 8, borderRadius: 6, background: "rgba(0,0,0,0.08)", marginTop: 8, overflow: "hidden" }}
                  >
                    <div style={{ width: `${percent ?? 0}%`, height: "100%", background: "#16a34a" }} />
                  </div>
                  <div style={{ fontSize: 13, marginTop: 6 }}>
                    {percent === null ? "هنوز داده‌ای ثبت نشده" : `تسلط: ${toPersianDigits(percent)}٪`}
                    {chapter.locked_reason === "previous_chapter_not_mastered" ? " · قفل تا تسلط فصل قبل" : ""}
                    {chapter.locked_reason === "admin_locked" ? " · قفل توسط مدیر" : ""}
                  </div>
                </li>
              );
            })}
          </ol>
        </>
      ) : null}

      {shownObjectiveTree ? (
        <section className="glass-panel" style={{ padding: 16, display: "grid", gap: 12 }}>
          <div>
            <h3 style={{ margin: 0 }}>اهداف یادگیری این نسخهٔ کتاب</h3>
            <p style={{ margin: "6px 0 0", fontSize: 13 }}>
              {toPersianDigits(shownObjectiveTree.mastered_count)} هدف از {toPersianDigits(shownObjectiveTree.objectives.length)} هدف به‌صورت بازبینی‌شده به تسلط رسیده‌اند.
              {shownObjectiveTree.academic_year_code ? ` · سال تحصیلی ${shownObjectiveTree.academic_year_code}` : ""}
            </p>
          </div>
          {shownObjectiveTree.message ? <p>{shownObjectiveTree.message}</p> : null}
          {shownObjectiveTree.objectives.map((objective) => {
            const isWaiting = objective.status === "submitted_for_review";
            const canSubmit = objective.status !== "locked" && objective.status !== "mastered";
            return (
              <article key={objective.id} className="mastery-node" style={{ borderTop: "1px solid var(--border-subtle, rgba(127,127,127,.25))", paddingTop: 12 }}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <div>
                    <strong>{objective.title}</strong>
                    <div style={{ fontSize: 12, opacity: 0.75 }}>
                      {objective.subject.title} · {objective.unit.title} · {objective.code}
                    </div>
                    {objective.description ? <p style={{ margin: "6px 0" }}>{objective.description}</p> : null}
                  </div>
                  <span>{OBJECTIVE_STATUS_LABEL[objective.status] ?? objective.status}</span>
                </div>
                <div style={{ fontSize: 13, marginTop: 6 }}>
                  {objective.score !== null ? `میانگین نمرهٔ تأییدشده: ${toPersianDigits(objective.score)}٪` : ""}
                  {objective.qualitative_level ? ` · سطح: ${objective.qualitative_level}` : ""}
                  {objective.evidence_count ? ` · ${toPersianDigits(objective.evidence_count)} شاهد` : ""}
                </div>
                {objective.prerequisites.length ? (
                  <div style={{ fontSize: 12, marginTop: 6 }}>
                    پیش‌نیازها: {objective.prerequisites.map((item) => item.title).join("، ")}
                  </div>
                ) : null}
                {objective.evidence.length ? (
                  <ul style={{ margin: "8px 0", paddingInlineStart: 20, fontSize: 12 }}>
                    {objective.evidence.slice(0, 3).map((item) => (
                      <li key={item.id}>
                        {item.source_type} · {item.verification_status === "verified" ? "تأییدشده" : item.verification_status === "rejected" ? "ردشده" : "در انتظار بازبینی"}
                        {item.score !== null ? ` · ${toPersianDigits(item.score)}٪` : ""}
                        {item.feedback ? ` · ${item.feedback}` : ""}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {canSubmit ? (
                  <details style={{ marginTop: 8 }}>
                    <summary style={{ cursor: "pointer" }}>
                      {isWaiting ? "ارسال شاهد تکمیلی" : "ثبت شاهد یادگیری"}
                    </summary>
                    <form
                      onSubmit={(event) => void submitEvidence(event, objective)}
                      style={{ display: "grid", gap: 8, marginTop: 10 }}
                    >
                      <label style={{ display: "grid", gap: 4 }}>
                        نوع شاهد
                        <select name="source_type" defaultValue={objective.assessment_profile === "performance" ? "performance_task" : "self_assessment"}>
                          {SOURCE_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                      </label>
                      {["written", "mixed"].includes(objective.assessment_profile) ? (
                        <label style={{ display: "grid", gap: 4 }}>
                          نمره (۰ تا ۱۰۰)
                          <input name="score" type="number" min="0" max="100" step="1" required={objective.assessment_profile === "written"} />
                        </label>
                      ) : null}
                      {["qualitative_descriptive", "performance", "mixed"].includes(objective.assessment_profile) ? (
                        <label style={{ display: "grid", gap: 4 }}>
                          سطح ارزیابی
                          <select name="qualitative_level" defaultValue="" required={objective.assessment_profile !== "mixed"}>
                            <option value="">انتخاب سطح</option>
                            {QUALITATIVE_LEVELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                          </select>
                        </label>
                      ) : null}
                      <label style={{ display: "grid", gap: 4 }}>
                        توضیح یا بازخورد (اختیاری)
                        <textarea name="feedback" rows={2} maxLength={4000} />
                      </label>
                      <button type="submit" className="btn-primary" disabled={savingObjectiveId === objective.id}>
                        {savingObjectiveId === objective.id ? "در حال ثبت…" : "ارسال برای بازبینی"}
                      </button>
                    </form>
                  </details>
                ) : null}
              </article>
            );
          })}
        </section>
      ) : null}
      {objectiveError ? <div className="glass-panel" role="alert" style={{ padding: 16 }}>{objectiveError}</div> : null}
      {submissionMessage ? <div className="glass-panel" role="status" style={{ padding: 16 }}>{submissionMessage}</div> : null}
    </div>
  );
}
