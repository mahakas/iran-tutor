/** Phase 3 flashcard types shared by the student workspace, chat button and admin panel. */

export type FlashcardStats = {
  total: number;
  due: number;
  mastered: number;
  new: number;
  progress_percent: number;
};

export type FlashcardDeck = {
  id: number;
  title: string;
  book_id: number | null;
  chapter_number: number | null;
  page_start: number | null;
  page_end: number | null;
  source_type: "book" | "chat" | "mistake" | "manual";
  is_public: boolean;
  admin_approved: boolean;
  created_at: string | null;
  stats: FlashcardStats;
};

export type FlashcardCitation = {
  book_id: number | null;
  book_title: string | null;
  chapter_number: number | null;
  chapter_title: string | null;
  pdf_page_index: number | null;
  printed_page_number: number | null;
  citation: string;
};

export type FlashcardReview = {
  ease_factor: number;
  interval_days: number;
  repetitions: number;
  next_review_at: string;
  last_rating: number | null;
  review_count: number;
};

export type Flashcard = {
  id: number;
  deck_id: number;
  front_md: string;
  back_md: string;
  hint_md: string;
  citations: FlashcardCitation[];
  tags: string[];
  review: FlashcardReview | null;
  deck_title?: string;
};

export type FlashcardDeckDetail = FlashcardDeck & { cards: Flashcard[] };

export type DueQueue = { due_count: number; cards: Flashcard[] };

export const RATING_BUTTONS: ReadonlyArray<{ rating: 1 | 2 | 3 | 4; label: string; tone: string }> = [
  { rating: 1, label: "فراموش کردم", tone: "again" },
  { rating: 2, label: "سخت", tone: "hard" },
  { rating: 3, label: "خوب", tone: "good" },
  { rating: 4, label: "آسان", tone: "easy" },
];

/** Reads FastAPI's `detail` (string or validation list) and falls back to a Persian message. */
export function flashcardErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") {
      return detail[0].msg as string;
    }
  }
  return fallback;
}
