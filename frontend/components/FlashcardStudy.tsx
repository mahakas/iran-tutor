"use client";

/**
 * NotebookLM-style study environment for Darsyar flashcards.
 *
 * Rendered by FlashcardsWorkspace while `view === "study"`. Everything is
 * driven by the server-persisted study session (PostgreSQL), so closing the
 * browser and coming back resumes the same order, position, flip state and
 * per-card results. Fullscreen uses the browser Fullscreen API with a fixed
 * overlay fallback.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsRight,
  Eye,
  EyeOff,
  Lightbulb,
  Maximize2,
  Minimize2,
  RotateCcw,
  Shuffle,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import MathContent from "@/components/MathContent";
import {
  flashcardErrorMessage,
  type ExplainResponse,
  type StudySession,
} from "@/lib/flashcards";

export type StudyCardData = NonNullable<StudySession["cards"]>[number];

type FlashcardStudyProps = {
  session: StudySession;
  deckTitle: string | null;
  authFetch: (input: string, init?: RequestInit) => Promise<Response>;
  onMergeSummary: (summary: StudySession) => void;
  onReplaceSession: (session: StudySession) => void;
  onExit: () => void;
  onStudyAll: () => void;
  onStudyMissed: (cardIds: number[]) => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
};

const OUTCOME_LABEL: Record<"got" | "missed", string> = {
  got: "بلد بودم",
  missed: "بلد نبودم",
};

/** Persian (fa-IR) digits for UI counters — matches «کارت ۶ از ۳۰». */
function toFa(value: number): string {
  return Number(value).toLocaleString("fa-IR", { useGrouping: false });
}

export default function FlashcardStudy({
  session,
  deckTitle,
  authFetch,
  onMergeSummary,
  onReplaceSession,
  onExit,
  onStudyAll,
  onStudyMissed,
  onError,
  onNotice,
}: FlashcardStudyProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  // Per-card chrome state is keyed by card id, so no reset effect is needed:
  // switching cards naturally hides the previous card's hint/explanation.
  const [hintOpenFor, setHintOpenFor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [explain, setExplain] = useState<{
    cardId: number | null;
    value:
      | { state: "idle" }
      | { state: "loading" }
      | { state: "error"; message: string }
      | { state: "done"; payload: ExplainResponse };
  }>({ cardId: null, value: { state: "idle" } });

  const cards = useMemo(() => session.cards ?? [], [session.cards]);
  const total = cards.length;
  const position = Math.min(Math.max(0, session.position), Math.max(0, total - 1));
  const current: StudyCardData | null = total ? cards[position] : null;
  const results = useMemo(() => session.results ?? {}, [session.results]);
  const currentResult = current ? results[String(current.id)] : undefined;
  const counts = session.counts;
  const completed = session.status === "completed";
  const progressPercent = counts.total ? Math.round((counts.rated / counts.total) * 100) : 0;
  const missedIds = useMemo(
    () =>
      (session.card_ids ?? []).filter((id) => (results[String(id)] ?? null) === "missed"),
    [session.card_ids, results],
  );

  const hintOpen = hintOpenFor !== null && hintOpenFor === current?.id;
  const explainView =
    explain.cardId === (current?.id ?? null) ? explain.value : ({ state: "idle" } as const);

  // Track native fullscreen transitions (including Esc).
  useEffect(() => {
    function handle() {
      const active = Boolean(
        document.fullscreenElement ||
          (document as Document & { webkitFullscreenElement?: Element | null }).webkitFullscreenElement,
      );
      setFullscreen((prev) => (active ? prev : false));
    }
    document.addEventListener("fullscreenchange", handle);
    document.addEventListener("webkitfullscreenchange", handle as EventListener);
    return () => {
      document.removeEventListener("fullscreenchange", handle);
      document.removeEventListener("webkitfullscreenchange", handle as EventListener);
    };
  }, []);

  const patchProgress = useCallback(
    async (patch: { position?: number; flipped?: boolean }) => {
      try {
        await authFetch(`/api/v1/flashcards/sessions/${session.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        });
      } catch {
        // Non-fatal: local state already updated; the next successful write re-syncs.
      }
    },
    [authFetch, session.id],
  );

  const goTo = useCallback(
    (next: number) => {
      const clamped = Math.min(Math.max(0, next), Math.max(0, total - 1));
      if (clamped === position) return;
      onMergeSummary({ ...session, position: clamped, flipped: false });
      void patchProgress({ position: clamped, flipped: false });
    },
    [onMergeSummary, patchProgress, position, session, total],  );

  const toggleFlip = useCallback(() => {
    if (!current) return;
    const next = !session.flipped;
    onMergeSummary({ ...session, flipped: next });
    void patchProgress({ flipped: next });
  }, [current, onMergeSummary, patchProgress, session]);

  async function toggleFullscreen() {
    const doc = document as Document & {
      webkitFullscreenElement?: Element | null;
      webkitExitFullscreen?: () => Promise<void>;
    };
    const nativeActive = Boolean(document.fullscreenElement || doc.webkitFullscreenElement);
    if (fullscreen || nativeActive) {
      // Already in fullscreen (native or CSS fallback): leave it.
      if (nativeActive) {
        try {
          if (document.exitFullscreen) await document.exitFullscreen();
          else if (doc.webkitExitFullscreen) await doc.webkitExitFullscreen();
        } catch {
          /* older browsers */
        }
      }
      setFullscreen(false);
      return;
    }
    const element = containerRef.current as (HTMLDivElement & {
      webkitRequestFullscreen?: () => Promise<void>;
    }) | null;
    if (element?.requestFullscreen) {
      try {
        await element.requestFullscreen();
        setFullscreen(true);
        return;
      } catch {
        /* fall through to the CSS fallback */
      }
    } else if (element?.webkitRequestFullscreen) {
      try {
        await element.webkitRequestFullscreen();
        setFullscreen(true);
        return;
      } catch {
        /* fall through */
      }
    }
    // Fallback for browsers without the Fullscreen API: fixed overlay.
    setFullscreen(true);
  }

  async function rate(outcome: "got" | "missed") {
    if (!current || busy || currentResult) return;
    setBusy(true);
    onError("");
    try {
      const rating = outcome === "got" ? 3 : 1;
      const response = await authFetch(`/api/v1/flashcards/${current.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, session_id: session.id }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        onError(flashcardErrorMessage(payload, "ثبت نتیجه ناموفق بود."));
        return;
      }
      const summary = (payload as { session?: StudySession } | null)?.session;
      if (!summary) {
        onError("پاسخ سرور کامل نبود؛ لطفاً دوباره تلاش کنید.");
        return;
      }
      const mergedResults = summary.results ?? {};
      const mergedCards = cards.map((card) =>
        String(card.id) === String(current.id)
          ? { ...card, session_result: outcome }
          : card,
      );
      const merged: StudySession = {
        ...session,
        ...summary,
        cards: mergedCards,
      };
      if (summary.status === "completed") {
        onMergeSummary(merged);
        return;
      }
      // Auto-advance: next unrated card after the current one, else the first unrated one.
      const order = merged.card_ids ?? [];
      const isRated = (id: number) => (mergedResults[String(id)] ?? null) !== null;
      let nextIndex = -1;
      for (let step = 1; step <= order.length; step += 1) {
        const actual = (position + step) % order.length;
        if (!isRated(order[actual])) {
          nextIndex = actual;
          break;
        }
      }
      if (nextIndex === -1) {
        nextIndex = order.findIndex((id) => !isRated(id));
      }
      const clampedNext = nextIndex === -1 ? position : nextIndex;
      onMergeSummary({ ...merged, position: clampedNext, flipped: false });
      void patchProgress({ position: clampedNext, flipped: false });
    } catch {
      onError("ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function shuffle() {
    if (busy) return;
    setBusy(true);
    try {
      const response = await authFetch(`/api/v1/flashcards/sessions/${session.id}/shuffle`, {
        method: "POST",
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        onError(flashcardErrorMessage(payload, "بر زدن کارت‌ها ناموفق بود."));
        return;
      }
      onReplaceSession(payload as StudySession);
    } catch {
      onError("ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function restart() {
    if (busy) return;
    const ok = window.confirm(
      "شروع مجدد؟ نتیجه‌های ثبت‌شدهٔ این جلسه پاک می‌شود (سابقهٔ کلی مرور شما در SM-2 حفظ می‌ماند).",
    );
    if (!ok) return;
    setBusy(true);
    try {
      const response = await authFetch(`/api/v1/flashcards/sessions/${session.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shuffle: false }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        onError(flashcardErrorMessage(payload, "شروع دوباره ناموفق بود."));
        return;
      }
      onNotice("جلسه از نو شروع شد.");
      onReplaceSession(payload as StudySession);
    } catch {
      onError("ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteCurrentCard() {
    if (!current || busy) return;
    const ok = window.confirm("این کارت برای همیشه حذف شود؟ نتیجه‌های مرور مرتبط با آن هم پاک می‌شود.");
    if (!ok) return;
    setBusy(true);
    try {
      const response = await authFetch(`/api/v1/flashcards/cards/${current.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        onError(flashcardErrorMessage(payload, "حذف کارت ناموفق بود."));
        return;
      }
      const refreshed = await authFetch(`/api/v1/flashcards/sessions/${session.id}`);
      if (refreshed.ok) {
        onReplaceSession((await refreshed.json()) as StudySession);
      } else {
        onExit();
      }
      onNotice("کارت حذف شد.");
    } catch {
      onError("ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function loadExplanation() {
    if (!current || explainView.state === "loading") return;
    setExplain({ cardId: current.id, value: { state: "loading" } });
    try {
      const response = await authFetch(`/api/v1/flashcards/cards/${current.id}/explain`, {
        method: "POST",
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setExplain({
          cardId: current.id,
          value: {
            state: "error",
            message: flashcardErrorMessage(payload, "دریافت توضیح ناموفق بود."),
          },
        });
        return;
      }
      setExplain({ cardId: current.id, value: { state: "done", payload: payload as ExplainResponse } });
    } catch {
      setExplain({ cardId: current.id, value: { state: "error", message: "ارتباط با سرور برقرار نشد." } });
    }
  }

  // Keyboard support: RTL-aware arrows, space/enter to flip, g/m for ratings.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (completed) return;
      if (event.key === "ArrowRight") {
        event.preventDefault();
        goTo(position - 1); // RTL: right arrow = previous
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        goTo(position + 1); // RTL: left arrow = next
      } else if (event.key === " " || event.key === "Enter") {
        // Avoid hijacking activation of focused buttons.
        if (target && target.tagName === "BUTTON") return;
        event.preventDefault();
        toggleFlip();
      } else if (event.key.toLowerCase() === "g" && session.flipped) {
        void rate("got");
      } else if (event.key.toLowerCase() === "m" && session.flipped) {
        void rate("missed");
      } else if (event.key === "Escape" && fullscreen) {
        setFullscreen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [goTo, position, session.flipped, completed, fullscreen, toggleFlip]);

  const screenLabel = deckTitle ?? (session.deck_id === null ? "همهٔ دسته‌ها" : "جلسهٔ مطالعه");

  if (completed) {
    const success = counts.rated ? Math.round((counts.got / counts.rated) * 100) : 0;
    return (
      <div ref={containerRef} className={`fc-study fc-results${fullscreen ? " is-fullscreen" : ""}`} dir="rtl">
        <header className="fc-study-topbar">
          <button type="button" className="fc-link fc-back-link" onClick={onExit}>
            <ArrowRight size={16} /> بازگشت
          </button>
          <span className="fc-muted fc-small">{screenLabel}</span>
          <span />
        </header>
        <div className="fc-results-card">
          <p className="fc-results-kicker">نتیجهٔ مطالعه</p>
          <h2 className="fc-results-title">جلسه تکمیل شد</h2>
          <div className="fc-results-hero" aria-label="درصد موفقیت">
            <span className="fc-results-percent">{toFa(success)}٪</span>
            <span className="fc-muted">پاسخ‌های درست</span>
          </div>
          <div className="fc-results-grid">
            <div className="fc-result-stat">
              <span className="fc-result-num">{toFa(counts.total)}</span>
              <span className="fc-muted fc-small">تعداد کارت‌ها</span>
            </div>
            <div className="fc-result-stat got">
              <span className="fc-result-num">{toFa(counts.got)}</span>
              <span className="fc-muted fc-small">بلد بودم</span>
            </div>
            <div className="fc-result-stat missed">
              <span className="fc-result-num">{toFa(counts.missed)}</span>
              <span className="fc-muted fc-small">بلد نبودم</span>
            </div>
          </div>
          <div className="fc-progress tall" aria-hidden="true">
            <span style={{ width: `${success}%` }} />
          </div>
          <div className="fc-results-actions">
            <button type="button" className="fc-btn" onClick={() => void restart()}>
              <RotateCcw size={16} /> مرور دوبارهٔ همین کارت‌ها
            </button>
            <button type="button" className="fc-btn" onClick={onStudyAll}>
              <ChevronsRight size={16} /> مرور همهٔ کارت‌ها
            </button>
            <button
              type="button"
              className="fc-btn primary"
              onClick={() => missedIds.length && onStudyMissed(missedIds)}
              disabled={missedIds.length === 0}
            >
              <X size={16} /> فقط کارت‌های بلد نبودم ({toFa(missedIds.length)})
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`fc-study${fullscreen ? " is-fullscreen" : ""}`}
      dir="rtl"
    >
      <header className="fc-study-topbar">
        <button type="button" className="fc-link fc-back-link" onClick={onExit}>
          <ArrowRight size={16} /> بازگشت
        </button>
        <div className="fc-study-title">
          <strong>{screenLabel}</strong>
          <span className="fc-counter" aria-live="polite">
            کارت {toFa(total ? position + 1 : 0)} از {toFa(total)}
          </span>
        </div>
        <div className="fc-study-actions">
          <button
            type="button"
            className="fc-icon-btn"
            onClick={() => void shuffle()}
            disabled={busy || total < 2}
            aria-label="بر زدن کارت‌ها"
            title="بر زدن کارت‌ها"
          >
            <Shuffle size={17} />
          </button>
          <button
            type="button"
            className="fc-icon-btn"
            onClick={() => void toggleFullscreen()}
            aria-label={fullscreen ? "خروج از تمام‌صفحه" : "تمام‌صفحه"}
            aria-pressed={fullscreen}
            title={fullscreen ? "خروج از تمام‌صفحه" : "تمام‌صفحه"}
          >
            {fullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
          </button>
          <button
            type="button"
            className="fc-icon-btn"
            onClick={() => void restart()}
            disabled={busy}
            aria-label="شروع مجدد"
            title="شروع مجدد"
          >
            <RotateCcw size={17} />
          </button>
          <button
            type="button"
            className="fc-icon-btn danger"
            onClick={() => void deleteCurrentCard()}
            disabled={busy || !current}
            aria-label="حذف این کارت"
            title="حذف این کارت"
          >
            <Trash2 size={17} />
          </button>
        </div>
      </header>

      <div className="fc-progress tall" role="progressbar" aria-valuenow={progressPercent} aria-valuemin={0} aria-valuemax={100} aria-label="پیشرفت مطالعه">
        <span style={{ width: `${progressPercent}%` }} />
      </div>

      <div className="fc-card-stage">
        {current ? (
          <>
            <button
              type="button"
              className={`fc-bigcard${session.flipped ? " is-flipped" : ""}`}
              onClick={toggleFlip}
              aria-pressed={session.flipped}
              aria-label={session.flipped ? "نمایش روی کارت" : "نمایش پاسخ کارت"}
            >
              <div className="fc-bigcard-inner">
                <div className="fc-bigface fc-front">
                  <span className="fc-face-tag">سؤال</span>
                  <div className="fc-face-body">
                    <MathContent content={current.front_md} />
                  </div>
                  <span className="fc-face-hint">
                    <Eye size={14} /> برای دیدن پاسخ بزنید
                  </span>
                </div>
                <div className="fc-bigface fc-back">
                  <span className="fc-face-tag answer">پاسخ</span>
                  <div className="fc-face-body">
                    <MathContent content={current.back_md} />
                  </div>
                  {current.citations.length > 0 && (
                    <div className="fc-cite-stack">
                      {current.citations.map((cite, index) => (
                        <span key={`${cite.pdf_page_index}-${index}`} className="fc-cite-chip">
                          <BookOpen size={12} /> {cite.citation}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </button>

            <div className="fc-stage-tools">
              <button
                type="button"
                className="fc-icon-btn"
                onClick={() => goTo(position - 1)}
                disabled={position === 0}
                aria-label="کارت قبلی"
                title="کارت قبلی"
              >
                <ChevronRight size={20} />
              </button>

              <div className="fc-stage-center">
                {!session.flipped ? (
                  <button type="button" className="fc-btn primary" onClick={toggleFlip}>
                    <Eye size={16} /> نمایش پاسخ
                  </button>
                ) : (
                  <div className="fc-outcome-row" role="group" aria-label="نتیجهٔ شما برای این کارت">
                    {currentResult ? (
                      <span className={`fc-result-chip ${currentResult}`}>
                        {currentResult === "got" ? <Check size={16} /> : <X size={16} />}
                        {OUTCOME_LABEL[currentResult]} — نتیجهٔ این جلسه ثبت شده است
                      </span>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="fc-outcome got"
                          onClick={() => void rate("got")}
                          disabled={busy}
                        >
                          <Check size={22} strokeWidth={3} /> بلد بودم
                        </button>
                        <button
                          type="button"
                          className="fc-outcome missed"
                          onClick={() => void rate("missed")}
                          disabled={busy}
                        >
                          <X size={22} strokeWidth={3} /> بلد نبودم
                        </button>
                      </>
                    )}
                  </div>
                )}
                {current.hint_md && (
                  <button
                    type="button"
                    className="fc-btn small ghost"
                    onClick={() => setHintOpenFor(hintOpen ? null : current?.id ?? null)}
                    aria-expanded={hintOpen}
                  >
                    {hintOpen ? <EyeOff size={14} /> : <Lightbulb size={14} />}
                    {hintOpen ? "پنهان کردن راهنما" : "نمایش راهنما"}
                  </button>
                )}
              </div>

              <button
                type="button"
                className="fc-icon-btn"
                onClick={() => goTo(position + 1)}
                disabled={position >= total - 1}
                aria-label="کارت بعدی"
                title="کارت بعدی"
              >
                <ChevronLeft size={20} />
              </button>
            </div>

            {hintOpen && current.hint_md && (
              <div className="fc-hint">
                <MathContent content={current.hint_md} />
              </div>
            )}

            {session.flipped && (
              <div className="fc-explain">
                {explainView.state !== "done" && (
                  <button
                    type="button"
                    className="fc-btn small"
                    onClick={() => void loadExplanation()}
                    disabled={explainView.state === "loading"}
                  >
                    <Sparkles size={15} />
                    {explainView.state === "loading" ? "در حال نوشتن توضیح…" : "توضیح بیشتر"}
                  </button>
                )}
                {explainView.state === "error" && <div className="inline-error">{explainView.message}</div>}
                {explainView.state === "done" && (
                  <div className="fc-explain-panel">
                    <div className="fc-explain-head">
                      <Sparkles size={16} /> توضیح بیشتر
                    </div>
                    <MathContent content={explainView.payload.explanation} />
                    {explainView.payload.source_available ? (
                      explainView.payload.citation && (
                        <span className="fc-cite-chip">
                          <BookOpen size={12} /> {explainView.payload.citation}
                        </span>
                      )
                    ) : (
                      <p className="fc-muted fc-small">
                        متن اصلی کتاب برای این کارت قابل بازیابی نبود؛ این توضیح فقط بر اساس محتوای ذخیره‌شدهٔ کارت است.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        ) : (
          <div className="fc-empty">کارتی برای نمایش وجود ندارد.</div>
        )}
      </div>
    </div>
  );
}
