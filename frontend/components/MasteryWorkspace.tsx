"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAppContext } from "@/components/AppProvider";
import BookGradePicker from "@/components/BookGradePicker";
import {
  MASTERY_STATUS_LABEL,
  phase5ErrorMessage,
  toPersianDigits,
  type MasteryTree,
} from "@/lib/phase5";

export default function MasteryWorkspace() {
  const { authFetch } = useAppContext();
  const [bookId, setBookId] = useState<number | null>(null);
  const [tree, setTree] = useState<MasteryTree | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    (async () => {
      const res = await authFetch(`/api/v1/mastery/books/${bookId}`);
      const payload = await res.json().catch(() => null);
      if (cancelled) return;
      if (!res.ok) {
        setError(phase5ErrorMessage(payload, "مسیر تسلط در دسترس نیست."));
        setTree(null);
        return;
      }
      setError(null);
      setTree(payload as MasteryTree);
    })();
    return () => {
      cancelled = true;
    };
  }, [authFetch, bookId]);
  // Derived, not reset in an effect: a cleared book shows no tree.
  const shownTree = bookId ? tree : null;
  return (
    <div dir="rtl" style={{ display: "grid", gap: 16 }}>
      <BookGradePicker value={bookId} onChange={setBookId} />
      {!bookId ? <div className="glass-panel" style={{ padding: 20 }}>یک کتاب را انتخاب کنید.</div> : null}
      {error ? <div className="glass-panel" style={{ padding: 20 }}>{error}</div> : null}
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
          <ol style={{ display: "grid", gap: 10, listStyle: "none", padding: 0, margin: 0 }}>
            {shownTree.chapters.map((chapter) => {
              const percent = chapter.score === null ? null : Math.round(chapter.score * 100);
              return (
                <li key={chapter.chapter_number} className="glass-panel" style={{ padding: 14, opacity: chapter.status === "locked" ? 0.6 : 1 }}>
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
    </div>
  );
}
