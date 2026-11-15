"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp, AudioLines, BookOpen, Check, ChevronDown, CircleHelp, Clock3,
  Coins, Crown, FileImage, GraduationCap, LoaderCircle, LogIn, LogOut, Menu,
  MessageSquare, Mic, Paperclip, Phone, Plus, ReceiptText, Send, ShieldCheck,
  Sparkles, Square, Trash2, Wallet, X, Zap,
} from "lucide-react";
import ExamRunner from "@/components/ExamRunner";
import MathContent from "@/components/MathContent";
import type {
  BookOption,
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  Exam,
  ExamSummary,
  GradeOption,
  MajorOption,
  PaymentTransactionItem,
  PublicPlansPayload,
  Source,
  StudentUser,
  TokenUsageLogItem,
  TutorMode,
  TutorResponse,
} from "@/lib/types";

const USER_TOKEN_KEY = "iran_tutor_user_token";

function readStoredUserToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(USER_TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeUserToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.sessionStorage.setItem(USER_TOKEN_KEY, token);
    } else {
      window.sessionStorage.removeItem(USER_TOKEN_KEY);
    }
  } catch {
    // ignore storage restriction inside restricted iframes
  }
}

function buildUserAuthHeaders(token: string | null): Record<string, string> {
  if (!token) return {};
  return {
    Authorization: `Bearer ${token}`,
    "X-User-Token": token,
  };
}

function errorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") return payload.detail;
  return fallback;
}

function sourceText(source: Source) {
  return source.citation ?? [
    source.book_title,
    source.chapter_number ? `فصل ${source.chapter_number}` : source.chapter_title,
    source.printed_page_number ? `صفحهٔ ${source.printed_page_number}` : null,
  ].filter(Boolean).join(" · ");
}

function formatFaDate(iso: string | null) {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  try {
    return new Intl.DateTimeFormat("fa-IR", { dateStyle: "short", timeStyle: "short" }).format(ms);
  } catch {
    return "";
  }
}

function formatFaNumber(value: number) {
  try {
    return new Intl.NumberFormat("fa-IR").format(value);
  } catch {
    return String(value);
  }
}

function makeChatTitle(text: string) {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return "گفت‌وگو با معلم";
  return clean.length > 44 ? `${clean.slice(0, 44)}…` : clean;
}

function actionLabel(action: string): string {
  switch (action) {
    case "tutor_ask":
      return "پرسش متنی از معلم";
    case "tutor_image":
      return "حل تمرین تصویری";
    case "tutor_audio":
      return "پرسش صوتی";
    case "exam_create":
      return "طراحی آزمون زمان‌دار";
    default:
      return action;
  }
}

export default function StudentApp() {
  const [grades, setGrades] = useState<GradeOption[]>([]);
  const [majors, setMajors] = useState<MajorOption[]>([]);
  const [books, setBooks] = useState<BookOption[]>([]);
  const [gradeNumber, setGradeNumber] = useState<number | null>(null);
  const [majorCode, setMajorCode] = useState("");
  const [bookId, setBookId] = useState("");
  const [curriculumError, setCurriculumError] = useState("");
  const [demoMode, setDemoMode] = useState(false);

  // Phase 6: Student Auth & Plans
  const userTokenRef = useRef<string | null>(null);
  const [userTokenState, setUserTokenState] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [currentUser, setCurrentUser] = useState<StudentUser | null>(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authStep, setAuthStep] = useState<"phone" | "otp">("phone");
  const [phoneInput, setPhoneInput] = useState("");
  const [fullNameInput, setFullNameInput] = useState("");
  const [otpInput, setOtpInput] = useState("");
  const [normalizedPhone, setNormalizedPhone] = useState("");
  const [demoOtpHint, setDemoOtpHint] = useState<string | null>(null);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");

  const [plansPayload, setPlansPayload] = useState<PublicPlansPayload | null>(null);
  const [plansModalOpen, setPlansModalOpen] = useState(false);
  const [plansTab, setPlansTab] = useState<"plans" | "usage">("plans");
  const [checkoutBusyCode, setCheckoutBusyCode] = useState<string | null>(null);
  const [plansFeedback, setPlansFeedback] = useState("");
  const [plansError, setPlansError] = useState("");
  const [usageLogs, setUsageLogs] = useState<TokenUsageLogItem[]>([]);
  const [paymentTxs, setPaymentTxs] = useState<PaymentTransactionItem[]>([]);
  const [usageLoading, setUsageLoading] = useState(false);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatSessionSummary[]>([]);
  const [examHistory, setExamHistory] = useState<ExamSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [messageError, setMessageError] = useState("");
  const [tutoringMode, setTutoringMode] = useState<TutorMode>("tutor");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [examSetupOpen, setExamSetupOpen] = useState(false);
  const [examHistoryOpen, setExamHistoryOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [examType, setExamType] = useState<"konkoor" | "final">("konkoor");
  const [questionCount, setQuestionCount] = useState(5);
  const [timeLimit, setTimeLimit] = useState(15);
  const [activeExam, setActiveExam] = useState<Exam | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioChunks = useRef<BlobPart[]>([]);

  const getActiveToken = useCallback((): string | null => {
    return userTokenRef.current ?? readStoredUserToken();
  }, []);

  const setActiveToken = useCallback((token: string | null) => {
    userTokenRef.current = token;
    setUserTokenState(token);
    storeUserToken(token);
  }, []);

  const currentGrade = grades.find((grade) => grade.number === gradeNumber);
  const selectedBook = books.find((book) => String(book.id) === bookId);
  const hasMajor = currentGrade?.has_major ?? false;
  const canAsk = Boolean(bookId && !busy);

  const openLoginModal = useCallback((notice?: string) => {
    setAuthError(notice ?? "");
    setAuthStep("phone");
    setOtpInput("");
    setDemoOtpHint(null);
    setAuthModalOpen(true);
  }, []);

  const refreshAccount = useCallback(async () => {
    const token = getActiveToken();
    try {
      const response = await fetch("/api/v1/auth/me", {
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(token),
      });
      if (!response.ok) return null;
      const payload = (await response.json()) as { authenticated?: boolean; user?: StudentUser | null };
      if (payload.authenticated && payload.user) {
        setCurrentUser(payload.user);
        return payload.user;
      }
      setCurrentUser(null);
      setActiveToken(null);
      return null;
    } catch {
      return null;
    }
  }, [getActiveToken, setActiveToken]);

  const loadChatHistory = useCallback(async (tokenOverride?: string | null) => {
    const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
    if (!token && !currentUser) return;
    try {
      const response = await fetch("/api/v1/tutor/sessions", {
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(token),
      });
      if (!response.ok) return;
      const items = (await response.json()) as ChatSessionSummary[];
      setChatHistory(items);
    } catch {
      // Ignore silent history fetch failure
    }
  }, [currentUser, getActiveToken]);

  const loadExamHistory = useCallback(async (tokenOverride?: string | null) => {
    const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
    if (!token && !currentUser) return;
    try {
      const response = await fetch("/api/v1/exams", {
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(token),
      });
      if (!response.ok) return;
      const items = (await response.json()) as ExamSummary[];
      setExamHistory(items);
    } catch {
      // Ignore silent history fetch failure
    }
  }, [currentUser, getActiveToken]);

  const loadUsageDetails = useCallback(async () => {
    const token = getActiveToken();
    if (!token) return;
    setUsageLoading(true);
    try {
      const response = await fetch("/api/v1/plans/usage", {
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(token),
      });
      if (!response.ok) return;
      const data = (await response.json()) as {
        user?: StudentUser;
        logs?: TokenUsageLogItem[];
        transactions?: PaymentTransactionItem[];
      };
      if (data.user) setCurrentUser(data.user);
      if (data.logs) setUsageLogs(data.logs);
      if (data.transactions) setPaymentTxs(data.transactions);
    } catch {
      // Ignore silent usage failure
    } finally {
      setUsageLoading(false);
    }
  }, [getActiveToken]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [gradeResponse, majorResponse] = await Promise.all([
          fetch("/api/v1/curriculum/grades"),
          fetch("/api/v1/curriculum/majors"),
        ]);
        if (!gradeResponse.ok || !majorResponse.ok) throw new Error("کتابخانهٔ آموزشی در دسترس نیست");
        const gradeData = (await gradeResponse.json()) as GradeOption[];
        const majorData = (await majorResponse.json()) as MajorOption[];
        if (cancelled) return;
        setGrades(gradeData);
        setMajors(majorData);
        setGradeNumber(gradeData.find((item) => item.number === 12)?.number ?? gradeData[0]?.number ?? null);
      } catch (error) {
        if (!cancelled) setCurriculumError(error instanceof Error ? error.message : "خطا در دریافت فهرست کتاب‌ها");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let active = true;
    const storedToken = getActiveToken();

    fetch("/api/v1/system/status")
      .then((response) => (response.ok ? response.json() : null))
      .then((status: { mode?: string } | null) => {
        if (active) setDemoMode(status?.mode === "demo");
      })
      .catch(() => {
        if (active) setDemoMode(false);
      });

    fetch("/api/v1/plans", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((plansData: PublicPlansPayload | null) => {
        if (active && plansData) setPlansPayload(plansData);
      })
      .catch(() => undefined);

    fetch("/api/v1/auth/me", {
      cache: "no-store",
      credentials: "same-origin",
      headers: buildUserAuthHeaders(storedToken),
    })
      .then((response) => (response.ok ? response.json() : null))
      .then(async (payload: { authenticated?: boolean; user?: StudentUser | null } | null) => {
        if (!active) return;
        if (payload?.authenticated && payload.user) {
          if (storedToken) setActiveToken(storedToken);
          setCurrentUser(payload.user);
          setAuthReady(true);
          await Promise.all([
            fetch("/api/v1/tutor/sessions", {
              cache: "no-store",
              credentials: "same-origin",
              headers: buildUserAuthHeaders(storedToken),
            })
              .then((r) => (r.ok ? r.json() : null))
              .then((items: ChatSessionSummary[] | null) => {
                if (active && items) setChatHistory(items);
              }),
            fetch("/api/v1/exams", {
              cache: "no-store",
              credentials: "same-origin",
              headers: buildUserAuthHeaders(storedToken),
            })
              .then((r) => (r.ok ? r.json() : null))
              .then((items: ExamSummary[] | null) => {
                if (active && items) setExamHistory(items);
              }),
          ]);

          // Handle optional payment callback query parameters
          const params = new URLSearchParams(window.location.search);
          const authority = params.get("Authority");
          const paymentTx = params.get("payment_tx");
          const paymentStatus = params.get("Status");
          if (authority) {
            fetch("/api/v1/plans/verify", {
              method: "POST",
              credentials: "same-origin",
              headers: {
                "Content-Type": "application/json",
                ...buildUserAuthHeaders(storedToken),
              },
              body: JSON.stringify({
                authority,
                transaction_id: paymentTx,
                status: paymentStatus,
              }),
            })
              .then(async (r) => {
                const verifyData = (await r.json().catch(() => ({}))) as { user?: StudentUser; detail?: string };
                if (!active) return;
                if (r.ok && verifyData.user) {
                  setCurrentUser(verifyData.user);
                  setPlansFeedback("پرداخت با موفقیت تأیید شد و اعتبار توکن شما شارژ گردید.");
                  setPlansModalOpen(true);
                } else if (verifyData.detail) {
                  setPlansError(verifyData.detail);
                  setPlansModalOpen(true);
                }
                window.history.replaceState({}, "", window.location.pathname);
              })
              .catch(() => undefined);
          }
        } else {
          setCurrentUser(null);
          setActiveToken(null);
          setAuthReady(true);
        }
      })
      .catch(() => {
        if (active) {
          setCurrentUser(null);
          setAuthReady(true);
        }
      });

    return () => { active = false; };
  }, [getActiveToken, setActiveToken]);

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = window.setInterval(() => {
      setResendCooldown((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [resendCooldown]);

  useEffect(() => {
    if (!gradeNumber || (hasMajor && !majorCode)) return;
    const controller = new AbortController();
    const query = new URLSearchParams({ grade_number: String(gradeNumber) });
    if (hasMajor) query.set("major_code", majorCode);
    fetch(`/api/v1/curriculum/books?${query.toString()}`, { signal: controller.signal })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(errorMessage(payload, "کتابی برای این انتخاب پیدا نشد"));
        setBooks(payload as BookOption[]);
        setCurriculumError("");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setCurriculumError(error instanceof Error ? error.message : "خطا در دریافت کتاب‌ها");
      });
    return () => controller.abort();
  }, [gradeNumber, majorCode, hasMajor]);

  const clearAttachments = useCallback(() => {
    setImageFile(null);
    setAudioFile(null);
    if (imageInputRef.current) imageInputRef.current.value = "";
  }, []);

  const resetChat = useCallback(() => {
    setMessages([]);
    setActiveChatId(null);
    setDraft("");
    setMessageError("");
    clearAttachments();
    setSidebarOpen(false);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [clearAttachments]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        resetChat();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [resetChat]);

  useEffect(() => {
    if (!messages.length && !busy) return;
    document.getElementById("message-end")?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  const handleRequestOtp = async (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!phoneInput.trim()) {
      setAuthError("لطفاً شماره موبایل خود را وارد کنید.");
      return;
    }
    setAuthBusy(true);
    setAuthError("");
    try {
      const response = await fetch("/api/v1/auth/request-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number: phoneInput.trim() }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        detail?: string;
        phone_number?: string;
        resend_after_seconds?: number;
        demo_code?: string;
      };
      if (!response.ok) throw new Error(payload.detail ?? "ارسال کد تأیید انجام نشد.");
      setNormalizedPhone(payload.phone_number ?? phoneInput.trim());
      setDemoOtpHint(payload.demo_code ?? null);
      setResendCooldown(payload.resend_after_seconds ?? 60);
      setAuthStep("otp");
      setOtpInput("");
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "خطا در ارسال پیامک");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleVerifyOtp = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!otpInput.trim()) {
      setAuthError("کد تأیید ۶ رقمی را وارد کنید.");
      return;
    }
    setAuthBusy(true);
    setAuthError("");
    try {
      const response = await fetch("/api/v1/auth/verify-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          phone_number: normalizedPhone || phoneInput.trim(),
          code: otpInput.trim(),
          full_name: fullNameInput.trim() || null,
        }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        detail?: string;
        authenticated?: boolean;
        token?: string;
        user?: StudentUser;
      };
      if (!response.ok || !payload.authenticated || !payload.token || !payload.user) {
        throw new Error(payload.detail ?? "کد تأیید نادرست است.");
      }
      setActiveToken(payload.token);
      setCurrentUser(payload.user);
      setAuthModalOpen(false);
      setMessageError("");
      setOtpInput("");
      setDemoOtpHint(null);
      await Promise.all([loadChatHistory(payload.token), loadExamHistory(payload.token)]);
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "خطا در تأیید کد");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogout = async () => {
    const token = getActiveToken();
    await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: buildUserAuthHeaders(token),
    }).catch(() => undefined);
    setActiveToken(null);
    setCurrentUser(null);
    setChatHistory([]);
    setExamHistory([]);
    setActiveExam(null);
    resetChat();
  };

  const openPlansModal = useCallback(async (tab: "plans" | "usage" = "plans") => {
    setPlansTab(tab);
    setPlansError("");
    setPlansFeedback("");
    setPlansModalOpen(true);
    setSidebarOpen(false);
    fetch("/api/v1/plans", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: PublicPlansPayload | null) => {
        if (data) setPlansPayload(data);
      })
      .catch(() => undefined);
    if (getActiveToken()) {
      await loadUsageDetails();
    }
  }, [getActiveToken, loadUsageDetails]);

  const handleCheckoutPlan = async (planCode: string) => {
    const token = getActiveToken();
    if (!token || !currentUser) {
      setPlansModalOpen(false);
      openLoginModal("برای خرید یا فعال‌سازی پلن، ابتدا با شماره موبایل وارد شوید.");
      return;
    }
    setCheckoutBusyCode(planCode);
    setPlansError("");
    setPlansFeedback("");
    try {
      const response = await fetch("/api/v1/plans/checkout", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          ...buildUserAuthHeaders(token),
        },
        body: JSON.stringify({ plan_code: planCode }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        detail?: string;
        status?: string;
        payment_url?: string;
        user?: StudentUser;
        plan?: { name: string };
      };
      if (response.status === 401) {
        setPlansModalOpen(false);
        openLoginModal("نشست شما منقضی شده است؛ لطفاً دوباره وارد شوید.");
        return;
      }
      if (!response.ok) throw new Error(payload.detail ?? "خطا در شروع خرید پلن");
      if (payload.status === "redirect" && payload.payment_url) {
        window.location.assign(payload.payment_url);
        return;
      }
      if (payload.user) {
        setCurrentUser(payload.user);
      }
      setPlansFeedback(`پلن «${payload.plan?.name ?? ""}» با موفقیت فعال شد و سهمیه توکن شما شارژ گردید.`);
      setMessageError("");
      await loadUsageDetails();
    } catch (cause) {
      setPlansError(cause instanceof Error ? cause.message : "خطا در فعال‌سازی پلن");
    } finally {
      setCheckoutBusyCode(null);
    }
  };

  const persistConversation = useCallback(
    async (
      existingSessionId: string | null,
      nextMessages: ChatMessage[],
      firstPrompt: string,
      selectedGrade: number,
      selectedMajor: string | null,
      selectedBookId: number,
      mode: TutorMode
    ) => {
      const token = getActiveToken();
      if (!token) return existingSessionId;
      try {
        if (existingSessionId) {
          const response = await fetch(`/api/v1/tutor/sessions/${existingSessionId}`, {
            method: "PUT",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json",
              ...buildUserAuthHeaders(token),
            },
            body: JSON.stringify({ mode, messages: nextMessages }),
          });
          if (response.ok) {
            await loadChatHistory(token);
            return existingSessionId;
          }
        }
        const response = await fetch("/api/v1/tutor/sessions", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            ...buildUserAuthHeaders(token),
          },
          body: JSON.stringify({
            book_id: selectedBookId,
            grade_number: selectedGrade,
            major_code: selectedMajor,
            mode,
            title: makeChatTitle(firstPrompt),
            messages: nextMessages,
          }),
        });
        if (!response.ok) return existingSessionId;
        const created = (await response.json()) as ChatSessionDetail;
        setActiveChatId(created.id);
        await loadChatHistory(token);
        return created.id;
      } catch {
        return existingSessionId;
      }
    },
    [getActiveToken, loadChatHistory]
  );

  const sendMessage = useCallback(async () => {
    const query = draft.trim();
    if ((!query && !imageFile && !audioFile) || !bookId || gradeNumber === null || busy) return;

    const token = getActiveToken();
    if (!currentUser || !token) {
      openLoginModal("برای پرسش از معلم، ابتدا با شماره موبایل خود وارد شوید.");
      return;
    }

    const attachment = imageFile?.name ?? audioFile?.name;
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: query || (imageFile ? "این سؤال را از روی تصویر حل کن." : "این سؤال را از روی صدا پاسخ بده."),
      attachment,
    };
    const priorMessages = messages;
    const withUser = [...priorMessages, userMessage];
    setMessages(withUser);
    setDraft("");
    setMessageError("");
    setBusy(true);
    try {
      const response = await (imageFile || audioFile
        ? (async () => {
            const form = new FormData();
            form.set(imageFile ? "image" : "audio", imageFile ?? (audioFile as File));
            form.set("grade_number", String(gradeNumber));
            form.set("book_id", bookId);
            form.set("mode", tutoringMode);
            if (hasMajor && majorCode) form.set("major_code", majorCode);
            const endpoint = imageFile ? "/api/v1/tutor/ask-image" : "/api/v1/tutor/ask-audio";
            return fetch(endpoint, {
              method: "POST",
              credentials: "same-origin",
              headers: buildUserAuthHeaders(token),
              body: form,
            });
          })()
        : fetch("/api/v1/tutor/ask", {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json",
              ...buildUserAuthHeaders(token),
            },
            body: JSON.stringify({
              query,
              grade_number: gradeNumber,
              major_code: hasMajor ? majorCode : null,
              book_id: Number(bookId),
              mode: tutoringMode,
            }),
          }));
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401) {
        setMessages(priorMessages);
        setCurrentUser(null);
        setActiveToken(null);
        openLoginModal(errorMessage(payload, "لطفاً دوباره وارد حساب خود شوید."));
        return;
      }
      if (response.status === 402) {
        setMessages(priorMessages);
        setMessageError(errorMessage(payload, "اعتبار توکن شما به پایان رسیده است."));
        void refreshAccount();
        void openPlansModal("plans");
        return;
      }
      if (!response.ok) throw new Error(errorMessage(payload, "پاسخی دریافت نشد. دوباره تلاش کن."));

      const result = payload as TutorResponse;
      const detail = result.recognized_question ? `صورت سؤال خوانده‌شده: ${result.recognized_question}\n\n${result.answer}`
        : result.transcript ? `متن تشخیص‌داده‌شده: ${result.transcript}\n\n${result.answer}`
        : result.answer;
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: detail,
        sources: result.sources,
      };
      const fullThread = [...withUser, assistantMessage];
      setMessages(fullThread);
      if (result.usage) {
        setCurrentUser((prev) =>
          prev
            ? {
                ...prev,
                tokens_remaining: result.usage!.tokens_remaining,
                tokens_used_total: prev.tokens_used_total + result.usage!.total_tokens,
                tokens_used_today: prev.tokens_used_today + result.usage!.total_tokens,
              }
            : prev
        );
      }
      if (result.uncertain_parts?.length) setMessageError(`بخش‌های نامطمئن تصویر: ${result.uncertain_parts.join("، ")}`);
      clearAttachments();
      await persistConversation(
        activeChatId,
        fullThread,
        userMessage.content,
        gradeNumber,
        hasMajor ? majorCode : null,
        Number(bookId),
        tutoringMode
      );
    } catch (error) {
      setMessageError(error instanceof Error ? error.message : "ارتباط با معلم برقرار نشد");
    } finally {
      setBusy(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [
    activeChatId,
    audioFile,
    bookId,
    busy,
    clearAttachments,
    currentUser,
    draft,
    getActiveToken,
    gradeNumber,
    hasMajor,
    imageFile,
    majorCode,
    messages,
    openLoginModal,
    openPlansModal,
    persistConversation,
    refreshAccount,
    setActiveToken,
    tutoringMode,
  ]);

  const openChatSession = async (sessionId: string) => {
    const token = getActiveToken();
    if (!token) {
      openLoginModal();
      return;
    }
    setMessageError("");
    try {
      const response = await fetch(`/api/v1/tutor/sessions/${sessionId}`, {
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(token),
      });
      if (!response.ok) throw new Error("گفت‌وگو پیدا نشد");
      const detail = (await response.json()) as ChatSessionDetail;
      setGradeNumber(detail.grade_number);
      setMajorCode(detail.major_code === "general" ? "" : detail.major_code);
      setBookId(String(detail.book_id));
      setTutoringMode(detail.mode);
      setMessages(detail.messages ?? []);
      setActiveChatId(detail.id);
      clearAttachments();
      setSidebarOpen(false);
    } catch (error) {
      setMessageError(error instanceof Error ? error.message : "بازکردن گفت‌وگو انجام نشد");
    }
  };

  const deleteChatSession = async (sessionId: string) => {
    const token = getActiveToken();
    if (!token) return;
    try {
      const response = await fetch(`/api/v1/tutor/sessions/${sessionId}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(token),
      });
      if (!response.ok) return;
      setChatHistory((prev) => prev.filter((item) => item.id !== sessionId));
      if (activeChatId === sessionId) {
        resetChat();
      }
    } catch {
      // Ignore silent delete error
    }
  };

  const openExamHistory = async () => {
    const token = getActiveToken();
    if (!currentUser || !token) {
      setSidebarOpen(false);
      openLoginModal("برای مشاهده و شرکت در آزمون‌ها، ابتدا وارد شوید.");
      return;
    }
    setSidebarOpen(false);
    setExamHistoryOpen(true);
    setHistoryLoading(true);
    await loadExamHistory(token);
    setHistoryLoading(false);
  };

  const openSavedExam = async (examId: string) => {
    const token = getActiveToken();
    if (!token) {
      openLoginModal();
      return;
    }
    setBusy(true);
    setMessageError("");
    try {
      const response = await fetch(`/api/v1/exams/${examId}`, {
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(token),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload, "دریافت آزمون انجام نشد"));
      setActiveExam(payload as Exam);
      setExamHistoryOpen(false);
    } catch (error) {
      setMessageError(error instanceof Error ? error.message : "دریافت آزمون انجام نشد");
    } finally {
      setBusy(false);
    }
  };

  const startRecording = async () => {
    if (recording) {
      recorderRef.current?.stop();
      setRecording(false);
      return;
    }
    if (!currentUser || !getActiveToken()) {
      openLoginModal("برای پرسش صوتی، ابتدا با شماره موبایل وارد شوید.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      audioChunks.current = [];
      const recorder = new MediaRecorder(stream, MediaRecorder.isTypeSupported("audio/webm") ? { mimeType: "audio/webm" } : undefined);
      recorder.ondataavailable = (event) => { if (event.data.size) audioChunks.current.push(event.data); };
      recorder.onstop = () => {
        const blob = new Blob(audioChunks.current, { type: recorder.mimeType || "audio/webm" });
        setAudioFile(new File([blob], "question.webm", { type: blob.type }));
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      };
      recorderRef.current = recorder;
      recorder.start();
      setImageFile(null);
      setRecording(true);
      setMessageError("");
    } catch {
      setMessageError("برای ضبط صدا، دسترسی میکروفون را در مرورگر فعال کن.");
    }
  };

  const createExam = async () => {
    if (!bookId || gradeNumber === null) return;
    const token = getActiveToken();
    if (!currentUser || !token) {
      setExamSetupOpen(false);
      openLoginModal("برای ساخت آزمون زمان‌دار، ابتدا وارد حساب خود شوید.");
      return;
    }
    setBusy(true);
    setMessageError("");
    try {
      const response = await fetch("/api/v1/exams", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          ...buildUserAuthHeaders(token),
        },
        body: JSON.stringify({
          grade_number: gradeNumber,
          major_code: hasMajor ? majorCode : null,
          book_id: Number(bookId),
          question_count: questionCount,
          time_limit_minutes: timeLimit,
          exam_type: examType,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401) {
        setExamSetupOpen(false);
        openLoginModal("نشست شما منقضی شده است؛ لطفاً دوباره وارد شوید.");
        return;
      }
      if (response.status === 402) {
        setExamSetupOpen(false);
        setMessageError(errorMessage(payload, "سهمیهٔ توکن شما کافی نیست."));
        void refreshAccount();
        void openPlansModal("plans");
        return;
      }
      if (!response.ok) throw new Error(errorMessage(payload, "ساخت آزمون انجام نشد"));
      const exam = payload as Exam;
      if (exam.usage) {
        setCurrentUser((prev) =>
          prev
            ? {
                ...prev,
                tokens_remaining: exam.usage!.tokens_remaining,
                tokens_used_total: prev.tokens_used_total + exam.usage!.total_tokens,
              }
            : prev
        );
      }
      setActiveExam(exam);
      setExamSetupOpen(false);
      void loadExamHistory(token);
    } catch (error) {
      setMessageError(error instanceof Error ? error.message : "ساخت آزمون انجام نشد");
      setExamSetupOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const suggestions = useMemo(() => [
    "فصل حرکت بر خط راست را ساده توضیح بده",
    "از این مبحث یک مثال مرحله‌به‌مرحله حل کن",
    "شیب نمودار مکان-زمان چه چیزی را نشان می‌دهد؟",
  ], []);

  const tokenProgressPct = currentUser && currentUser.tokens_total > 0
    ? Math.min(100, Math.max(0, Math.round((currentUser.tokens_remaining / currentUser.tokens_total) * 100)))
    : 0;

  const examAuthHeaders = useMemo(() => buildUserAuthHeaders(userTokenState), [userTokenState]);

  if (activeExam) {
    return (
      <ExamRunner
        exam={activeExam}
        authHeaders={examAuthHeaders}
        onExit={() => {
          setActiveExam(null);
          void loadExamHistory();
          void refreshAccount();
        }}
      />
    );
  }

  return (
    <div className="app-shell" dir="rtl">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-brand">
          <div className="brand-mark">د</div>
          <div><strong>درسیار</strong><span>معلم خصوصی هوشمند</span></div>
          <button className="icon-button mobile-close" aria-label="بستن منو" onClick={() => setSidebarOpen(false)}><X size={18} /></button>
        </div>
        <button className="new-chat-button" onClick={resetChat}><Plus size={18} /> گفت‌وگوی تازه <span>⌘ K</span></button>
        <div className="sidebar-section-label">فضای یادگیری</div>
        <button className="sidebar-item active" onClick={() => setSidebarOpen(false)}>
          <BookOpen size={17} /><span>معلم خصوصی</span><span className="side-dot" />
        </button>
        <button className="sidebar-item" onClick={() => void openExamHistory()}>
          <GraduationCap size={17} />
          <span>آزمون‌های من</span>
          {examHistory.length > 0 && <span className="side-badge">{examHistory.length}</span>}
        </button>
        <button className="sidebar-item" onClick={() => void openPlansModal("plans")}>
          <Crown size={17} />
          <span>پلن‌ها و اعتبار توکن</span>
        </button>

        <div className="sidebar-section-label recent-label">گفت‌وگوهای اخیر</div>
        {!currentUser ? (
          <div className="sidebar-empty">پس از ورود پیامکی، گفت‌وگوهای<br />شخصی‌ات اینجا ذخیره می‌شوند.</div>
        ) : chatHistory.length > 0 ? (
          <div className="recent-list">
            {chatHistory.map((item) => (
              <div key={item.id} className={`recent-row ${activeChatId === item.id ? "active" : ""}`}>
                <button
                  type="button"
                  className="recent-chat"
                  onClick={() => void openChatSession(item.id)}
                  title={`${item.title}${item.book_title ? ` · ${item.book_title}` : ""}`}
                >
                  <span className="recent-indicator" />
                  <span className="recent-title">{item.title}</span>
                </button>
                <button
                  type="button"
                  className="recent-delete"
                  aria-label="حذف گفت‌وگو"
                  onClick={() => void deleteChatSession(item.id)}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="sidebar-empty">گفت‌وگوهای تازه‌ات اینجا<br />ذخیره می‌شوند.</div>
        )}

        <div className="sidebar-spacer" />

        {currentUser ? (
          <div className="account-card">
            <div className="account-card-top">
              <div className="avatar">{(currentUser.full_name || "د").slice(0, 1)}</div>
              <div className="account-meta">
                <b>{currentUser.full_name || currentUser.masked_phone}</b>
                <span>{currentUser.full_name ? currentUser.masked_phone : "دانش‌آموز"}</span>
              </div>
              <span className={`plan-pill ${currentUser.plan_code}`}>{currentUser.plan_title}</span>
            </div>
            <div className="account-quota">
              <div className="account-quota-row">
                <span>توکن باقی‌مانده</span>
                <b>{formatFaNumber(currentUser.tokens_remaining)}</b>
              </div>
              <div className="account-quota-bar">
                <span style={{ width: `${tokenProgressPct}%` }} />
              </div>
              <div className="account-quota-foot">
                <small>{currentUser.is_expired ? "منقضی شده" : `${formatFaNumber(currentUser.days_remaining)} روز اعتبار`}</small>
                <button type="button" className="account-mini-link" onClick={() => void openPlansModal("usage")}>
                  گزارش مصرف
                </button>
              </div>
            </div>
            <div className="account-actions">
              <button type="button" className="account-upgrade-btn" onClick={() => void openPlansModal("plans")}>
                <Zap size={13} /> ارتقا / شارژ
              </button>
              <button type="button" className="account-logout-btn" onClick={() => void handleLogout()} title="خروج از حساب">
                <LogOut size={13} /> خروج
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className="login-sidebar-cta"
            onClick={() => {
              setSidebarOpen(false);
              openLoginModal();
            }}
          >
            <div className="avatar"><Phone size={15} /></div>
            <div>
              <b>ورود / ثبت‌نام پیامکی</b>
              <span>شروع با اعتبار هدیهٔ رایگان</span>
            </div>
            <LogIn size={15} />
          </button>
        )}
      </aside>
      {sidebarOpen && <button className="sidebar-scrim" aria-label="بستن منو" onClick={() => setSidebarOpen(false)} />}

      <main className="main-panel">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="بازکردن منو" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button>
          <div className="context-title"><span className="online-indicator" /><div><b>{selectedBook?.title ?? "کلاس درس"}</b><span>{currentGrade?.title ?? "انتخاب پایه"}{hasMajor && majorCode ? ` · ${majors.find((major) => major.code === majorCode)?.title ?? ""}` : ""}</span></div><ChevronDown size={15} /></div>
          <div className="topbar-actions">
            {demoMode && <span className="private-badge demo-badge"><Sparkles size={14} /> حالت آزمایشی</span>}
            {currentUser ? (
              <button
                type="button"
                className={`token-status-pill ${currentUser.is_expired || currentUser.tokens_remaining <= 0 ? "depleted" : ""}`}
                onClick={() => void openPlansModal("plans")}
                title="مشاهده پلن‌ها و مصرف توکن"
              >
                <Coins size={14} />
                <span>{formatFaNumber(currentUser.tokens_remaining)} توکن</span>
                <small>{currentUser.plan_title}</small>
              </button>
            ) : authReady ? (
              <button type="button" className="topbar-login-btn" onClick={() => openLoginModal()}>
                <LogIn size={14} /> ورود پیامکی
              </button>
            ) : null}
            <span className="private-badge"><ShieldCheck size={14} /> فضای خصوصی</span>
            <button className="icon-button help-button" aria-label="راهنما" onClick={() => setHelpOpen(true)}><CircleHelp size={18} /></button>
          </div>
        </header>

        <section className="curriculum-strip">
          <div className="strip-heading"><span className="strip-icon"><BookOpen size={17} /></span><div><b>کلاس امروزت</b><span>کتابت را انتخاب کن تا معلم دقیقاً با همان منبع کمکت کند.</span></div></div>
          <div className="selector-row">
            <label className="select-wrap"><span>پایه</span><select value={gradeNumber ?? ""} onChange={(event) => { setGradeNumber(Number(event.target.value)); setMajorCode(""); setBooks([]); setBookId(""); setMessages([]); setActiveChatId(null); setMessageError(""); }}><option value="" disabled>انتخاب پایه</option>{grades.map((grade) => <option key={grade.number} value={grade.number}>{grade.title}</option>)}</select><ChevronDown size={15} /></label>
            {hasMajor && <label className="select-wrap"><span>رشته</span><select value={majorCode} onChange={(event) => { setMajorCode(event.target.value); setBooks([]); setBookId(""); setMessages([]); setActiveChatId(null); setMessageError(""); }}><option value="">انتخاب رشته</option>{majors.map((major) => <option key={major.code} value={major.code}>{major.title}</option>)}</select><ChevronDown size={15} /></label>}
            <label className="select-wrap book-select"><span>کتاب</span><select value={bookId} onChange={(event) => { setBookId(event.target.value); setMessages([]); setActiveChatId(null); setMessageError(""); }} disabled={!books.length}><option value="">{books.length ? "انتخاب کتاب" : "کتابی در دسترس نیست"}</option>{books.map((book) => <option key={book.id} value={book.id}>{book.title}</option>)}</select><ChevronDown size={15} /></label>
          </div>
          {curriculumError && <div className="notice-error">{curriculumError} · مطمئن شو بک‌اند و دیتابیس اجرا هستند.</div>}
        </section>

        <div className="mode-toolbar">
          <div className="mode-tabs">
            <button className={`mode-tab ${tutoringMode === "tutor" ? "selected" : ""}`} onClick={() => setTutoringMode("tutor")}><Sparkles size={15} />معلم خصوصی</button>
            <button className={`mode-tab ${tutoringMode === "problem_solver" ? "selected" : ""}`} onClick={() => setTutoringMode("problem_solver")}><Check size={15} />حل تمرین</button>
            <button className={`mode-tab ${tutoringMode === "question_designer" ? "selected" : ""}`} onClick={() => setTutoringMode("question_designer")}><BookOpen size={15} />طراحی سؤال</button>
            <button
              className="mode-tab"
              onClick={() => {
                if (!currentUser || !getActiveToken()) {
                  openLoginModal("برای شروع آزمون زمان‌دار، ابتدا با شماره موبایل وارد شوید.");
                  return;
                }
                setExamSetupOpen(true);
              }}
            >
              <GraduationCap size={15} />آزمون زمان‌دار
            </button>
          </div>
          <span className="grounding-note"><ShieldCheck size={14} /> پاسخ مستند از کتاب انتخابی</span>
        </div>

        <section className={`conversation ${messages.length ? "has-messages" : ""}`}>
          {!messages.length ? (
            <div className="welcome-state">
              <div className="welcome-orb"><Sparkles size={25} /></div>
              <span className="eyebrow">یادگیری با گفت‌وگو</span>
              <h1>سلام! آماده‌ای<br /><em>با هم یاد بگیریم؟</em></h1>
              <p>پرسشت را بنویس، از تمرین عکس بگیر یا با صدایت بپرس.<br />من پاسخ را از کتاب درسی انتخابی‌ات پیدا می‌کنم.</p>
              {authReady && !currentUser && (
                <div className="auth-gate-banner">
                  <div>
                    <b>ورود پیامکی برای شروع یادگیری</b>
                    <span>
                      با شماره موبایل وارد شو و{" "}
                      {formatFaNumber(plansPayload?.starter_tokens ?? 15000)} توکن هدیهٔ شروع دریافت کن.
                    </span>
                  </div>
                  <button type="button" className="primary-button" onClick={() => openLoginModal()}>
                    <Phone size={15} /> ورود با پیامک
                  </button>
                </div>
              )}
              <div className="suggestion-grid">{suggestions.map((text) => <button key={text} onClick={() => { setDraft(text); inputRef.current?.focus(); }}><span>{text}</span><ArrowUp size={15} /></button>)}</div>
              <div className="trust-note"><ShieldCheck size={15} /> پاسخ‌ها همراه با ارجاع به فصل و صفحهٔ کتاب ارائه می‌شوند.</div>
            </div>
          ) : (
            <div className="message-list">
              {messages.map((message) => (
                <article key={message.id} className={`message-row ${message.role}`}>
                  {message.role === "assistant" ? <div className="assistant-avatar"><Sparkles size={15} /></div> : <div className="user-avatar">{(currentUser?.full_name || "د").slice(0, 1)}</div>}
                  <div className="message-body">
                    {message.attachment && <div className="attachment-chip">{message.attachment.endsWith(".webm") ? <AudioLines size={15} /> : <FileImage size={15} />}{message.attachment}</div>}
                    <div className={`message-bubble ${message.role}`}>
                      {message.role === "assistant" ? <MathContent content={message.content} /> : <p>{message.content}</p>}
                    </div>
                    {!!message.sources?.length && <div className="source-list"><span><BookOpen size={13} /> منابع کتاب</span>{message.sources.map((source, sourceIndex) => <div className="source-pill" key={`${source.book_id}-${source.pdf_page_index}-${sourceIndex}`}>{sourceText(source)}</div>)}</div>}
                  </div>
                </article>
              ))}
              {busy && <div className="typing-row"><div className="assistant-avatar"><Sparkles size={15} /></div><div className="typing-bubble"><span /><span /><span />معلم در حال بررسی کتاب است</div></div>}
              <div id="message-end" />
            </div>
          )}
        </section>

        <footer className="composer-area">
          {messageError && <div className="inline-error composer-error">{messageError}<button onClick={() => setMessageError("")} aria-label="بستن"><X size={15} /></button></div>}
          {(imageFile || audioFile) && <div className="attachment-preview"><span>{imageFile ? <FileImage size={15} /> : <AudioLines size={15} />}{imageFile?.name ?? audioFile?.name}</span><button onClick={clearAttachments} aria-label="حذف فایل"><X size={15} /></button></div>}
          <div className="composer-box">
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage();
                }
              }}
              placeholder={
                !bookId
                  ? "اول پایه، رشته و کتابت را انتخاب کن"
                  : !currentUser
                  ? "برای پرسش از معلم، پیام خود را بنویس یا وارد شو..."
                  : tutoringMode === "problem_solver"
                  ? "صورت تمرینت را بنویس یا از آن عکس بگیر..."
                  : tutoringMode === "question_designer"
                  ? "از کدام مبحث برایت سؤال طراحی کنم؟"
                  : "از معلمت هر چیزی دربارهٔ درس بپرس..."
              }
              disabled={!bookId || busy}
              rows={2}
            />
            <div className="composer-tools">
              <div className="tool-group">
                <button
                  className="tool-button"
                  disabled={!bookId || busy}
                  onClick={() => {
                    if (!currentUser || !getActiveToken()) {
                      openLoginModal("برای ارسال تصویر سؤال، ابتدا با شماره موبایل وارد شوید.");
                      return;
                    }
                    imageInputRef.current?.click();
                  }}
                  title="پیوست تصویر"
                >
                  <Paperclip size={18} /><span>تصویر سؤال</span>
                </button>
                <input ref={imageInputRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) { setImageFile(file); setAudioFile(null); } }} />
                <button className={`tool-button ${recording ? "recording" : ""}`} disabled={!bookId || busy} onClick={() => void startRecording()} title={recording ? "پایان ضبط" : "ضبط صدا"}>{recording ? <Square size={16} /> : <Mic size={18} />}<span>{recording ? "پایان ضبط" : "صدا"}</span></button>
                {recording && <span className="recording-status"><i />در حال ضبط</span>}
              </div>
              <button className="send-button" disabled={!canAsk || (!draft.trim() && !imageFile && !audioFile)} onClick={() => void sendMessage()} aria-label="ارسال پرسش">{busy ? <LoaderCircle className="spin" size={18} /> : <Send size={18} />}</button>
            </div>
          </div>
          <div className="composer-disclaimer"><span>درسیار ممکن است اشتباه کند؛ پاسخ را با کتاب درسی تطبیق بده.</span><span><Check size={13} /> مصرف بر اساس توکن محاسبه می‌شود</span></div>
        </footer>
      </main>

      {/* SMS OTP Login Modal */}
      {authModalOpen && (
        <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setAuthModalOpen(false); }}>
          <section className="exam-setup-modal otp-modal" role="dialog" aria-modal="true" aria-labelledby="otp-modal-title">
            <button className="modal-close icon-button" onClick={() => setAuthModalOpen(false)} aria-label="بستن"><X size={18} /></button>
            <div className="modal-icon"><Phone size={22} /></div>
            <span className="eyebrow">احراز هویت پیامکی</span>
            <h2 id="otp-modal-title">{authStep === "phone" ? "ورود یا ثبت‌نام با موبایل" : "تأیید کد پیامکی"}</h2>
            {authStep === "phone" ? (
              <form onSubmit={handleRequestOtp}>
                <p>شماره موبایل خودت را وارد کن تا کد ۶ رقمی ورود برایت پیامک شود. کاربران تازه هدیهٔ شروع دریافت می‌کنند.</p>
                <label className="form-field">
                  <span>شماره موبایل (ایران)</span>
                  <input
                    type="tel"
                    dir="ltr"
                    value={phoneInput}
                    onChange={(event) => setPhoneInput(event.target.value)}
                    placeholder="09123456789"
                    autoFocus
                    required
                  />
                </label>
                <label className="form-field">
                  <span>نام و نام خانوادگی (اختیاری — برای ثبت‌نام تازه)</span>
                  <input
                    type="text"
                    value={fullNameInput}
                    onChange={(event) => setFullNameInput(event.target.value)}
                    placeholder="مثلاً علی رضایی"
                  />
                </label>
                {authError && <div className="inline-error">{authError}</div>}
                <button className="primary-button modal-submit" type="submit" disabled={authBusy}>
                  {authBusy ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
                  ارسال کد تأیید پیامکی
                </button>
              </form>
            ) : (
              <form onSubmit={handleVerifyOtp}>
                <p>کد ۶ رقمی ارسال‌شده به شمارهٔ <b dir="ltr">{normalizedPhone}</b> را وارد کن.</p>
                {demoOtpHint && (
                  <div className="demo-otp-box">
                    <div>
                      <b>حالت آزمایشی</b>
                      <span>کد تأیید شما: <strong dir="ltr">{demoOtpHint}</strong></span>
                    </div>
                    <button
                      type="button"
                      className="outline-button"
                      onClick={() => setOtpInput(demoOtpHint)}
                    >
                      درج خودکار کد
                    </button>
                  </div>
                )}
                <label className="form-field">
                  <span>کد تأیید ۶ رقمی</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    dir="ltr"
                    maxLength={6}
                    value={otpInput}
                    onChange={(event) => setOtpInput(event.target.value)}
                    placeholder="123456"
                    autoFocus
                    required
                  />
                </label>
                {authError && <div className="inline-error">{authError}</div>}
                <button className="primary-button modal-submit" type="submit" disabled={authBusy}>
                  {authBusy ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />}
                  تأیید و ورود به کلاس
                </button>
                <div className="otp-footer-actions">
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      setAuthStep("phone");
                      setAuthError("");
                    }}
                  >
                    تغییر شماره موبایل
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    disabled={resendCooldown > 0 || authBusy}
                    onClick={() => void handleRequestOtp()}
                  >
                    {resendCooldown > 0 ? `ارسال مجدد (${resendCooldown} ثانیه)` : "ارسال مجدد کد"}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}

      {/* Plans & Usage Modal */}
      {plansModalOpen && (
        <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setPlansModalOpen(false); }}>
          <section className="exam-setup-modal plans-modal" role="dialog" aria-modal="true" aria-labelledby="plans-modal-title">
            <button className="modal-close icon-button" onClick={() => setPlansModalOpen(false)} aria-label="بستن"><X size={18} /></button>
            <div className="plans-modal-head">
              <div>
                <span className="eyebrow">اشتراک و شارژ توکن</span>
                <h2 id="plans-modal-title">پلن‌های درسیار و گزارش مصرف</h2>
                <p>سهمیهٔ هر پلن بر اساس توکن مصرفی و مدت زمان استفاده محاسبه می‌شود.</p>
              </div>
              {currentUser && (
                <div className="plans-balance-chip">
                  <Wallet size={16} />
                  <div>
                    <b>{formatFaNumber(currentUser.tokens_remaining)} توکن باقی‌مانده</b>
                    <span>{currentUser.plan_title} · {currentUser.is_expired ? "منقضی‌شده" : `${formatFaNumber(currentUser.days_remaining)} روز اعتبار`}</span>
                  </div>
                </div>
              )}
            </div>

            <div className="plans-tabs">
              <button
                type="button"
                className={`plans-tab ${plansTab === "plans" ? "active" : ""}`}
                onClick={() => setPlansTab("plans")}
              >
                <Crown size={15} /> انتخاب و خرید پلن
              </button>
              <button
                type="button"
                className={`plans-tab ${plansTab === "usage" ? "active" : ""}`}
                onClick={() => {
                  setPlansTab("usage");
                  void loadUsageDetails();
                }}
              >
                <ReceiptText size={15} /> تاریخچهٔ مصرف و پرداخت
              </button>
            </div>

            {plansFeedback && <div className="success-note plans-notice"><Check size={16} />{plansFeedback}</div>}
            {plansError && <div className="inline-error plans-notice">{plansError}</div>}

            {plansTab === "plans" ? (
              <>
                <div className="plans-grid">
                  {(plansPayload?.plans ?? []).map((plan) => (
                    <article key={plan.code} className={`plan-card ${plan.code === "pro" ? "featured" : ""}`}>
                      <div className="plan-card-top">
                        <h3>پلن {plan.name}</h3>
                        {plan.code === "pro" && <span className="plan-tag">پیشنهادی</span>}
                        {currentUser?.plan_code === plan.code && !currentUser.is_expired && (
                          <span className="plan-tag active">پلن فعلی</span>
                        )}
                      </div>
                      <div className="plan-price">
                        <strong>{formatFaNumber(plan.price_toman)}</strong>
                        <span>تومان</span>
                      </div>
                      <p className="plan-desc">{plan.description}</p>
                      <ul className="plan-specs">
                        <li><Coins size={14} /> سهمیه: <b>{formatFaNumber(plan.token_quota)} توکن</b></li>
                        <li><Clock3 size={14} /> مدت اعتبار: <b>{formatFaNumber(plan.duration_days)} روز</b></li>
                        <li><Zap size={14} /> تعرفهٔ مؤثر: <b>{formatFaNumber(plan.effective_toman_per_1k)} تومان / ۱٬۰۰۰ توکن</b></li>
                      </ul>
                      <button
                        type="button"
                        className="primary-button plan-buy-btn"
                        disabled={checkoutBusyCode !== null}
                        onClick={() => void handleCheckoutPlan(plan.code)}
                      >
                        {checkoutBusyCode === plan.code ? (
                          <LoaderCircle className="spin" size={16} />
                        ) : (
                          <Zap size={16} />
                        )}
                        {plansPayload?.payment_mode === "demo" ? "فعال‌سازی آنی پلن (دمو)" : "پرداخت و فعال‌سازی"}
                      </button>
                    </article>
                  ))}
                </div>
                {plansPayload && (
                  <div className="plans-rate-footnote">
                    نرخ پایهٔ محاسبهٔ مصرف توکن: هر ۱٬۰۰۰ توکن = {formatFaNumber(plansPayload.token_price_per_1k_toman)} تومان · هدیهٔ ثبت‌نام: {formatFaNumber(plansPayload.starter_tokens)} توکن ({formatFaNumber(plansPayload.starter_duration_days)} روز)
                  </div>
                )}
              </>
            ) : (
              <div className="usage-panel">
                {!currentUser ? (
                  <div className="history-empty">
                    <span>برای دیدن تاریخچهٔ مصرف، ابتدا با شماره موبایل وارد شوید.</span>
                    <button type="button" className="primary-button" onClick={() => { setPlansModalOpen(false); openLoginModal(); }}>
                      ورود پیامکی
                    </button>
                  </div>
                ) : usageLoading ? (
                  <div className="history-empty">
                    <LoaderCircle className="spin" size={18} />
                    <span>در حال دریافت گزارش مصرف...</span>
                  </div>
                ) : (
                  <>
                    <div className="usage-stats-row">
                      <div><span>مصرف امروز</span><b>{formatFaNumber(currentUser.tokens_used_today)} توکن</b></div>
                      <div><span>مصرف کل</span><b>{formatFaNumber(currentUser.tokens_used_total)} توکن</b></div>
                      <div><span>ارزش معادل مصرف</span><b>{formatFaNumber(currentUser.used_value_toman)} تومان</b></div>
                    </div>
                    <div className="usage-lists-grid">
                      <div>
                        <h4>آخرین مصرف‌های توکن</h4>
                        {usageLogs.length === 0 ? (
                          <p className="usage-empty">هنوز مصرفی ثبت نشده است.</p>
                        ) : (
                          <div className="usage-list">
                            {usageLogs.map((log) => (
                              <div key={log.id} className="usage-item">
                                <div>
                                  <b>{actionLabel(log.action)}</b>
                                  <small>{formatFaDate(log.created_at)}</small>
                                </div>
                                <div className="usage-item-num">
                                  <b>{formatFaNumber(log.total_tokens)} توکن</b>
                                  <small>{formatFaNumber(log.cost_toman)} تومان</small>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      <div>
                        <h4>تراکنش‌های پرداخت</h4>
                        {paymentTxs.length === 0 ? (
                          <p className="usage-empty">هنوز پرداختی ثبت نشده است.</p>
                        ) : (
                          <div className="usage-list">
                            {paymentTxs.map((tx) => (
                              <div key={tx.id} className="usage-item">
                                <div>
                                  <b>پلن {tx.plan_name}</b>
                                  <small>{tx.provider === "admin_grant" ? "تخصیص مدیر" : tx.provider} · {formatFaDate(tx.paid_at ?? tx.created_at)}</small>
                                </div>
                                <div className="usage-item-num">
                                  <b>{formatFaNumber(tx.tokens_granted)} توکن</b>
                                  <small>{tx.amount_toman ? `${formatFaNumber(tx.amount_toman)} تومان` : "هدیه / مدیر"}</small>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </section>
        </div>
      )}

      {examHistoryOpen && (
        <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setExamHistoryOpen(false); }}>
          <section className="exam-setup-modal history-modal" role="dialog" aria-modal="true" aria-labelledby="exam-history-title">
            <button className="modal-close icon-button" onClick={() => setExamHistoryOpen(false)} aria-label="بستن"><X size={18} /></button>
            <div className="history-head">
              <div>
                <span className="eyebrow">تاریخچهٔ آزمون‌ها</span>
                <h2 id="exam-history-title">آزمون‌های من</h2>
                <p>کارنامهٔ آزمون‌های قبلی را مرور کن یا آزمون جدید بساز.</p>
              </div>
              <button
                className="primary-button"
                type="button"
                onClick={() => {
                  setExamHistoryOpen(false);
                  setExamSetupOpen(true);
                }}
              >
                <Plus size={16} /> آزمون جدید
              </button>
            </div>

            {historyLoading ? (
              <div className="history-empty">
                <LoaderCircle className="spin" size={18} />
                <span>در حال بارگذاری آزمون‌ها...</span>
              </div>
            ) : examHistory.length === 0 ? (
              <div className="history-empty">
                <GraduationCap size={22} />
                <span>هنوز آزمونی ثبت نشده است.</span>
              </div>
            ) : (
              <div className="exam-history-list">
                {examHistory.map((item) => {
                  const summary = item.report_summary;
                  const canOpen = item.status === "submitted" || item.status === "active";
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className="exam-history-item"
                      disabled={!canOpen || busy}
                      onClick={() => void openSavedExam(item.id)}
                    >
                      <div className="exam-history-main">
                        <div className="exam-history-top">
                          <b>{item.title}</b>
                          <span className={`history-status ${item.status}`}>
                            {item.status === "submitted"
                              ? "کارنامه آماده"
                              : item.status === "active"
                              ? "در حال اجرا"
                              : "منقضی‌شده"}
                          </span>
                        </div>
                        <small>
                          {item.book_title ?? `کتاب #${item.book_id}`} · {item.exam_type === "konkoor" ? "کنکوری" : "تمرینی"} · {item.question_count} سؤال
                        </small>
                        <span className="exam-history-date">
                          <Clock3 size={12} /> {formatFaDate(item.submitted_at ?? item.created_at)}
                        </span>
                      </div>
                      <div className="exam-history-score">
                        {summary ? (
                          <>
                            <strong>{summary.score}</strong>
                            <span>{summary.scale === "percent" ? "درصد" : "از ۲۰"}</span>
                          </>
                        ) : (
                          <span>{item.status === "active" ? "ادامه" : "بسته"}</span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}

      {examSetupOpen && <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setExamSetupOpen(false); }}>
        <section className="exam-setup-modal" role="dialog" aria-modal="true" aria-labelledby="exam-modal-title">
          <button className="modal-close icon-button" onClick={() => setExamSetupOpen(false)} aria-label="بستن"><X size={18} /></button>
          <div className="modal-icon"><GraduationCap size={22} /></div><span className="eyebrow">سنجش یادگیری</span><h2 id="exam-modal-title">آزمونت را تنظیم کن</h2><p>سؤال‌ها از صفحه‌های تأییدشدهٔ کتاب انتخابی طراحی می‌شوند.</p>
          <label className="form-field"><span>نوع آزمون</span><select value={examType} onChange={(event) => setExamType(event.target.value as "konkoor" | "final")}><option value="konkoor">کنکوری — با نمرهٔ منفی</option><option value="final">تمرینی — نمره از ۲۰</option></select></label>
          <div className="form-row"><label className="form-field"><span>تعداد سؤال</span><select value={questionCount} onChange={(event) => setQuestionCount(Number(event.target.value))}>{[3, 5, 10, 15, 20].map((count) => <option key={count} value={count}>{count} سؤال</option>)}</select></label><label className="form-field"><span>زمان</span><select value={timeLimit} onChange={(event) => setTimeLimit(Number(event.target.value))}>{[5, 10, 15, 20, 30, 45, 60].map((minutes) => <option key={minutes} value={minutes}>{minutes} دقیقه</option>)}</select></label></div>
          {messageError && <div className="inline-error">{messageError}</div>}
          <button className="primary-button modal-submit" disabled={!bookId || busy} onClick={() => void createExam()}>{busy ? <LoaderCircle className="spin" size={17} /> : <GraduationCap size={17} />}شروع آزمون</button>
          {examHistory.length > 0 && (
            <button
              type="button"
              className="outline-button modal-submit"
              onClick={() => {
                setExamSetupOpen(false);
                void openExamHistory();
              }}
            >
              <MessageSquare size={15} /> مشاهدهٔ آزمون‌های قبلی ({examHistory.length})
            </button>
          )}
          {!bookId && <small className="modal-hint">برای ساخت آزمون، ابتدا کتابت را انتخاب کن.</small>}
        </section>
      </div>}

      {helpOpen && <div className="modal-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setHelpOpen(false); }}>
        <section className="exam-setup-modal" role="dialog" aria-modal="true" aria-labelledby="help-modal-title">
          <button className="modal-close icon-button" onClick={() => setHelpOpen(false)} aria-label="بستن"><X size={18} /></button>
          <div className="modal-icon"><CircleHelp size={22} /></div><span className="eyebrow">راهنمای درسیار</span><h2 id="help-modal-title">نحوهٔ استفاده</h2>
          <p>۱. با شماره موبایل و کد پیامکی وارد شو تا اعتبار شروع دریافت کنی.<br />۲. پایه، رشته (برای پایه‌های ۱۰ تا ۱۲) و کتاب درسی را انتخاب کن.<br />۳. حالت یادگیری را از نوار ابزار برگزین: معلم خصوصی، حل تمرین، طراحی سؤال یا آزمون زمان‌دار.<br />۴. مصرف هر پرسش بر اساس توکن از اعتبارت کسر می‌شود و از بخش «پلن‌ها و اعتبار توکن» قابل تمدید یا ارتقاست.</p>
          <button className="primary-button modal-submit" onClick={() => setHelpOpen(false)}>متوجه شدم</button>
        </section>
      </div>}
    </div>
  );
}
