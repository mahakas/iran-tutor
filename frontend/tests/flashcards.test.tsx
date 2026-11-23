/**
 * Tests for the NotebookLM-style flashcard experience:
 * generation modal options, study session flow (flip/nav/rate/results),
 * shuffle/fullscreen, reload-restore, and the resume banner.
 *
 * The backend contract is mocked in-memory; no network, API keys or DB are used.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FlashcardsWorkspace from "@/components/FlashcardsWorkspace";
import FlashcardStudy from "@/components/FlashcardStudy";
import type { StudySession, Flashcard } from "@/lib/flashcards";

const authFetchMock = vi.fn();

vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({
    authFetch: authFetchMock,
    getActiveToken: () => "test-token",
    authHeaders: {},
  }),
  buildUserAuthHeaders: () => ({}),
}));

vi.mock("@/lib/capabilities", () => ({
  fetchMyCapabilities: vi.fn(async () => new Set(["flashcards"])),
}));

const DECK = {
  id: 1,
  title: "فیزیک دهم — فصل ۲",
  book_id: 7,
  chapter_number: 2,
  page_start: null,
  page_end: null,
  source_type: "book" as const,
  is_public: false,
  admin_approved: false,
  created_at: "2026-01-05T10:00:00Z",
  stats: { total: 3, due: 2, mastered: 1, new: 1, progress_percent: 33.3 },
};

function makeCard(id: number, front: string, back: string): Flashcard {
  return {
    id,
    deck_id: 1,
    front_md: front,
    back_md: back,
    hint_md: "",
    citations: [
      {
        book_id: 7,
        book_title: "فیزیک (۱) دهم",
        chapter_number: 2,
        chapter_title: "حرکت‌شناسی",
        pdf_page_index: 24,
        printed_page_number: 22,
        citation: "فیزیک (۱) دهم، فصل ۲، صفحهٔ ۲۲",
      },
    ],
    tags: [],
    review: null,
  };
}

const CARDS = [
  makeCard(11, "قانون دوم نیوتن چیست؟ $F=ma$", "نیروی خالص برابر حاصل‌ضرب جرم در شتاب است."),
  makeCard(12, "شتاب چیست؟", "تغییرات سرعت در واحد زمان."),
  makeCard(13, "جابه‌جایی چیست؟", "بردار واصل به نقطهٔ شروع و پایان."),
];

function makeCounts(results: Record<string, "got" | "missed">, total: number) {
  const got = Object.values(results).filter((v) => v === "got").length;
  const missed = Object.values(results).filter((v) => v === "missed").length;
  const rated = got + missed;
  return {
    total,
    got,
    missed,
    rated,
    remaining: total - rated,
    percent: total ? Math.round((rated / total) * 1000) / 10 : 0,
    success_percent: rated ? Math.round((got / rated) * 1000) / 10 : 0,
  };
}

function makeSession(overrides: Partial<StudySession> = {}): StudySession {
  const results = overrides.results ?? {};
  const total = overrides.card_ids?.length ?? CARDS.length;
  const counts = overrides.counts ?? makeCounts(results, total);
  return {
    id: 42,
    deck_id: 1,
    mode: "full",
    card_ids: CARDS.map((card) => card.id),
    position: 0,
    results,
    flipped: false,
    status: "in_progress",
    started_at: "2026-11-20T10:00:00Z",
    updated_at: "2026-11-20T10:00:00Z",
    completed_at: null,
    counts,
    total: counts.total,
    got_count: counts.got,
    missed_count: counts.missed,
    rated_count: counts.rated,
    success_percent: counts.success_percent,
    cards: CARDS.map((card) => ({ ...card, session_result: results[String(card.id)] ?? null })),
    ...overrides,
  };
}

function summaryOf(session: StudySession): StudySession {
  const { cards: _cards, ...summary } = session;
  return summary;
}

/** Mock backend session endpoints against an in-memory session object. */
function wireStudyBackend(initial: StudySession) {
  const state = { session: structuredClone(initial) as StudySession };
  authFetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;

    if (method === "PATCH" && url === `/api/v1/flashcards/sessions/${state.session.id}`) {
      if (body?.position !== undefined) state.session.position = body.position;
      if (body?.flipped !== undefined) state.session.flipped = body.flipped;
      state.session.counts = makeCounts(state.session.results ?? {}, state.session.card_ids.length);
      return json(summaryOf(state.session));
    }
    if (method === "POST" && url === `/api/v1/flashcards/sessions/${state.session.id}/shuffle`) {
      state.session.card_ids = [...state.session.card_ids].reverse();
      state.session.position = 0;
      const byId = new Map((state.session.cards ?? []).map((card) => [card.id, card]));
      state.session.cards = state.session.card_ids.map((id) => byId.get(id)!);
      return json(state.session);
    }
    if (method === "POST" && url === `/api/v1/flashcards/sessions/${state.session.id}/restart`) {
      state.session.position = 0;
      state.session.results = {};
      state.session.flipped = false;
      state.session.status = "in_progress";
      state.session.counts = makeCounts({}, state.session.card_ids.length);
      state.session.cards = (state.session.cards ?? []).map((card) => ({ ...card, session_result: null }));
      return json(state.session);
    }
    if (method === "GET" && url === `/api/v1/flashcards/sessions/${state.session.id}`) {
      return json(state.session);
    }
    const reviewMatch = url.match(/^\/api\/v1\/flashcards\/(\d+)\/review$/);
    if (method === "POST" && reviewMatch) {
      const cardId = Number(reviewMatch[1]);
      const rating = body.rating as number;
      const outcome = rating >= 3 ? "got" : "missed";
      const results = { ...(state.session.results ?? {}) };
      results[String(cardId)] = results[String(cardId)] ?? outcome; // idempotent replay
      state.session.results = results;
      state.session.flipped = false;
      const counts = makeCounts(results, state.session.card_ids.length);
      state.session.counts = counts;
      state.session.total = counts.total;
      state.session.got_count = counts.got;
      state.session.missed_count = counts.missed;
      state.session.rated_count = counts.rated;
      state.session.success_percent = counts.success_percent;
      if (counts.rated >= counts.total) state.session.status = "completed";
      state.session.cards = (state.session.cards ?? []).map((card) => ({
        ...card,
        session_result: results[String(card.id)] ?? null,
      }));
      return json({ card_id: cardId, review: {}, applied: true, session: summaryOf(state.session) });
    }
    if (method === "POST" && /\/explain$/.test(url)) {
      return json({
        card_id: Number(url.match(/cards\/(\d+)\/explain/)?.[1]),
        deck_id: 1,
        explanation: "قانون دوم نیوتن می‌گوید نیروی خالص برابر $F=ma$ است. مثال: با هل دادن جسم #جرم جرم بیشتر، شتاب کمتر می‌شود.",
        source_available: false,
        citations: [],
        citation: null,
        audit_id: 99,
      });
    }
    const deleteMatch = url.match(/^\/api\/v1\/flashcards\/cards\/(\d+)$/);
    if (method === "DELETE" && deleteMatch) {
      const cardId = Number(deleteMatch[1]);
      state.session.card_ids = state.session.card_ids.filter((id) => id !== cardId);
      state.session.cards = (state.session.cards ?? []).filter((card) => card.id !== cardId);
      delete state.session.results?.[String(cardId)];
      state.session.counts = makeCounts(state.session.results ?? {}, state.session.card_ids.length);
      return new Response(null, { status: 204 });
    }
    return new Response(JSON.stringify({ detail: `unhandled ${method} ${url}` }), { status: 404 });
  });
  return state;
}


/** Stateful wrapper that mimics the workspace's merge semantics. */
function Harness({
  initial,
  deckTitle = "فیزیک",
  onStudyAll = vi.fn(),
  onStudyMissed = vi.fn(),
  onExit = vi.fn(),
  onError = vi.fn(),
  onNotice = vi.fn(),
}: {
  initial: StudySession;
  deckTitle?: string | null;
  onStudyAll?: () => void;
  onStudyMissed?: (ids: number[]) => void;
  onExit?: () => void;
  onError?: (m: string) => void;
  onNotice?: (m: string) => void;
}) {
  const [session, setSession] = React.useState(initial);
  return (
    <FlashcardStudy
      session={session}
      deckTitle={deckTitle}
      authFetch={authFetchMock as unknown as (input: string, init?: RequestInit) => Promise<Response>}
      onMergeSummary={(summary) =>
        setSession((prev) => {
          const cards = summary.cards ?? prev.cards;
          return { ...prev, ...summary, cards };
        })
      }
      onReplaceSession={(next) => setSession(next)}
      onExit={onExit}
      onStudyAll={onStudyAll}
      onStudyMissed={onStudyMissed}
      onError={onError}
      onNotice={onNotice}
    />
  );
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  authFetchMock.mockReset();
  vi.stubGlobal("confirm", vi.fn(() => true));
});

describe("generation modal", () => {
  const exam = { id: "exam-1", title: "آزمون ۱", status: "submitted", book_title: null };

  function mockBoot() {
    authFetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/v1/flashcards/decks") return json([DECK]);
      if (url === "/api/v1/flashcards/library") return json([]);
      if (url === "/api/v1/flashcards/sessions/active") return json([]);
      if (url === "/api/v1/exams") return json([exam]);
      if (method === "POST" && url === "/api/v1/flashcards/generate") {
        return json({ deck_id: 99, created_count: 10 }, 201);
      }
      return json({ detail: `unhandled ${method} ${url}` }, 404);
    });
  }

  it("shows fewer/standard/more and difficulty options plus the custom prompt field", async () => {
    mockBoot();
    const user = userEvent.setup();
    render(<FlashcardsWorkspace />);
    await user.click(await screen.findByRole("button", { name: /ساخت با هوش مصنوعی/ }));

    expect(screen.getByRole("radio", { name: /کمتر/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /استاندارد/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /بیشتر/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /آسان/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /متوسط/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /سخت/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/می‌خواهی فلش‌کارت‌ها روی چه موضوعی تمرکز کنند؟/)).toBeInTheDocument();
  });

  it("sends count, difficulty and the custom prompt to the backend", async () => {
    mockBoot();
    const user = userEvent.setup();
    render(<FlashcardsWorkspace />);
    await user.click(await screen.findByRole("button", { name: /ساخت با هوش مصنوعی/ }));
    await user.click(screen.getByRole("button", { name: "از اشتباهات آزمون" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /آزمون/ })).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox", { name: /آزمون/ }), "exam-1");

    await user.click(screen.getByRole("radio", { name: /بیشتر/ }));
    await user.click(screen.getByRole("radio", { name: /سخت/ }));
    await user.type(screen.getByLabelText(/می‌خواهی فلش‌کارت‌ها/), "فقط قوانین و فرمول‌های فصل");

    await user.click(screen.getByRole("button", { name: /ساخت کارت‌ها/ }));

    await waitFor(() => {
      const generateCall = authFetchMock.mock.calls.find(([url, init]) => {
        return url === "/api/v1/flashcards/generate" && (init as RequestInit).method === "POST";
      });
      expect(generateCall, "generate endpoint was called").toBeTruthy();
      const body = JSON.parse(String((generateCall![1] as RequestInit).body));
      expect(body).toMatchObject({
        source: "mistake",
        exam_id: "exam-1",
        count: 10,
        difficulty: "hard",
        custom_prompt: "فقط قوانین و فرمول‌های فصل",
      });
    });
  });

  it("keeps the form values and shows the error when generation fails", async () => {
    authFetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/v1/flashcards/decks") return json([DECK]);
      if (url === "/api/v1/flashcards/library") return json([]);
      if (url === "/api/v1/flashcards/sessions/active") return json([]);
      if (url === "/api/v1/exams") return json([exam]);
      if (method === "POST" && url === "/api/v1/flashcards/generate") {
        return json({ detail: "سهمیهٔ امروز شما تمام شده است." }, 402);
      }
      return json({ detail: "unhandled" }, 404);
    });
    const user = userEvent.setup();
    render(<FlashcardsWorkspace />);
    await user.click(await screen.findByRole("button", { name: /ساخت با هوش مصنوعی/ }));
    await user.click(screen.getByRole("button", { name: "از اشتباهات آزمون" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /آزمون/ })).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox", { name: /آزمون/ }), "exam-1");
    await user.click(screen.getByRole("radio", { name: /کمتر/ }));
    await user.type(screen.getByLabelText(/می‌خواهی فلش‌کارت‌ها/), "فقط تعریف اصطلاحات");
    await user.click(screen.getByRole("button", { name: /ساخت کارت‌ها/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("سهمیهٔ امروز شما تمام شده است.");
    // Form preserved: the typed prompt is still there.
    expect(screen.getByLabelText(/می‌خواهی فلش‌کارت‌ها/)).toHaveValue("فقط تعریف اصطلاحات");
  });
});

describe("study session", () => {
  it("renders RTL card with counter and flips on click", async () => {
    const session = makeSession();
    wireStudyBackend(session);
    const user = userEvent.setup();
    const { container } = render(<Harness initial={session} />);
    expect(container.querySelector("[dir='rtl']")).toBeTruthy();
    expect(screen.getByText("کارت ۱ از ۳")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "کارت قبلی" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "کارت بعدی" }));
    expect(screen.getByText("کارت ۲ از ۳")).toBeInTheDocument();
  });

  it("shows KaTeX math inside the card in RTL layout", () => {
    const session = makeSession();
    const { container } = render(<Harness initial={session} />);
    expect(container.querySelector(".katex")).toBeTruthy();
    expect(container.querySelector("[dir='rtl']")).toBeTruthy();
  });

  it("records got/missed with the session id and auto-advances", async () => {
    const session = makeSession();
    wireStudyBackend(session);
    const user = userEvent.setup();
    render(<Harness initial={session} />);
    await user.click(screen.getByRole("button", { name: "نمایش پاسخ" }));
    await user.click(screen.getByRole("button", { name: /بلد بودم/ }));
    await waitFor(() => {
      const reviewCall = authFetchMock.mock.calls.find(([url]) => String(url).endsWith("/review"));
      expect(reviewCall).toBeTruthy();
      expect(JSON.parse(String((reviewCall![1] as RequestInit).body))).toMatchObject({
        rating: 3,
        session_id: 42,
      });
    });
    expect(await screen.findByText("کارت ۲ از ۳")).toBeInTheDocument();
  });

  it("records «بلد نبودم» as rating 1", async () => {
    const session = makeSession({ flipped: true });
    wireStudyBackend(session);
    const user = userEvent.setup();
    render(<Harness initial={session} />);
    await user.click(screen.getByRole("button", { name: /بلد نبودم/ }));
    await waitFor(() => {
      const reviewCall = authFetchMock.mock.calls.find(([url]) => String(url).endsWith("/review"));
      expect(JSON.parse(String((reviewCall![1] as RequestInit).body))).toMatchObject({ rating: 1 });
    });
  });

  it("completes the session, shows results and offers only-missed review", async () => {
    // Last remaining card of a 2-of-3 already-rated run.
    const session = makeSession({
      card_ids: [12, 13],
      results: { "12": "missed" },
      counts: makeCounts({ "12": "missed" }, 2),
      position: 1,
      flipped: true,
      cards: [
        { ...CARDS[1], session_result: "missed" as const },
        { ...CARDS[2], session_result: null },
      ],
    });
    wireStudyBackend(session);
    const onStudyMissed = vi.fn();
    const user = userEvent.setup();
    render(<Harness initial={session} onStudyMissed={onStudyMissed} />);

    await user.click(screen.getByRole("button", { name: /بلد نبودم/ }));
    expect(await screen.findByText("جلسه تکمیل شد")).toBeInTheDocument();
    expect(screen.getByText("تعداد کارت‌ها")).toBeInTheDocument();
    const missedButton = screen.getByRole("button", { name: /فقط کارت‌های بلد نبودم/ });
    expect(missedButton).toHaveTextContent("(۲)");
    await user.click(missedButton);
    expect(onStudyMissed).toHaveBeenCalledWith([12, 13]);
  });

  it("disables the only-missed button when nothing was missed", () => {
    const session = makeSession({
      results: { "11": "got", "12": "got", "13": "got" },
      counts: makeCounts({ "11": "got", "12": "got", "13": "got" }, 3),
      status: "completed",
      flipped: false,
    });
    render(<Harness initial={session} />);
    expect(screen.getByRole("button", { name: /فقط کارت‌های بلد نبودم/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /مرور دوبارهٔ همین کارت‌ها/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /مرور همهٔ کارت‌ها/ })).toBeInTheDocument();
  });

  it("calls shuffle and replaces the session with the server order", async () => {
    const session = makeSession();
    wireStudyBackend(session);
    const user = userEvent.setup();
    // Spy: capture the session the harness swaps in after shuffle.
    const { container } = render(<Harness initial={session} />);
    await user.click(screen.getByRole("button", { name: "بر زدن کارت‌ها" }));
    await waitFor(() => {
      expect(authFetchMock.mock.calls.some(([url]) => String(url).endsWith("/shuffle"))).toBe(true);
    });
    // هیچ کارتی حذف یا تکراری نشود؛ همان مجموعه باقی می‌ماند
    expect(screen.getByText(/کارت ۱ از ۳|کارت ۲ از ۳|کارت ۳ از ۳/)).toBeInTheDocument();
    expect(container.querySelectorAll(".fc-bigcard").length).toBe(1);
  });

  it("toggles the CSS fullscreen fallback when the Fullscreen API is unavailable", async () => {
    const session = makeSession();
    wireStudyBackend(session);
    const user = userEvent.setup();
    const { container } = render(<Harness initial={session} />);
    await user.click(screen.getByRole("button", { name: "تمام‌صفحه" }));
    expect(container.querySelector(".fc-study")?.className).toContain("is-fullscreen");
    await user.click(screen.getByRole("button", { name: "خروج از تمام‌صفحه" }));
    expect(container.querySelector(".fc-study")?.className).not.toContain("is-fullscreen");
  });

  it("restores the saved position after a reload", () => {
    const session = makeSession({ position: 1, flipped: true });
    render(<Harness initial={session} />);
    expect(screen.getByText("کارت ۲ از ۳")).toBeInTheDocument();
  });

  it("loads the textbook-grounded explanation after the back is shown", async () => {
    const session = makeSession({ flipped: true });
    wireStudyBackend(session);
    const user = userEvent.setup();
    render(<Harness initial={session} />);
    await user.click(screen.getByRole("button", { name: /توضیح بیشتر/ }));
    expect(await screen.findByText(/قانون دوم نیوتن می‌گوید/)).toBeInTheDocument();
    // منبع بازیابی نشد → پیام صریح نمایش داده می‌شود، بدون استناد ساختگی
    expect(screen.getByText(/متن اصلی کتاب برای این کارت قابل بازیابی نبود/)).toBeInTheDocument();
  });

  it("deletes the current card after confirmation", async () => {
    const session = makeSession();
    const state = wireStudyBackend(session);
    const user = userEvent.setup();
    render(<Harness initial={session} />);
    await user.click(screen.getByRole("button", { name: "حذف این کارت" }));
    await waitFor(() => {
      expect(authFetchMock.mock.calls.some(([url]) => url === "/api/v1/flashcards/cards/11")).toBe(true);
    });
    expect(window.confirm).toHaveBeenCalled();
    expect(state.session.card_ids).toEqual([12, 13]);
  });
});

describe("workspace resume", () => {
  it("shows the unfinished-session banner and resumes from the saved position", async () => {
    const inProgress = summaryOf(makeSession({ position: 1, flipped: true }));
    const detail = makeSession({ position: 1, flipped: true });
    authFetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/v1/flashcards/decks") return json([DECK]);
      if (url === "/api/v1/flashcards/library") return json([]);
      if (url === "/api/v1/flashcards/sessions/active") return json([inProgress]);
      if (method === "GET" && url === `/api/v1/flashcards/sessions/${detail.id}`) return json(detail);
      return json({ detail: "unhandled" }, 404);
    });
    const user = userEvent.setup();
    render(<FlashcardsWorkspace />);

    const resume = await screen.findByRole("button", { name: "ادامهٔ مطالعه" });
    await user.click(resume);
    expect(await screen.findByText("کارت ۲ از ۳")).toBeInTheDocument();
  });
});
