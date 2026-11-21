"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Download,
  Eye,
  EyeOff,
  Lightbulb,
  Plus,
  RotateCw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { buildUserAuthHeaders, useAppContext } from "@/components/AppProvider";
import MathContent from "@/components/MathContent";
import { fetchMyCapabilities } from "@/lib/capabilities";
import {
  RATING_BUTTONS,
  flashcardErrorMessage,
  type DueQueue,
  type Flashcard,
  type FlashcardDeck,
  type FlashcardDeckDetail,
} from "@/lib/flashcards";
import type { BookOption } from "@/lib/types";

type View = "decks" | "deck" | "study";
type GradeRow = { number: number; title: string; has_major: boolean };
type MajorRow = { code: string; title: string };
type ExamRow = { id: string; title: string; status: string; book_title: string | null };

function todayLabel(): string {
  return new Date().toLocaleDateString("fa-IR");
}

export default function FlashcardsWorkspace() {
  const { authFetch, getActiveToken } = useAppContext();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("decks");
  const [decks, setDecks] = useState<FlashcardDeck[]>([]);
  const [activeDeck, setActiveDeck] = useState<FlashcardDeckDetail | null>(null);
  const [queue, setQueue] = useState<Flashcard[]>([]);
  const [studyTotal, setStudyTotal] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [hintOpen, setHintOpen] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [dueCount, setDueCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newDeckTitle, setNewDeckTitle] = useState("");
  const [generateOpen, setGenerateOpen] = useState(false);
  const [libraryDecks, setLibraryDecks] = useState<FlashcardDeck[]>([]);

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
        await Promise.all([loadDecks(), loadLibrary()]);
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
  }, [getActiveToken, loadDecks, loadLibrary]);

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

  async function startStudy(deckId: number | null) {
    setError("");
    setNotice("");
    const response = await authFetch("/api/v1/flashcards/due?limit=200");
    const payload = (await response.json().catch(() => null)) as DueQueue | null;
    if (!response.ok || !payload) {
      setError("دریافت کارت‌های امروز ناموفق بود.");
      return;
    }
    const cards = deckId === null ? payload.cards : payload.cards.filter((card) => card.deck_id === deckId);
    if (!cards.length) {
      setNotice("برای امروز کارتی برای مرور وجود ندارد. آفرین!");
      return;
    }
    setQueue(cards);
    setStudyTotal(cards.length);
    setFlipped(false);
    setHintOpen(false);
    setView("study");
  }

  async function rate(rating: 1 | 2 | 3 | 4) {
    const card = queue[0];
    if (!card || reviewBusy) return;
    setReviewBusy(true);
    setError("");
    try {
      const response = await authFetch(`/api/v1/flashcards/${card.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        setError(flashcardErrorMessage(payload, "ثبت مرور ناموفق بود."));
        return;
      }
      // Rating 1 (forgot) brings the card back later in this session.
      setQueue((prev) => {
        const [head, ...rest] = prev;
        return rating === 1 && head ? [...rest, head] : rest;
      });
      setFlipped(false);
      setHintOpen(false);
    } catch {
      setError("ارتباط با سرور برقرار نشد.");
    } finally {
      setReviewBusy(false);
    }
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

  const currentCard = queue[0] ?? null;
  const studyDone = studyTotal - queue.length;
  const studyPercent = studyTotal ? Math.round((studyDone / studyTotal) * 100) : 0;

  const deckCards = useMemo(() => activeDeck?.cards ?? [], [activeDeck]);

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
      {error && <div className="inline-error fc-alert">{error}</div>}
      {notice && <div className="fc-notice">{notice}</div>}

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
                className="fc-btn primary"
                onClick={() => void startStudy(null)}
                disabled={loading}
              >
                <RotateCw size={16} /> مرور امروز
                {dueCount > 0 && <span className="fc-due-badge">{dueCount}</span>}
              </button>
              <button type="button" className="fc-btn" onClick={() => setGenerateOpen(true)}>
                <Sparkles size={16} /> ساخت با هوش مصنوعی
              </button>
            </div>
          </header>

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
                    onClick={() => void startStudy(deck.id)}
                    disabled={deck.stats.due === 0}
                  >
                    <RotateCw size={14} /> مرور
                  </button>
                </div>
              </article>
            ))}
          </div>

          {libraryDecks.length > 0 && (
            <section className="fc-library">
              <h3>کتابخانهٔ عمومی (تأییدشده)</h3>
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
                {activeDeck.stats.total} کارت · {activeDeck.stats.due} برای امروز
              </p>
            </div>
            <div className="fc-toolbar-actions">
              <button
                type="button"
                className="fc-btn primary"
                onClick={() => void startStudy(activeDeck.id)}
                disabled={activeDeck.stats.due === 0}
              >
                <RotateCw size={16} /> مرور این دسته
              </button>
              <button
                type="button"
                className="fc-btn"
                onClick={() => void downloadAnki(activeDeck)}
                disabled={activeDeck.cards.length === 0}
              >
                <Download size={16} /> خروجی Anki
              </button>
              <button type="button" className="fc-btn danger" onClick={() => void deleteDeck(activeDeck)}>
                <Trash2 size={16} /> حذف دسته
              </button>
            </div>
          </header>
          <div className="fc-progress wide">
            <span style={{ width: `${activeDeck.stats.progress_percent}%` }} />
          </div>
          {deckCards.length === 0 && <div className="fc-empty">این دسته هنوز کارتی ندارد.</div>}
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

      {view === "study" && (
        <section className="fc-study">
          <header className="fc-toolbar">
            <button type="button" className="fc-link" onClick={() => setView(activeDeck ? "deck" : "decks")}>
              ← بازگشت
            </button>
            <span className="fc-muted">
              {studyDone} از {studyTotal} · {studyPercent}٪
            </span>
          </header>
          <div className="fc-progress wide">
            <span style={{ width: `${studyPercent}%` }} />
          </div>

          {currentCard ? (
            <>
              <button
                type="button"
                className={`fc-flip ${flipped ? "is-flipped" : ""}`}
                onClick={() => setFlipped((value) => !value)}
                aria-pressed={flipped}
                aria-label={flipped ? "نمایش رو" : "نمایش پشت کارت"}
              >
                <div className="fc-flip-inner">
                  <div className="fc-face fc-front">
                    <MathContent content={currentCard.front_md} />
                  </div>
                  <div className="fc-face fc-back">
                    <MathContent content={currentCard.back_md} />
                    {currentCard.citations.length > 0 && (
                      <div className="fc-cite-stack">
                        {currentCard.citations.map((cite, index) => (
                          <span key={`${cite.pdf_page_index}-${index}`} className="fc-cite-chip">
                            <BookOpen size={12} /> {cite.citation}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </button>

              <div className="fc-study-tools">
                {currentCard.hint_md && (
                  <button
                    type="button"
                    className="fc-btn small"
                    onClick={() => setHintOpen((value) => !value)}
                  >
                    {hintOpen ? <EyeOff size={14} /> : <Lightbulb size={14} />}
                    {hintOpen ? "پنهان کردن راهنما" : "نمایش راهنما"}
                  </button>
                )}
                {hintOpen && currentCard.hint_md && (
                  <div className="fc-hint">
                    <MathContent content={currentCard.hint_md} />
                  </div>
                )}
              </div>

              {flipped ? (
                <div className="fc-rating-row" role="group" aria-label="امتیاز مرور">
                  {RATING_BUTTONS.map((item) => (
                    <button
                      key={item.rating}
                      type="button"
                      className={`fc-rate ${item.tone}`}
                      disabled={reviewBusy}
                      onClick={() => void rate(item.rating)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="fc-muted fc-center">برای دیدن پاسخ کارت را بزنید.</p>
              )}
            </>
          ) : (
            <div className="fc-empty">
              مرور امروز تمام شد. {studyTotal} کارت مرور شد.
              <div className="fc-deck-actions center">
                <button type="button" className="fc-btn" onClick={() => setView("decks")}>
                  بازگشت به دسته‌ها
                </button>
              </div>
            </div>
          )}
        </section>
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
  const [count, setCount] = useState(5);
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
    setFormError("");
    const body: Record<string, unknown> = { source, count };
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
        setFormError(flashcardErrorMessage(payload, "ساخت فلش‌کارت ناموفق بود."));
        return;
      }
      const created = payload as { deck_id: number; created_count: number };
      await onGenerated(created.deck_id, `${created.created_count} فلش‌کارت با ارجاع به کتاب ساخته شد.`);
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
          <button type="button" className="fc-icon-btn" onClick={onClose} aria-label="بستن">
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

        <div className="fc-form-grid">
          <label>
            تعداد کارت
            <select value={count} onChange={(event) => setCount(Number(event.target.value))}>
              {[3, 5, 8, 10].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
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

        {formError && <div className="inline-error">{formError}</div>}

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
