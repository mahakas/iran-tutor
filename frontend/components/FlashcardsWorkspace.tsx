"use client";

/**
 * Darsyar flashcard workspace — NotebookLM-style study experience.
 *
 * Views: "decks" (library + resume banner) → "deck" (detail + study modes +
 * exports) → "study" (persistent session, flip, Got/Missed, results). Every
 * action talks to the real backend; study progress lives in PostgreSQL via
 * /api/v1/flashcards/sessions.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  BookOpenCheck,
  Download,
  Eye,
  FileText,
  Library,
  Play,
  Plus,
  RotateCw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { buildUserAuthHeaders, useAppContext } from "@/components/AppProvider";
import MathContent from "@/components/MathContent";
import FlashcardStudy from "@/components/FlashcardStudy";
import { fetchMyCapabilities } from "@/lib/capabilities";
import {
  flashcardErrorMessage,
  type Flashcard,
  type FlashcardDeck,
  type FlashcardDeckDetail,
  type StudyMode,
  type StudySession,
} from "@/lib/flashcards";
import type { BookOption } from "@/lib/types";

type View = "decks" | "deck" | "study";
type GradeRow = { number: number; title: string; has_major: boolean };
type MajorRow = { code: string; title: string };
type ExamRow = { id: string; title: string; status: string; book_title: string | null };

function todayLabel(): string {
  return new Date().toLocaleDateString("fa-IR");
}

function toFa(value: number): string {
  return Number(value).toLocaleString("fa-IR", { useGrouping: false });
}

export default function FlashcardsWorkspace() {
  const { authFetch, getActiveToken } = useAppContext();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("decks");
  const [decks, setDecks] = useState<FlashcardDeck[]>([]);
  const [activeDeck, setActiveDeck] = useState<FlashcardDeckDetail | null>(null);
  const [studySession, setStudySession] = useState<StudySession | null>(null);
  const [activeSessions, setActiveSessions] = useState<StudySession[]>([]);
  const [studyReturn, setStudyReturn] = useState<"decks" | "deck">("decks");
  const [dueCount, setDueCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [startingMode, setStartingMode] = useState<StudyMode | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newDeckTitle, setNewDeckTitle] = useState("");
  const [generateOpen, setGenerateOpen] = useState(false);
  const [libraryDecks, setLibraryDecks] = useState<FlashcardDeck[]>([]);

  const deckTitleFor = useCallback(
    (deckId: number | null) => {
      if (deckId === null) return "همهٔ دسته‌ها";
      return decks.find((deck) => deck.id === deckId)?.title ?? activeDeck?.title ?? `دستهٔ ${deckId}`;
    },
    [decks, activeDeck],
  );

  const loadDecks = useCallback(async () => {
    const response = await authFetch("/api/v1/flashcards/decks");
    if (response.status === 403) {
      setEnabled(false);
      return;
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(flashcardErrorMessage(payload, "بارگذاری دسته‌ها ناموفق بود."));
    setDecks(payload as FlashcardDeck[]);
    setDueCount((payload as FlashcardDeck[]).reduce((sum, deck) => sum + deck.stats.due, 0));
  }, [authFetch]);

  const loadLibrary = useCallback(async () => {
    const response = await authFetch("/api/v1/flashcards/library");
    if (response.ok) setLibraryDecks((await response.json()) as FlashcardDeck[]);
  }, [authFetch]);

  const loadActiveSessions = useCallback(async () => {
    const response = await authFetch("/api/v1/flashcards/sessions/active");
    if (response.ok) setActiveSessions((await response.json()) as StudySession[]);
  }, [authFetch]);

  // Gate the whole page on the capability flag; the API also returns 403 when disabled.
  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const keys = await fetchMyCapabilities(buildUserAuthHeaders(getActiveToken()));
      if (cancelled) return;
      if (keys !== null && !keys.has("flashcards")) {
        setEnabled(false);
        return;
      }
      setEnabled(true);
      setLoading(true);
      try {
        await Promise.all([loadDecks(), loadLibrary(), loadActiveSessions()]);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "خطا در بارگذاری.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, [getActiveToken, loadDecks, loadLibrary, loadActiveSessions]);

  async function openDeck(deckId: number) {
    setError("");
    setNotice("");
    const response = await authFetch(`/api/v1/flashcards/decks/${deckId}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(flashcardErrorMessage(payload, "دسته یافت نشد."));
      return;
    }
    setActiveDeck(payload as FlashcardDeckDetail);
    setView("deck");
  }

  async function startSession(
    deckId: number | null,
    mode: StudyMode,
    options: { shuffle?: boolean; cardIds?: number[] } = {},
  ) {
    setError("");
    setNotice("");
    setStartingMode(mode);
    try {
      const body: Record<string, unknown> = { deck_id: deckId, mode, shuffle: Boolean(options.shuffle) };
      if (options.cardIds && options.cardIds.length) body.card_ids = options.cardIds;
      const response = await authFetch("/api/v1/flashcards/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setError(flashcardErrorMessage(payload, "شروع جلسهٔ مطالعه ناموفق بود."));
        return;
      }
      setStudyReturn(view === "deck" ? "deck" : "decks");
      setStudySession(payload as StudySession);
      setView("study");
      void loadActiveSessions();
    } catch {
      setError("ارتباط با سرور برقرار نشد.");
    } finally {
      setStartingMode(null);
    }
  }

  async function resumeSession(session: StudySession) {
    setError("");
    setNotice("");
    const response = await authFetch(`/api/v1/flashcards/sessions/${session.id}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(flashcardErrorMessage(payload, "بازیابی جلسه ناموفق بود."));
      return;
    }
    setStudyReturn("decks");
    setStudySession(payload as StudySession);
    setView("study");
  }

  function mergeSummary(summary: StudySession) {
    setStudySession((prev) => {
      if (!prev) return summary;
      const cards = summary.cards ?? prev.cards;
      return { ...prev, ...summary, cards };
    });
  }

  function replaceSession(next: StudySession) {
    setStudySession(next);
    void loadActiveSessions();
  }

  function exitStudy() {
    setView(studyReturn === "deck" && activeDeck ? "deck" : "decks");
    void loadDecks();
    void loadActiveSessions();
    if (studyReturn === "deck" && activeDeck) void openDeck(activeDeck.id);
  }

  async function downloadAnki(deck: FlashcardDeck) {
    setError("");
    const response = await authFetch(`/api/v1/flashcards/decks/${deck.id}/export/anki`);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(flashcardErrorMessage(payload, "خروجی Anki ساخته نشد."));
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `darsyar-${deck.id}.apkg`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  async function downloadCsv(deck: FlashcardDeck) {
    setError("");
    const response = await authFetch(`/api/v1/flashcards/decks/${deck.id}/export/csv`);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(flashcardErrorMessage(payload, "خروجی CSV ساخته نشد."));
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `darsyar-${deck.id}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  async function createDeck() {
    const title = newDeckTitle.trim();
    if (!title) return;
    const response = await authFetch("/api/v1/flashcards/decks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(flashcardErrorMessage(payload, "ساخت دسته ناموفق بود."));
      return;
    }
    setNewDeckTitle("");
    await loadDecks();
    await openDeck((payload as FlashcardDeck).id);
  }

  async function deleteDeck(deck: FlashcardDeck) {
    if (!window.confirm(`دستهٔ «${deck.title}» و همهٔ کارت‌هایش حذف شود؟`)) return;
    const response = await authFetch(`/api/v1/flashcards/decks/${deck.id}`, { method: "DELETE" });
    if (!response.ok) {
      setError("حذف دسته ناموفق بود.");
      return;
    }
    setActiveDeck(null);
    setView("decks");
    await loadDecks();
    await loadActiveSessions();
  }

  async function deleteCard(card: Flashcard) {
    const response = await authFetch(`/api/v1/flashcards/cards/${card.id}`, { method: "DELETE" });
    if (!response.ok) {
      setError("حذف کارت ناموفق بود.");
      return;
    }
    await openDeck(card.deck_id);
    await loadDecks();
  }

  async function copyLibraryDeck(deck: FlashcardDeck) {
    const response = await authFetch(`/api/v1/flashcards/library/${deck.id}/copy`, { method: "POST" });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(flashcardErrorMessage(payload, "افزودن دسته ناموفق بود."));
      return;
    }
    setNotice("دسته به فلش‌کارت‌های شما اضافه شد.");
    await loadDecks();
  }

  const deckCards = useMemo(() => activeDeck?.cards ?? [], [activeDeck]);
  const activeDeckSession = activeDeck
    ? activeSessions.find((row) => row.deck_id === activeDeck.id)
    : undefined;
  const globalSessions = activeSessions.filter((row) => row.deck_id === null);

  if (enabled === false) {
    return (
      <section className="fc-panel fc-disabled" dir="rtl">
        <X size={22} />
        <h2>این قابلیت در حال حاضر غیرفعال است</h2>
        <p>فلش‌کارت‌ها توسط مدیر درسیار غیرفعال شده‌اند. بعداً دوباره سر بزنید.</p>
      </section>
    );
  }

  return (
    <div className="fc-root" dir="rtl">
      {error && <div className="inline-error fc-alert" role="alert">{error}</div>}
      {notice && <div className="fc-notice" role="status">{notice}</div>}

      {view === "decks" && (
        <>
          <header className="fc-toolbar">
            <div>
              <h2>دسته‌های فلش‌کارت</h2>
              <p className="fc-muted">مرور امروز: {todayLabel()}</p>
            </div>
            <div className="fc-toolbar-actions">
              <button
                type="button"
                className="fc-btn"
                onClick={() => void startSession(null, "full")}
                disabled={loading || startingMode !== null}
                title="همهٔ کارت‌ها، مستقل از موعد SM-2"
              >
                <Play size={16} /> مطالعهٔ کامل همه
              </button>
              <button
                type="button"
                className="fc-btn primary"
                onClick={() => void startSession(null, "smart")}
                disabled={loading || startingMode !== null}
                title="فقط کارت‌های در موعد SM-2"
              >
                <RotateCw size={16} /> مرور هوشمند
                {dueCount > 0 && <span className="fc-due-badge">{dueCount}</span>}
              </button>
              <button type="button" className="fc-btn" onClick={() => setGenerateOpen(true)}>
                <Sparkles size={16} /> ساخت با هوش مصنوعی
              </button>
            </div>
          </header>

          {(activeSessions.length > 0 || globalSessions.length > 0) && (
            <section className="fc-resume-banner" aria-label="جلسه‌های ناتمام">
              {activeSessions.map((row) => (
                <div key={row.id} className="fc-resume-row">
                  <div>
                    <strong>ادامهٔ جلسهٔ ناتمام</strong>
                    <div className="fc-muted fc-small">
                      {deckTitleFor(row.deck_id)} · کارت {toFa(Math.min(row.position + 1, row.total))} از {toFa(row.total)} ·{" "}
                      {row.mode === "smart" ? "مرور هوشمند" : "مطالعهٔ کامل"}
                    </div>
                  </div>
                  <button type="button" className="fc-btn small primary" onClick={() => void resumeSession(row)}>
                    ادامهٔ مطالعه
                  </button>
                </div>
              ))}
            </section>
          )}

          <div className="fc-create-row">
            <input
              className="fc-input"
              value={newDeckTitle}
              onChange={(event) => setNewDeckTitle(event.target.value)}
              placeholder="نام دستهٔ تازه…"
              maxLength={255}
            />
            <button type="button" className="fc-btn" onClick={() => void createDeck()} disabled={!newDeckTitle.trim()}>
              <Plus size={16} /> دستهٔ جدید
            </button>
          </div>

          {loading && <p className="fc-muted">در حال بارگذاری…</p>}
          {!loading && decks.length === 0 && (
            <div className="fc-empty">
              هنوز دسته‌ای ندارید. با «ساخت با هوش مصنوعی» از فصل کتاب یا اشتباهات آزمون کارت بسازید، یا از
              گفت‌وگوی معلم دکمهٔ «تبدیل به فلش‌کارت» را بزنید.
            </div>
          )}

          <div className="fc-deck-grid">
            {decks.map((deck) => (
              <article key={deck.id} className="fc-deck-card">
                <div className="fc-deck-head">
                  <h3>{deck.title}</h3>
                  {deck.stats.due > 0 && <span className="fc-due-badge">امروز: {deck.stats.due}</span>}
                </div>
                <div className="fc-muted fc-small">
                  {deck.stats.total} کارت · {deck.stats.mastered} تسلط‌یافته
                </div>
                <div className="fc-progress" aria-label="پیشرفت دسته">
                  <span style={{ width: `${deck.stats.progress_percent}%` }} />
                </div>
                <div className="fc-deck-actions">
                  <button type="button" className="fc-btn small" onClick={() => void openDeck(deck.id)}>
                    <Eye size={14} /> مشاهده
                  </button>
                  <button
                    type="button"
                    className="fc-btn small"
                    onClick={() => void startSession(deck.id, "full")}
                    disabled={deck.stats.total === 0 || startingMode !== null}
                    title="همهٔ کارت‌های این دسته"
                  >
                    <BookOpenCheck size={14} /> مطالعه
                  </button>
                  <button
                    type="button"
                    className="fc-btn small"
                    onClick={() => void startSession(deck.id, "smart")}
                    disabled={deck.stats.due === 0 || startingMode !== null}
                    title="فقط کارت‌های در موعد SM-2"
                  >
                    <RotateCw size={14} /> مرور هوشمند
                  </button>
                </div>
              </article>
            ))}
          </div>

          {libraryDecks.length > 0 && (
            <section className="fc-library">
              <h3>
                <Library size={16} /> کتابخانهٔ عمومی (تأییدشده)
              </h3>
              <div className="fc-deck-grid">
                {libraryDecks.map((deck) => (
                  <article key={deck.id} className="fc-deck-card">
                    <h3>{deck.title}</h3>
                    <div className="fc-muted fc-small">{deck.stats.total} کارت</div>
                    <button type="button" className="fc-btn small" onClick={() => void copyLibraryDeck(deck)}>
                      <Plus size={14} /> افزودن به من
                    </button>
                  </article>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {view === "deck" && activeDeck && (
        <>
          <header className="fc-toolbar">
            <div>
              <button type="button" className="fc-link" onClick={() => setView("decks")}>
                ← همهٔ دسته‌ها
              </button>
              <h2>{activeDeck.title}</h2>
              <p className="fc-muted fc-small">
                {activeDeck.stats.total} کارت · {activeDeck.stats.due} در موعد امروز
              </p>
            </div>
            <div className="fc-toolbar-actions">
              <button
                type="button"
                className="fc-btn primary"
                onClick={() => void startSession(activeDeck.id, "full")}
                disabled={activeDeck.cards.length === 0 || startingMode !== null}
                title="همهٔ کارت‌های این دسته، مستقل از موعد SM-2"
              >
                <BookOpenCheck size={16} /> مطالعهٔ کامل
              </button>
              <button
                type="button"
                className="fc-btn"
                onClick={() => void startSession(activeDeck.id, "smart")}
                disabled={activeDeck.stats.due === 0 || startingMode !== null}
                title="فقط کارت‌های در موعد SM-2"
              >
                <RotateCw size={16} /> مرور هوشمند
                {activeDeck.stats.due > 0 && <span className="fc-due-badge">{activeDeck.stats.due}</span>}
              </button>
              <button
                type="button"
                className="fc-btn"
                onClick={() => void downloadAnki(activeDeck)}
                disabled={activeDeck.cards.length === 0}
              >
                <Download size={16} /> خروجی Anki
              </button>
              <button
                type="button"
                className="fc-btn"
                onClick={() => void downloadCsv(activeDeck)}
                disabled={activeDeck.cards.length === 0}
              >
                <FileText size={16} /> دانلود CSV
              </button>
              <button type="button" className="fc-btn danger" onClick={() => void deleteDeck(activeDeck)}>
                <Trash2 size={16} /> حذف دسته
              </button>
            </div>
          </header>
          {activeDeckSession && (
            <div className="fc-resume-row standalone">
              <div>
                <strong>جلسهٔ ناتمام در این دسته</strong>
                <div className="fc-muted fc-small">
                  کارت {toFa(Math.min(activeDeckSession.position + 1, activeDeckSession.total))} از {toFa(activeDeckSession.total)}
                </div>
              </div>
              <button type="button" className="fc-btn small primary" onClick={() => void resumeSession(activeDeckSession)}>
                ادامهٔ مطالعه
              </button>
            </div>
          )}
          <div className="fc-progress wide" aria-hidden="true">
            <span style={{ width: `${activeDeck.stats.progress_percent}%` }} />
          </div>
          {deckCards.length === 0 && (
            <div className="empty-state">
              <b>این دسته هنوز کارتی ندارد</b>
              <span>کارت تازه بسازید یا از یک فصل کتاب کارت تولید کنید.</span>
            </div>
          )}
          <ul className="fc-card-list">
            {deckCards.map((card) => (
              <li key={card.id} className="fc-card-row">
                <div className="fc-card-row-body">
                  <MathContent content={card.front_md} />
                  <div className="fc-back-preview">
                    <MathContent content={card.back_md} />
                  </div>
                  {card.citations.map((cite, index) => (
                    <span key={`${cite.pdf_page_index}-${index}`} className="fc-cite-chip">
                      <BookOpen size={12} /> {cite.citation}
                    </span>
                  ))}
                </div>
                <button type="button" className="fc-icon-btn" aria-label="حذف کارت" onClick={() => void deleteCard(card)}>
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {view === "study" && studySession && (
        <FlashcardStudy
          session={studySession}
          deckTitle={deckTitleFor(studySession.deck_id)}
          authFetch={authFetch}
          onMergeSummary={mergeSummary}
          onReplaceSession={replaceSession}
          onExit={exitStudy}
          onStudyAll={() => void startSession(studySession.deck_id, "full")}
          onStudyMissed={(cardIds) =>
            void startSession(studySession.deck_id, "full", { cardIds })
          }
          onError={setError}
          onNotice={setNotice}
        />
      )}

      {generateOpen && (
        <GenerateModal
          decks={decks}
          onClose={() => setGenerateOpen(false)}
          onGenerated={async (deckId, message) => {
            setGenerateOpen(false);
            setNotice(message);
            await loadDecks();
            await openDeck(deckId);
          }}
          authFetch={authFetch}
        />
      )}
    </div>
  );
}

type CountOption = { value: number; label: string; hint: string };

const COUNT_OPTIONS: ReadonlyArray<CountOption> = [
  { value: 3, label: "کمتر", hint: "۳ کارت" },
  { value: 5, label: "استاندارد", hint: "۵ کارت" },
  { value: 10, label: "بیشتر", hint: "۱۰ کارت" },
];

const DIFFICULTY_OPTIONS: ReadonlyArray<{ value: "easy" | "medium" | "hard"; label: string; hint: string }> = [
  { value: "easy", label: "آسان", hint: "تعاریف و مفاهیم پایه، سؤال‌های مستقیم" },
  { value: "medium", label: "متوسط", hint: "مفاهیم اصلی فصل و روابط بین آن‌ها" },
  { value: "hard", label: "سخت", hint: "نکات عمیق، مقایسهٔ مفاهیم و تحلیل" },
];

const CUSTOM_PROMPT_MAX = 1000;

type GenerateModalProps = {
  decks: FlashcardDeck[];
  onClose: () => void;
  onGenerated: (deckId: number, message: string) => Promise<void>;
  authFetch: (input: string, init?: RequestInit) => Promise<Response>;
};

function GenerateModal({ decks, onClose, onGenerated, authFetch }: GenerateModalProps) {
  const [source, setSource] = useState<"book" | "mistake">("book");
  const [grades, setGrades] = useState<GradeRow[]>([]);
  const [majors, setMajors] = useState<MajorRow[]>([]);
  const [grade, setGrade] = useState<number | "">("");
  const [major, setMajor] = useState("");
  const [books, setBooks] = useState<BookOption[]>([]);
  const [bookId, setBookId] = useState<number | "">("");
  const [chapter, setChapter] = useState("");
  const [pageStart, setPageStart] = useState("");
  const [pageEnd, setPageEnd] = useState("");
  const [exams, setExams] = useState<ExamRow[]>([]);
  const [examId, setExamId] = useState("");
  const [count, setCount] = useState<number>(5);
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium");
  const [customPrompt, setCustomPrompt] = useState("");
  const [deckChoice, setDeckChoice] = useState<string>("new");
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const selectedGrade = grades.find((row) => row.number === grade);
  const needsMajor = Boolean(selectedGrade?.has_major);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/curriculum/grades")
      .then((response) => response.json())
      .then((payload: GradeRow[]) => {
        if (!cancelled) setGrades(payload);
      })
      .catch(() => undefined);
    fetch("/api/v1/curriculum/majors")
      .then((response) => response.json())
      .then((payload: MajorRow[]) => {
        if (!cancelled) setMajors(payload);
      })
      .catch(() => undefined);
    authFetch("/api/v1/exams")
      .then((response) => (response.ok ? response.json() : []))
      .then((payload: ExamRow[]) => {
        if (!cancelled) setExams(payload.filter((row) => row.status === "submitted"));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  useEffect(() => {
    if (grade === "") return;
    if (needsMajor && !major) return;
    const query = new URLSearchParams({ grade_number: String(grade) });
    if (needsMajor && major) query.set("major_code", major);
    let cancelled = false;
    fetch(`/api/v1/curriculum/books?${query.toString()}`)
      .then(async (response) => {
        const payload = await response.json();
        if (!cancelled) setBooks(response.ok ? (payload as BookOption[]) : []);
      })
      .catch(() => {
        if (!cancelled) setBooks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [grade, major, needsMajor]);

  async function submit() {
    if (busy) return; // hard guard against duplicate submissions
    setFormError("");
    const body: Record<string, unknown> = { source, count, difficulty };
    const trimmedPrompt = customPrompt.trim();
    if (trimmedPrompt) body.custom_prompt = trimmedPrompt;
    if (deckChoice === "new") {
      if (newTitle.trim()) body.new_deck_title = newTitle.trim();
    } else {
      body.deck_id = Number(deckChoice);
    }
    if (source === "book") {
      if (bookId === "") return setFormError("کتاب را انتخاب کنید.");
      body.book_id = bookId;
      if (chapter.trim()) body.chapter_number = Number(chapter);
      if (pageStart.trim()) body.page_start = Number(pageStart);
      if (pageEnd.trim()) body.page_end = Number(pageEnd);
      if (!chapter.trim() && !pageStart.trim()) return setFormError("فصل یا بازهٔ صفحه را مشخص کنید.");
    } else {
      if (!examId) return setFormError("یک آزمون ثبت‌شده را انتخاب کنید.");
      body.exam_id = examId;
    }
    setBusy(true);
    try {
      const response = await authFetch("/api/v1/flashcards/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        // Keep the form intact so the student can retry without re-entering data.
        setFormError(flashcardErrorMessage(payload, "ساخت فلش‌کارت ناموفق بود."));
        return;
      }
      const created = payload as { deck_id: number; created_count: number };
      await onGenerated(created.deck_id, `${created.created_count} فلش‌کارت ساخته شد و به دسته اضافه شد.`);
    } catch {
      setFormError("ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fc-modal-backdrop" role="dialog" aria-modal="true" aria-label="ساخت با هوش مصنوعی">
      <div className="fc-modal">
        <header className="fc-toolbar">
          <h2>
            <Sparkles size={18} /> ساخت فلش‌کارت با هوش مصنوعی
          </h2>
          <button type="button" className="fc-icon-btn" onClick={onClose} aria-label="بستن" disabled={busy}>
            <X size={18} />
          </button>
        </header>

        <div className="fc-segment" role="tablist">
          <button type="button" className={source === "book" ? "active" : ""} onClick={() => setSource("book")}>
            از فصل یا صفحه‌های کتاب
          </button>
          <button
            type="button"
            className={source === "mistake" ? "active" : ""}
            onClick={() => setSource("mistake")}
          >
            از اشتباهات آزمون
          </button>
        </div>

        {source === "book" ? (
          <div className="fc-form-grid">
            <label>
              پایه
              <select
                value={grade}
                onChange={(event) => {
                  setGrade(event.target.value ? Number(event.target.value) : "");
                  setBooks([]);
                  setBookId("");
                }}
              >
                <option value="">انتخاب کنید</option>
                {grades.map((row) => (
                  <option key={row.number} value={row.number}>
                    {row.title}
                  </option>
                ))}
              </select>
            </label>
            {needsMajor && (
              <label>
                رشته
                <select
                  value={major}
                  onChange={(event) => {
                    setMajor(event.target.value);
                    setBooks([]);
                    setBookId("");
                  }}
                >
                  <option value="">انتخاب کنید</option>
                  {majors.map((row) => (
                    <option key={row.code} value={row.code}>
                      {row.title}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="wide">
              کتاب
              <select value={bookId} onChange={(event) => setBookId(event.target.value ? Number(event.target.value) : "")}>
                <option value="">انتخاب کنید</option>
                {books.map((book) => (
                  <option key={book.id} value={book.id}>
                    {book.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              شمارهٔ فصل
              <input value={chapter} onChange={(event) => setChapter(event.target.value)} inputMode="numeric" placeholder="مثلاً ۳" />
            </label>
            <label>
              از صفحهٔ PDF
              <input value={pageStart} onChange={(event) => setPageStart(event.target.value)} inputMode="numeric" />
            </label>
            <label>
              تا صفحهٔ PDF
              <input value={pageEnd} onChange={(event) => setPageEnd(event.target.value)} inputMode="numeric" />
            </label>
            <p className="fc-muted fc-small wide">حداکثر ۸ صفحه در هر بار ساخت مجاز است.</p>
          </div>
        ) : (
          <div className="fc-form-grid">
            <label className="wide">
              آزمون
              <select value={examId} onChange={(event) => setExamId(event.target.value)}>
                <option value="">انتخاب کنید</option>
                {exams.map((exam) => (
                  <option key={exam.id} value={exam.id}>
                    {exam.title}
                    {exam.book_title ? ` — ${exam.book_title}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <p className="fc-muted fc-small wide">
              فقط پاسخ‌های نادرستِ همین آزمون، با توضیح و ارجاع صفحه، به کارت تبدیل می‌شوند.
            </p>
          </div>
        )}

        <fieldset className="fc-option-fieldset">
          <legend>تعداد کارت‌ها</legend>
          <div className="fc-option-cards" role="radiogroup" aria-label="تعداد کارت‌ها">
            {COUNT_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={count === option.value}
                className={`fc-option-card${count === option.value ? " active" : ""}`}
                onClick={() => setCount(option.value)}
              >
                <span className="fc-option-title">{option.label}</span>
                <span className="fc-option-hint">{option.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="fc-option-fieldset">
          <legend>سطح دشواری</legend>
          <div className="fc-option-cards" role="radiogroup" aria-label="سطح دشواری">
            {DIFFICULTY_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={difficulty === option.value}
                className={`fc-option-card${difficulty === option.value ? " active" : ""}`}
                onClick={() => setDifficulty(option.value)}
              >
                <span className="fc-option-title">{option.label}</span>
                <span className="fc-option-hint">{option.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <label className="fc-custom-prompt">
          می‌خواهی فلش‌کارت‌ها روی چه موضوعی تمرکز کنند؟
          <textarea
            value={customPrompt}
            onChange={(event) => setCustomPrompt(event.target.value.slice(0, CUSTOM_PROMPT_MAX))}
            maxLength={CUSTOM_PROMPT_MAX}
            rows={3}
            placeholder="مثلاً: فقط نکات مهم و فرمول‌های فصل را پوشش بده؛ یا کارت‌ها برای آمادگی امتحان نهایی باشند…"
          />
          <span className="fc-char-counter" aria-live="polite">
            {customPrompt.length} از {CUSTOM_PROMPT_MAX}
          </span>
        </label>

        <div className="fc-form-grid">
          <label>
            مقصد
            <select value={deckChoice} onChange={(event) => setDeckChoice(event.target.value)}>
              <option value="new">دستهٔ تازه</option>
              {decks.map((deck) => (
                <option key={deck.id} value={deck.id}>
                  {deck.title}
                </option>
              ))}
            </select>
          </label>
          {deckChoice === "new" && (
            <label className="wide">
              نام دستهٔ تازه (اختیاری)
              <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} maxLength={255} />
            </label>
          )}
        </div>

        {formError && <div className="inline-error" role="alert">{formError}</div>}

        <div className="fc-modal-actions">
          <button type="button" className="fc-btn" onClick={onClose} disabled={busy}>
            انصراف
          </button>
          <button type="button" className="fc-btn primary" onClick={() => void submit()} disabled={busy}>
            <Sparkles size={16} /> {busy ? "در حال ساخت…" : "ساخت کارت‌ها"}
          </button>
        </div>
      </div>
    </div>
  );
}
