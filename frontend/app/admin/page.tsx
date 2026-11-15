"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Coins,
  Crown,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  FileUp,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  XCircle,
} from "lucide-react";
import type { PlanItem, StudentUser } from "@/lib/types";

type BookStatus = {
  id: number;
  title: string;
  grade_number?: number;
  major_code?: string | null;
  total_pdf_pages: number;
  status: string;
  pages: Record<string, number>;
};

type VisualElement = {
  label?: string;
  type?: string;
  scientific_description?: string;
};

type AdminPageItem = {
  pdf_page_index: number;
  printed_page_number: number | null;
  chapter_number: number | null;
  chapter_title: string | null;
  status: string;
  warnings: string[];
  markdown_content: string;
  visual_elements: VisualElement[];
  extraction_model: string | null;
  edited_by_human: boolean;
  error_message: string | null;
  image_url: string;
};

const MAX_PDF_BYTES = 100 * 1024 * 1024;
const ADMIN_TOKEN_KEY = "iran_tutor_admin_token";

function readStoredAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeAdminToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
    } else {
      window.sessionStorage.removeItem(ADMIN_TOKEN_KEY);
    }
  } catch {
    // ignore storage restriction
  }
}

function buildAuthHeaders(token: string | null): Record<string, string> {
  if (!token) return {};
  return {
    Authorization: `Bearer ${token}`,
    "X-Admin-Token": token,
  };
}

const majors = [
  { code: "math_physics", label: "ریاضی‌فیزیک" },
  { code: "experimental", label: "علوم تجربی" },
  { code: "humanities", label: "علوم انسانی" },
];

const statusLabel: Record<string, string> = {
  done: "تأییدشده",
  needs_review: "نیازمند بازبینی",
  failed: "خطا",
  pending: "در انتظار",
};

type BillingSettingsData = {
  token_price_per_1k_toman: number;
  starter_tokens: number;
  starter_duration_days: number;
};

type AdminUsersSummary = {
  total_users: number;
  active_users: number;
  paid_users: number;
  total_tokens_used: number;
  total_used_value_toman: number;
  total_revenue_toman: number;
};

function formatFaNumber(value: number) {
  try {
    return new Intl.NumberFormat("fa-IR").format(value);
  } catch {
    return String(value);
  }
}

export default function AdminPage() {
  const [authState, setAuthState] = useState<"checking" | "locked" | "authenticated">("checking");
  const [adminTab, setAdminTab] = useState<"books" | "plans" | "users">("books");
  const tokenRef = useRef<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [pageImageSrc, setPageImageSrc] = useState<string | null>(null);
  const [previewHtml, setPreviewHtml] = useState<string>("");

  // Phase 6: Plans, token pricing & user management state
  const [billingSettings, setBillingSettings] = useState<BillingSettingsData>({
    token_price_per_1k_toman: 1000,
    starter_tokens: 15000,
    starter_duration_days: 7,
  });
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [billingLoading, setBillingLoading] = useState(false);
  const [billingSaving, setBillingSaving] = useState(false);
  const [savingPlanCode, setSavingPlanCode] = useState<string | null>(null);
  const [billingMessage, setBillingMessage] = useState("");
  const [billingError, setBillingError] = useState("");

  const [users, setUsers] = useState<StudentUser[]>([]);
  const [usersSummary, setUsersSummary] = useState<AdminUsersSummary | null>(null);
  const [usersLoading, setUsersLoading] = useState(false);
  const [userSearch, setUserSearch] = useState("");
  const [userPlanFilter, setUserPlanFilter] = useState("all");
  const [editingUser, setEditingUser] = useState<StudentUser | null>(null);
  const [editUserPlan, setEditUserPlan] = useState("trial");
  const [editUserApplyPlanDefaults, setEditUserApplyPlanDefaults] = useState(true);
  const [editUserAddTokens, setEditUserAddTokens] = useState("");
  const [editUserDurationDays, setEditUserDurationDays] = useState("");
  const [editUserActive, setEditUserActive] = useState(true);
  const [userSaving, setUserSaving] = useState(false);
  const [userMessage, setUserMessage] = useState("");
  const [userError, setUserError] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("فیزیک ۳");
  const [grade, setGrade] = useState(12);
  const [major, setMajor] = useState("math_physics");
  const [startPage, setStartPage] = useState(12);
  const [endPage, setEndPage] = useState(16);
  const [books, setBooks] = useState<BookStatus[]>([]);
  const [book, setBook] = useState<BookStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewStatus, setPreviewStatus] = useState<"all" | "needs_review" | "done" | "failed">("all");
  const [previewVersion, setPreviewVersion] = useState(1);
  const [uploadMessage, setUploadMessage] = useState("");

  const [pages, setPages] = useState<AdminPageItem[]>([]);
  const [pagesLoading, setPagesLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [editPrintedPage, setEditPrintedPage] = useState("");
  const [editChapterNumber, setEditChapterNumber] = useState("");
  const [editChapterTitle, setEditChapterTitle] = useState("");
  const [editMarkdown, setEditMarkdown] = useState("");
  const [savingPage, setSavingPage] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [saveError, setSaveError] = useState("");
  const [imageError, setImageError] = useState(false);

  const selectPageForEdit = useCallback((page: AdminPageItem | null) => {
    if (!page) {
      setSelectedIdx(null);
      setEditPrintedPage("");
      setEditChapterNumber("");
      setEditChapterTitle("");
      setEditMarkdown("");
      setSaveError("");
      setImageError(false);
      return;
    }
    setSelectedIdx(page.pdf_page_index);
    setEditPrintedPage(page.printed_page_number !== null ? String(page.printed_page_number) : "");
    setEditChapterNumber(page.chapter_number !== null ? String(page.chapter_number) : "");
    setEditChapterTitle(page.chapter_title ?? "");
    setEditMarkdown(page.markdown_content ?? "");
    setSaveError("");
    setImageError(false);
  }, []);

  const getActiveToken = useCallback((): string | null => {
    return tokenRef.current ?? readStoredAdminToken();
  }, []);

  const setActiveToken = useCallback((token: string | null) => {
    tokenRef.current = token;
    storeAdminToken(token);
  }, []);

  const lockAdminPanel = useCallback(() => {
    setActiveToken(null);
    setAuthState("locked");
    setBooks([]);
    setBook(null);
    setPages([]);
    setPageImageSrc(null);
    setPreviewHtml("");
    setPreviewOpen(false);
    selectPageForEdit(null);
  }, [selectPageForEdit, setActiveToken]);

  const fetchBooks = useCallback(
    async (tokenOverride?: string | null): Promise<{ items: BookStatus[]; unauthorized: boolean }> => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      try {
        const response = await fetch("/api/v1/admin/books", {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) return { items: [], unauthorized: true };
        if (!response.ok) return { items: [], unauthorized: false };
        return { items: (await response.json()) as BookStatus[], unauthorized: false };
      } catch {
        return { items: [], unauthorized: false };
      }
    },
    [getActiveToken]
  );

  const fetchBookPages = useCallback(
    async (bookId: number, tokenOverride?: string | null): Promise<{ items: AdminPageItem[]; unauthorized: boolean }> => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      try {
        const response = await fetch(`/api/v1/admin/books/${bookId}/pages`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) return { items: [], unauthorized: true };
        if (!response.ok) return { items: [], unauthorized: false };
        return { items: (await response.json()) as AdminPageItem[], unauthorized: false };
      } catch {
        return { items: [], unauthorized: false };
      }
    },
    [getActiveToken]
  );

  const fetchBillingData = useCallback(
    async (tokenOverride?: string | null) => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      setBillingLoading(true);
      setBillingError("");
      try {
        const response = await fetch("/api/v1/admin/billing", {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) {
          lockAdminPanel();
          return;
        }
        const payload = (await response.json()) as {
          settings?: BillingSettingsData;
          plans?: PlanItem[];
          detail?: string;
        };
        if (!response.ok) throw new Error(payload.detail ?? "خطا در دریافت تنظیمات پلن‌ها");
        if (payload.settings) setBillingSettings(payload.settings);
        if (payload.plans) setPlans(payload.plans);
      } catch (cause) {
        setBillingError(cause instanceof Error ? cause.message : "خطا در دریافت تنظیمات");
      } finally {
        setBillingLoading(false);
      }
    },
    [getActiveToken, lockAdminPanel]
  );

  const fetchUsersData = useCallback(
    async (searchTerm?: string, planFilter?: string) => {
      const token = getActiveToken();
      setUsersLoading(true);
      setUserError("");
      try {
        const params = new URLSearchParams();
        const qVal = searchTerm !== undefined ? searchTerm : userSearch;
        const pVal = planFilter !== undefined ? planFilter : userPlanFilter;
        if (qVal.trim()) params.set("q", qVal.trim());
        if (pVal && pVal !== "all") params.set("plan", pVal);
        const response = await fetch(`/api/v1/admin/users?${params.toString()}`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) {
          lockAdminPanel();
          return;
        }
        const payload = (await response.json()) as {
          summary?: AdminUsersSummary;
          users?: StudentUser[];
          detail?: string;
        };
        if (!response.ok) throw new Error(payload.detail ?? "خطا در دریافت لیست کاربران");
        if (payload.summary) setUsersSummary(payload.summary);
        if (payload.users) setUsers(payload.users);
      } catch (cause) {
        setUserError(cause instanceof Error ? cause.message : "خطا در دریافت کاربران");
      } finally {
        setUsersLoading(false);
      }
    },
    [getActiveToken, lockAdminPanel, userPlanFilter, userSearch]
  );

  const refreshBooksAndSelect = useCallback(
    async (preferredBookId?: number, tokenOverride?: string | null) => {
      const { items, unauthorized } = await fetchBooks(tokenOverride);
      if (unauthorized) {
        lockAdminPanel();
        return;
      }
      setBooks(items);
      if (preferredBookId !== undefined) {
        const match = items.find((item) => item.id === preferredBookId);
        if (match) setBook(match);
      } else if (items.length > 0) {
        setBook((current) => (current ? items.find((item) => item.id === current.id) ?? items[0] : items[0]));
      }
    },
    [fetchBooks, lockAdminPanel]
  );

  const refreshBookPages = useCallback(
    async (bookId: number, keepPageIdx?: number | null) => {
      setPagesLoading(true);
      const { items, unauthorized } = await fetchBookPages(bookId);
      setPagesLoading(false);
      if (unauthorized) {
        lockAdminPanel();
        return;
      }
      setPages(items);
      if (items.length === 0) {
        selectPageForEdit(null);
        return;
      }
      const kept =
        keepPageIdx !== undefined && keepPageIdx !== null
          ? items.find((item) => item.pdf_page_index === keepPageIdx)
          : undefined;
      const firstNeedsReview = items.find((item) => item.status === "needs_review" || item.status === "failed");
      selectPageForEdit(kept ?? firstNeedsReview ?? items[0]);
    },
    [fetchBookPages, lockAdminPanel, selectPageForEdit]
  );

  useEffect(() => {
    let active = true;
    const storedToken = getActiveToken();
    fetch("/api/v1/admin/auth/session", {
      cache: "no-store",
      credentials: "same-origin",
      headers: buildAuthHeaders(storedToken),
    })
      .then(async (response) => {
        if (!response.ok) return false;
        const data = (await response.json()) as { authenticated?: boolean };
        return Boolean(data.authenticated);
      })
      .catch(() => false)
      .then(async (authenticated) => {
        if (!active) return;
        if (!authenticated) {
          setActiveToken(null);
          setAuthState("locked");
          return;
        }
        const { items, unauthorized } = await fetchBooks(storedToken);
        if (!active) return;
        if (unauthorized) {
          lockAdminPanel();
          return;
        }
        setAuthState("authenticated");
        if (items.length > 0) {
          setBooks(items);
          setBook((current) => current ?? items[0]);
        }
      });
    return () => {
      active = false;
    };
  }, [fetchBooks, getActiveToken, lockAdminPanel, setActiveToken]);

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!username.trim() || !password) {
      setAuthError("لطفاً نام کاربری و رمز عبور مدیر را وارد کنید.");
      return;
    }
    setAuthBusy(true);
    setAuthError("");
    try {
      const response = await fetch("/api/v1/admin/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        detail?: string;
        authenticated?: boolean;
        token?: string;
      };
      if (!response.ok || !payload.authenticated || !payload.token) {
        throw new Error(payload.detail ?? "نام کاربری یا رمز عبور مدیر نادرست است.");
      }
      setActiveToken(payload.token);
      const { items, unauthorized } = await fetchBooks(payload.token);
      if (unauthorized) {
        setActiveToken(null);
        throw new Error("نشست احراز هویت در مرورگر حفظ نشد؛ لطفاً صفحه را رفرش یا در تب جدید باز کنید.");
      }
      setPassword("");
      setBooks(items);
      setBook(items[0] ?? null);
      setAuthState("authenticated");
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "خطا در ورود به پنل مدیریت");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogout = async () => {
    const token = getActiveToken();
    await fetch("/api/v1/admin/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: buildAuthHeaders(token),
    }).catch(() => undefined);
    lockAdminPanel();
  };

  const activeBookId = authState === "authenticated" ? book?.id ?? null : null;
  const activeBookStatus = authState === "authenticated" ? book?.status ?? null : null;

  useEffect(() => {
    if (!activeBookId || !activeBookStatus) return;
    let active = true;

    if (activeBookStatus === "ingesting") {
      const timer = window.setInterval(async () => {
        const token = getActiveToken();
        try {
          const response = await fetch(`/api/v1/admin/books/${activeBookId}/status`, {
            cache: "no-store",
            credentials: "same-origin",
            headers: buildAuthHeaders(token),
          });
          if (!active) return;
          if (response.status === 401) {
            lockAdminPanel();
            return;
          }
          const payload = (await response.json()) as BookStatus;
          if (!response.ok) return;
          setBook(payload);
          if (payload.status !== "ingesting") {
            const { items, unauthorized } = await fetchBooks();
            if (!active) return;
            if (unauthorized) {
              lockAdminPanel();
              return;
            }
            if (items.length > 0) setBooks(items);
          }
        } catch {
          if (active) setError("وضعیت پردازش دریافت نشد؛ ارتباط بک‌اند را بررسی کن.");
        }
      }, 2000);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
    }

    fetchBookPages(activeBookId).then(({ items, unauthorized }) => {
      if (!active) return;
      setPagesLoading(false);
      if (unauthorized) {
        lockAdminPanel();
        return;
      }
      setPages(items);
      if (items.length === 0) {
        selectPageForEdit(null);
        return;
      }
      const firstNeedsReview = items.find((item) => item.status === "needs_review" || item.status === "failed");
      selectPageForEdit(firstNeedsReview ?? items[0]);
    });

    return () => {
      active = false;
    };
  }, [activeBookId, activeBookStatus, fetchBookPages, fetchBooks, getActiveToken, lockAdminPanel, selectPageForEdit]);

  const selectedPage = useMemo(
    () => pages.find((item) => item.pdf_page_index === selectedIdx) ?? null,
    [pages, selectedIdx]
  );

  const selectedImageUrl = selectedPage?.image_url ?? null;

  useEffect(() => {
    if (authState !== "authenticated" || !selectedImageUrl) return;
    let active = true;
    let objectUrl: string | null = null;
    const token = getActiveToken();
    fetch(`${selectedImageUrl}?v=${previewVersion}`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: buildAuthHeaders(token),
    })
      .then(async (response) => {
        if (response.status === 401) {
          if (active) lockAdminPanel();
          return null;
        }
        if (!response.ok) return null;
        return response.blob();
      })
      .then((blob) => {
        if (!active) return;
        if (!blob) {
          setImageError(true);
          setPageImageSrc(null);
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setImageError(false);
        setPageImageSrc(objectUrl);
      })
      .catch(() => {
        if (active) {
          setImageError(true);
          setPageImageSrc(null);
        }
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [authState, getActiveToken, lockAdminPanel, previewVersion, selectedImageUrl]);

  useEffect(() => {
    if (authState !== "authenticated" || !previewOpen || !activeBookId) return;
    let active = true;
    const token = getActiveToken();
    fetch(`/api/v1/admin/books/${activeBookId}/preview?status=${previewStatus}&v=${previewVersion}`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: buildAuthHeaders(token),
    })
      .then(async (response) => {
        if (response.status === 401) {
          if (active) lockAdminPanel();
          return "";
        }
        if (!response.ok) return "";
        return response.text();
      })
      .then((htmlText) => {
        if (active && htmlText) setPreviewHtml(htmlText);
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [activeBookId, authState, getActiveToken, lockAdminPanel, previewOpen, previewStatus, previewVersion]);

  const processedPages = useMemo(
    () => (book ? Object.values(book.pages).reduce((total, count) => total + count, 0) : 0),
    [book]
  );
  const progress = book?.total_pdf_pages ? Math.min(100, (processedPages / book.total_pdf_pages) * 100) : 0;

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setError("ابتدا فایل PDF را انتخاب کن.");
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setError("حجم فایل PDF نباید بیشتر از ۱۰۰ مگابایت باشد.");
      return;
    }
    if (startPage < 1 || endPage < startPage) {
      setError("بازهٔ صفحه‌ها معتبر نیست.");
      return;
    }
    setSubmitting(true);
    setError("");
    setPreviewOpen(false);
    setPreviewStatus("all");
    setUploadMessage("");
    setSaveMessage("");
    setPages([]);
    selectPageForEdit(null);
    const form = new FormData();
    form.set("pdf_file", file);
    form.set("grade_number", String(grade));
    form.set("book_title", title);
    form.set("start_page", String(startPage));
    form.set("end_page", String(endPage));
    if (grade >= 10) form.set("major_code", major);
    try {
      const token = getActiveToken();
      const response = await fetch("/api/v1/admin/books/upload-and-ingest", {
        method: "POST",
        credentials: "same-origin",
        headers: buildAuthHeaders(token),
        body: form,
      });
      if (response.status === 401) {
        lockAdminPanel();
        throw new Error("نشست مدیریت منقضی شده است؛ لطفاً دوباره وارد شوید.");
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "آپلود و پردازش شروع نشد.");
      setUploadMessage(`پردازش کتاب با شناسهٔ ${payload.book_id} شروع شد.`);
      setBook({
        id: payload.book_id,
        title,
        grade_number: grade,
        major_code: grade >= 10 ? major : null,
        total_pdf_pages: endPage - startPage + 1,
        status: "ingesting",
        pages: {},
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "خطا در ارتباط با سرور");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSavePage = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!book || !selectedPage) return;
    setSavingPage(true);
    setSaveError("");
    setSaveMessage("");

    const parsedPrinted = editPrintedPage.trim() === "" ? null : Number(editPrintedPage);
    const parsedChapter = editChapterNumber.trim() === "" ? null : Number(editChapterNumber);
    if (parsedPrinted !== null && (!Number.isInteger(parsedPrinted) || parsedPrinted < 0)) {
      setSaveError("شمارهٔ صفحهٔ چاپی باید عدد صحیح نامنفی یا خالی باشد.");
      setSavingPage(false);
      return;
    }
    if (parsedChapter !== null && (!Number.isInteger(parsedChapter) || parsedChapter < 0)) {
      setSaveError("شمارهٔ فصل باید عدد صحیح نامنفی یا خالی باشد.");
      setSavingPage(false);
      return;
    }

    try {
      const token = getActiveToken();
      const response = await fetch(`/api/v1/admin/books/${book.id}/pages/${selectedPage.pdf_page_index}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(token),
        },
        credentials: "same-origin",
        body: JSON.stringify({
          printed_page_number: parsedPrinted,
          chapter_number: parsedChapter,
          chapter_title: editChapterTitle.trim() === "" ? null : editChapterTitle.trim(),
          markdown_content: editMarkdown,
        }),
      });
      if (response.status === 401) {
        lockAdminPanel();
        throw new Error("نشست مدیریت منقضی شده است؛ لطفاً دوباره وارد شوید.");
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "ذخیرهٔ صفحه انجام نشد.");
      setSaveMessage(`صفحهٔ PDF ${selectedPage.pdf_page_index} ذخیره و به‌عنوان «تأییدشده» ثبت شد.`);
      setPreviewVersion((current) => current + 1);
      await Promise.all([
        refreshBooksAndSelect(book.id),
        refreshBookPages(book.id, selectedPage.pdf_page_index),
      ]);
    } catch (cause) {
      setSaveError(cause instanceof Error ? cause.message : "خطا در ذخیرهٔ صفحه");
    } finally {
      setSavingPage(false);
    }
  };

  const handleSaveBillingSettings = async (event: React.FormEvent) => {
    event.preventDefault();
    const token = getActiveToken();
    setBillingSaving(true);
    setBillingError("");
    setBillingMessage("");
    try {
      const response = await fetch("/api/v1/admin/billing/settings", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
        body: JSON.stringify(billingSettings),
      });
      if (response.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await response.json()) as { settings?: BillingSettingsData; detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "ذخیره تنظیمات توکن انجام نشد");
      if (payload.settings) setBillingSettings(payload.settings);
      setBillingMessage("قیمت توکن و تنظیمات هدیه ثبت‌نام با موفقیت ذخیره شد.");
    } catch (cause) {
      setBillingError(cause instanceof Error ? cause.message : "خطا در ذخیره تنظیمات");
    } finally {
      setBillingSaving(false);
    }
  };

  const handleSavePlan = async (plan: PlanItem) => {
    const token = getActiveToken();
    setSavingPlanCode(plan.code);
    setBillingError("");
    setBillingMessage("");
    try {
      const response = await fetch(`/api/v1/admin/billing/plans/${plan.code}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
        body: JSON.stringify({
          name: plan.name,
          description: plan.description,
          price_toman: Number(plan.price_toman),
          token_quota: Number(plan.token_quota),
          duration_days: Number(plan.duration_days),
          is_active: plan.is_active,
        }),
      });
      if (response.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await response.json()) as { plan?: PlanItem; detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "ذخیره پلن انجام نشد");
      if (payload.plan) {
        setPlans((prev) => prev.map((item) => (item.code === plan.code ? payload.plan! : item)));
      }
      setBillingMessage(`تغییرات پلن «${plan.name}» با موفقیت ذخیره شد.`);
    } catch (cause) {
      setBillingError(cause instanceof Error ? cause.message : "خطا در ذخیره پلن");
    } finally {
      setSavingPlanCode(null);
    }
  };

  const selectUserForEdit = (u: StudentUser) => {
    setEditingUser(u);
    setEditUserPlan(u.plan_code);
    setEditUserApplyPlanDefaults(false);
    setEditUserAddTokens("");
    setEditUserDurationDays("");
    setEditUserActive(u.is_active);
    setUserMessage("");
    setUserError("");
  };

  const handleSaveUser = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingUser) return;
    const token = getActiveToken();
    setUserSaving(true);
    setUserError("");
    setUserMessage("");
    try {
      const body: Record<string, unknown> = {
        plan_code: editUserPlan,
        apply_plan_defaults: editUserApplyPlanDefaults,
        is_active: editUserActive,
      };
      if (editUserAddTokens.trim() !== "") {
        body.add_tokens = Number(editUserAddTokens);
      }
      if (editUserDurationDays.trim() !== "") {
        body.duration_days = Number(editUserDurationDays);
      }
      const response = await fetch(`/api/v1/admin/users/${editingUser.id}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
        body: JSON.stringify(body),
      });
      if (response.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await response.json()) as { user?: StudentUser; detail?: string };
      if (!response.ok || !payload.user) throw new Error(payload.detail ?? "به‌روزرسانی کاربر انجام نشد");
      setUserMessage(`اطلاعات کاربر ${payload.user.phone_number} با موفقیت به‌روزرسانی شد.`);
      setEditingUser(payload.user);
      setEditUserAddTokens("");
      setEditUserDurationDays("");
      setEditUserApplyPlanDefaults(false);
      await fetchUsersData();
    } catch (cause) {
      setUserError(cause instanceof Error ? cause.message : "خطا در به‌روزرسانی کاربر");
    } finally {
      setUserSaving(false);
    }
  };

  if (authState === "checking") {
    return (
      <main className="admin-login-shell" dir="rtl">
        <div className="admin-login-card">
          <div className="admin-login-icon">
            <LoaderCircle size={24} className="spin" />
          </div>
          <h1>بررسی دسترسی مدیریت...</h1>
        </div>
      </main>
    );
  }

  if (authState === "locked") {
    return (
      <main className="admin-login-shell" dir="rtl">
        <section className="admin-login-card" aria-labelledby="admin-login-title">
          <div className="admin-login-icon">
            <LockKeyhole size={24} />
          </div>
          <span className="eyebrow">دسترسی محدود</span>
          <h1 id="admin-login-title">ورود به پنل مدیریت هم‌درس</h1>
          <p>این بخش از محیط دانش‌آموز جداست. برای مدیریت کتاب‌های درسی، نام کاربری و رمز عبور مدیر را وارد کنید.</p>
          <form onSubmit={handleLogin} className="admin-form">
            <label className="form-field">
              <span>نام کاربری</span>
              <input
                type="text"
                dir="ltr"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="admin"
                autoComplete="username"
                autoFocus
              />
            </label>
            <label className="form-field">
              <span>رمز عبور</span>
              <div className="password-input-wrap">
                <input
                  type={showPassword ? "text" : "password"}
                  dir="ltr"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="رمز عبور را وارد کنید"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? "مخفی کردن رمز" : "نمایش رمز"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
            {authError && <div className="inline-error">{authError}</div>}
            <button className="primary-button admin-submit" type="submit" disabled={authBusy}>
              {authBusy ? <LoaderCircle size={17} className="spin" /> : <LockKeyhole size={17} />}
              ورود به پنل مدیریت
            </button>
          </form>
          <Link className="back-link admin-login-back" href="/">
            <ArrowRight size={16} /> بازگشت به سایت
          </Link>
        </section>
      </main>
    );
  }

  return (
    <main className="admin-shell" dir="rtl">
      <header className="admin-topbar">
        <div className="admin-brand">
          <div className="brand-mark">ه</div>
          <div>
            <b>مدیریت هم‌درس</b>
            <span>مرکز محتوای آموزشی</span>
          </div>
        </div>
        <div className="admin-topbar-actions">
          <Link className="back-link" href="/">
            <ArrowRight size={17} /> مشاهدهٔ سایت
          </Link>
          <button type="button" className="admin-logout-btn" onClick={() => void handleLogout()}>
            <LogOut size={15} /> خروج
          </button>
        </div>
      </header>
      <div className="admin-content">
        <div className="admin-heading">
          <div>
            <span className="eyebrow">مدیریت هم‌درس</span>
            <h1>
              {adminTab === "books"
                ? "افزودن و بازبینی کتاب درسی"
                : adminTab === "plans"
                ? "مدیریت قیمت توکن و پلن‌ها"
                : "مدیریت کاربران و سهمیه‌ها"}
            </h1>
            <p>
              {adminTab === "books"
                ? "کتاب را وارد کن، چند صفحه را آزمایشی پردازش کن، خروجی را با PDF بسنج و صفحه‌ها را تأیید کن."
                : adminTab === "plans"
                ? "قیمت پایهٔ توکن، سهمیهٔ هر پلن، مدت اعتبار (روز) و مبلغ پلن‌های اقتصادی، حرفه‌ای و هوشمندانه را تنظیم کنید."
                : "وضعیت کاربران ثبت‌نامی، میزان مصرف توکن، پلن فعال و شارژ حساب‌ها را مدیریت کنید."}
            </p>
          </div>
          <div className="admin-heading-mark">
            {adminTab === "books" ? <BookOpen size={25} /> : adminTab === "plans" ? <Crown size={25} /> : <Users size={25} />}
          </div>
        </div>

        <nav className="admin-tabs" aria-label="بخش‌های پنل مدیریت">
          <button
            type="button"
            className={`admin-tab ${adminTab === "books" ? "active" : ""}`}
            onClick={() => setAdminTab("books")}
          >
            <BookOpen size={16} /> کتاب‌ها و پردازش PDF
          </button>
          <button
            type="button"
            className={`admin-tab ${adminTab === "plans" ? "active" : ""}`}
            onClick={() => {
              setAdminTab("plans");
              void fetchBillingData();
            }}
          >
            <Crown size={16} /> پلن‌ها و قیمت توکن
          </button>
          <button
            type="button"
            className={`admin-tab ${adminTab === "users" ? "active" : ""}`}
            onClick={() => {
              setAdminTab("users");
              void fetchUsersData();
              void fetchBillingData();
            }}
          >
            <Users size={16} /> کاربران و سهمیه‌ها
          </button>
        </nav>

        <div className="admin-warning admin-protected-note">
          <ShieldCheck size={18} />
          <span>
            <b>دسترسی محافظت‌شده با رمز عبور</b> · مسیر /admin از محیط دانش‌آموز جدا شده است. پیش از انتشار نهایی، مقدار ADMIN_PASSWORD را به رمز قوی تغییر دهید.
          </span>
        </div>

        {adminTab === "plans" && (
          <div className="admin-billing-stack">
            {billingMessage && <div className="success-note admin-banner"><CheckCircle2 size={15} />{billingMessage}</div>}
            {billingError && <div className="inline-error admin-banner">{billingError}</div>}

            <section className="admin-card">
              <div className="card-heading">
                <div>
                  <h2>قیمت پایهٔ توکن و اعتبار هدیهٔ ثبت‌نام</h2>
                  <p>ارزش معادل هر ۱٬۰۰۰ توکن مصرفی به تومان و سهمیهٔ اولیه کاربران تازه‌وارد.</p>
                </div>
                <span className="step-badge"><Coins size={14} /></span>
              </div>
              <form className="admin-form" onSubmit={handleSaveBillingSettings}>
                <div className="form-row">
                  <label className="form-field">
                    <span>قیمت هر ۱٬۰۰۰ توکن (تومان)</span>
                    <input
                      type="number"
                      min={1}
                      value={billingSettings.token_price_per_1k_toman}
                      onChange={(e) =>
                        setBillingSettings((prev) => ({
                          ...prev,
                          token_price_per_1k_toman: Number(e.target.value),
                        }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>توکن هدیه ثبت‌نام جدید</span>
                    <input
                      type="number"
                      min={0}
                      value={billingSettings.starter_tokens}
                      onChange={(e) =>
                        setBillingSettings((prev) => ({
                          ...prev,
                          starter_tokens: Number(e.target.value),
                        }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>مدت اعتبار هدیه (روز)</span>
                    <input
                      type="number"
                      min={1}
                      value={billingSettings.starter_duration_days}
                      onChange={(e) =>
                        setBillingSettings((prev) => ({
                          ...prev,
                          starter_duration_days: Number(e.target.value),
                        }))
                      }
                    />
                  </label>
                </div>
                <div className="admin-inline-actions">
                  <button className="primary-button" type="submit" disabled={billingSaving || billingLoading}>
                    {billingSaving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                    ذخیره تنظیمات توکن
                  </button>
                </div>
              </form>
            </section>

            <section className="admin-plans-grid">
              {plans.map((plan) => (
                <article key={plan.code} className="admin-card">
                  <div className="card-heading">
                    <div>
                      <h2>پلن {plan.name} ({plan.code})</h2>
                      <p>تعرفه مؤثر: {formatFaNumber(plan.token_quota > 0 ? Math.round((plan.price_toman * 1000) / plan.token_quota) : 0)} تومان / ۱٬۰۰۰ توکن</p>
                    </div>
                    <label className="plan-active-toggle">
                      <input
                        type="checkbox"
                        checked={plan.is_active}
                        onChange={(e) =>
                          setPlans((prev) =>
                            prev.map((item) =>
                              item.code === plan.code ? { ...item, is_active: e.target.checked } : item
                            )
                          )
                        }
                      />
                      <span>فعال</span>
                    </label>
                  </div>
                  <div className="admin-form">
                    <label className="form-field">
                      <span>عنوان پلن</span>
                      <input
                        value={plan.name}
                        onChange={(e) =>
                          setPlans((prev) =>
                            prev.map((item) => (item.code === plan.code ? { ...item, name: e.target.value } : item))
                          )
                        }
                      />
                    </label>
                    <label className="form-field">
                      <span>قیمت پلن (تومان)</span>
                      <input
                        type="number"
                        min={0}
                        value={plan.price_toman}
                        onChange={(e) =>
                          setPlans((prev) =>
                            prev.map((item) =>
                              item.code === plan.code ? { ...item, price_toman: Number(e.target.value) } : item
                            )
                          )
                        }
                      />
                    </label>
                    <div className="form-row">
                      <label className="form-field">
                        <span>میزان توکن (سهمیه)</span>
                        <input
                          type="number"
                          min={1}
                          value={plan.token_quota}
                          onChange={(e) =>
                            setPlans((prev) =>
                              prev.map((item) =>
                                item.code === plan.code ? { ...item, token_quota: Number(e.target.value) } : item
                              )
                            )
                          }
                        />
                      </label>
                      <label className="form-field">
                        <span>زمان استفاده (روز)</span>
                        <input
                          type="number"
                          min={1}
                          value={plan.duration_days}
                          onChange={(e) =>
                            setPlans((prev) =>
                              prev.map((item) =>
                                item.code === plan.code ? { ...item, duration_days: Number(e.target.value) } : item
                              )
                            )
                          }
                        />
                      </label>
                    </div>
                    <label className="form-field">
                      <span>توضیحات نمایشی</span>
                      <input
                        value={plan.description}
                        onChange={(e) =>
                          setPlans((prev) =>
                            prev.map((item) =>
                              item.code === plan.code ? { ...item, description: e.target.value } : item
                            )
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="primary-button admin-submit"
                      disabled={savingPlanCode === plan.code}
                      onClick={() => void handleSavePlan(plan)}
                    >
                      {savingPlanCode === plan.code ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                      ذخیره تغییرات پلن {plan.name}
                    </button>
                  </div>
                </article>
              ))}
            </section>
          </div>
        )}

        {adminTab === "users" && (
          <div className="admin-billing-stack">
            {usersSummary && (
              <div className="admin-kpi-grid">
                <div className="admin-kpi-card"><span>کل کاربران</span><b>{formatFaNumber(usersSummary.total_users)}</b></div>
                <div className="admin-kpi-card"><span>کاربران با پلن خریداری‌شده</span><b>{formatFaNumber(usersSummary.paid_users)}</b></div>
                <div className="admin-kpi-card"><span>مجموع توکن مصرفی</span><b>{formatFaNumber(usersSummary.total_tokens_used)}</b></div>
                <div className="admin-kpi-card"><span>درآمد پرداخت‌ها (تومان)</span><b>{formatFaNumber(usersSummary.total_revenue_toman)}</b></div>
              </div>
            )}

            <section className="admin-card">
              <div className="users-toolbar">
                <div className="users-search">
                  <Search size={15} />
                  <input
                    placeholder="جستجو با شماره موبایل یا نام..."
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void fetchUsersData(userSearch, userPlanFilter);
                    }}
                  />
                </div>
                <select
                  value={userPlanFilter}
                  onChange={(e) => {
                    setUserPlanFilter(e.target.value);
                    void fetchUsersData(userSearch, e.target.value);
                  }}
                >
                  <option value="all">همه پلن‌ها</option>
                  <option value="trial">هدیه ثبت‌نام</option>
                  <option value="normal">اقتصادی</option>
                  <option value="pro">حرفه‌ای</option>
                  <option value="vip">هوشمندانه</option>
                </select>
                <button
                  type="button"
                  className="outline-button"
                  onClick={() => void fetchUsersData(userSearch, userPlanFilter)}
                >
                  بروزرسانی لیست
                </button>
              </div>

              {userMessage && <div className="success-note admin-banner"><CheckCircle2 size={15} />{userMessage}</div>}
              {userError && <div className="inline-error admin-banner">{userError}</div>}

              {usersLoading ? (
                <div className="review-loading"><LoaderCircle className="spin" size={18} /><span>در حال دریافت کاربران...</span></div>
              ) : users.length === 0 ? (
                <div className="review-empty">هنوز کاربری ثبت‌نام نکرده است.</div>
              ) : (
                <div className="admin-users-table-wrap">
                  <table className="admin-users-table">
                    <thead>
                      <tr>
                        <th>موبایل / نام</th>
                        <th>پلن فعلی</th>
                        <th>توکن باقی‌مانده</th>
                        <th>مصرف امروز / کل</th>
                        <th>اعتبار باقی‌مانده</th>
                        <th>وضعیت</th>
                        <th>مدیریت</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => (
                        <tr key={u.id} className={editingUser?.id === u.id ? "selected" : ""}>
                          <td>
                            <b dir="ltr">{u.phone_number}</b>
                            <small>{u.full_name || "بدون نام"}</small>
                          </td>
                          <td><span className={`badge-pill ${u.is_expired ? "failed" : "done"}`}>{u.plan_title}</span></td>
                          <td>{formatFaNumber(u.tokens_remaining)} / {formatFaNumber(u.tokens_total)}</td>
                          <td>{formatFaNumber(u.tokens_used_today)} / {formatFaNumber(u.tokens_used_total)}</td>
                          <td>{u.is_expired ? "منقضی" : `${formatFaNumber(u.days_remaining)} روز`}</td>
                          <td>{u.is_active ? "فعال" : "مسدود"}</td>
                          <td>
                            <button
                              type="button"
                              className="outline-button"
                              onClick={() => selectUserForEdit(u)}
                            >
                              ویرایش / شارژ
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {editingUser && (
              <section className="admin-card">
                <div className="card-heading">
                  <div>
                    <h2>مدیریت حساب کاربر <span dir="ltr">{editingUser.phone_number}</span></h2>
                    <p>تخصیص پلن، افزایش توکن، تغییر مدت اعتبار یا فعال/غیرفعال‌سازی دسترسی.</p>
                  </div>
                  <button type="button" className="icon-button" onClick={() => setEditingUser(null)} aria-label="بستن">
                    <XCircle size={18} />
                  </button>
                </div>
                <form className="admin-form" onSubmit={handleSaveUser}>
                  <div className="form-row">
                    <label className="form-field">
                      <span>تغییر پلن</span>
                      <select value={editUserPlan} onChange={(e) => setEditUserPlan(e.target.value)}>
                        <option value="trial">هدیه ثبت‌نام (trial)</option>
                        {plans.map((p) => (
                          <option key={p.code} value={p.code}>
                            {p.name} ({formatFaNumber(p.token_quota)} توکن / {p.duration_days} روز)
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="form-field">
                      <span>افزایش / کاهش توکن (اختیاری)</span>
                      <input
                        type="number"
                        placeholder="مثلاً 100000"
                        value={editUserAddTokens}
                        onChange={(e) => setEditUserAddTokens(e.target.value)}
                      />
                    </label>
                    <label className="form-field">
                      <span>تمدید اعتبار از امروز (روز، اختیاری)</span>
                      <input
                        type="number"
                        min={1}
                        placeholder="مثلاً 30"
                        value={editUserDurationDays}
                        onChange={(e) => setEditUserDurationDays(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="admin-inline-checks">
                    <label className="plan-active-toggle">
                      <input
                        type="checkbox"
                        checked={editUserApplyPlanDefaults}
                        onChange={(e) => setEditUserApplyPlanDefaults(e.target.checked)}
                      />
                      <span>سهمیه توکن و مدت روز پلن انتخابی را روی حساب اعمال کن</span>
                    </label>
                    <label className="plan-active-toggle">
                      <input
                        type="checkbox"
                        checked={editUserActive}
                        onChange={(e) => setEditUserActive(e.target.checked)}
                      />
                      <span>حساب کاربری فعال باشد</span>
                    </label>
                  </div>
                  <div className="admin-inline-actions">
                    <button type="submit" className="primary-button" disabled={userSaving}>
                      {userSaving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                      اعمال تغییرات کاربر
                    </button>
                  </div>
                </form>
              </section>
            )}
          </div>
        )}

        {adminTab === "books" && (
        <>
        <div className="admin-grid">
          <section className="admin-card">
            <div className="card-heading">
              <div>
                <h2>اطلاعات کتاب</h2>
                <p>برای تست اول، بازه‌ای کوچک از فصل را وارد کن.</p>
              </div>
              <span className="step-badge">۱</span>
            </div>
            <form onSubmit={submit} className="admin-form">
              <label className="form-field">
                <span>عنوان کتاب</span>
                <input value={title} onChange={(event) => setTitle(event.target.value)} required />
              </label>
              <div className="form-row">
                <label className="form-field">
                  <span>پایه</span>
                  <select value={grade} onChange={(event) => setGrade(Number(event.target.value))}>
                    {Array.from({ length: 12 }, (_, index) => index + 1).map((number) => (
                      <option key={number} value={number}>
                        {number === 12 ? "دوازدهم" : `پایهٔ ${number}`}
                      </option>
                    ))}
                  </select>
                </label>
                {grade >= 10 && (
                  <label className="form-field">
                    <span>رشته</span>
                    <select value={major} onChange={(event) => setMajor(event.target.value)}>
                      {majors.map((item) => (
                        <option key={item.code} value={item.code}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
              <div className="form-row">
                <label className="form-field">
                  <span>از صفحهٔ PDF</span>
                  <input
                    type="number"
                    min={1}
                    value={startPage}
                    onChange={(event) => setStartPage(Number(event.target.value))}
                  />
                </label>
                <label className="form-field">
                  <span>تا صفحهٔ PDF</span>
                  <input
                    type="number"
                    min={1}
                    value={endPage}
                    onChange={(event) => setEndPage(Number(event.target.value))}
                  />
                </label>
              </div>
              <label className={`pdf-dropzone ${file ? "has-file" : ""}`}>
                <input
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
                <span className="drop-icon">{file ? <CheckCircle2 size={21} /> : <FileUp size={21} />}</span>
                <b>{file ? file.name : "فایل PDF کتاب را انتخاب کن"}</b>
                <small>
                  {file
                    ? `${(file.size / (1024 * 1024)).toFixed(1)} مگابایت`
                    : "حداکثر ۱۰۰ مگابایت · فقط PDF"}
                </small>
              </label>
              {error && (
                <div className="inline-error">
                  {error}
                  <button type="button" onClick={() => setError("")}>
                    <XCircle size={15} />
                  </button>
                </div>
              )}
              <button className="primary-button admin-submit" type="submit" disabled={submitting}>
                {submitting ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
                آپلود و شروع پردازش
              </button>
            </form>
          </section>

          <section className="admin-card progress-card">
            <div className="card-heading">
              <div>
                <h2>وضعیت پردازش</h2>
                <p>استخراج صفحه‌به‌صفحه همراه با بازبینی‌پذیری.</p>
              </div>
              <span className="step-badge">۲</span>
            </div>

            {books.length > 0 && (
              <label className="form-field book-switcher">
                <span>انتخاب کتاب برای بررسی و بازبینی</span>
                <select
                  value={book?.id ?? ""}
                  onChange={(event) => {
                    const nextId = Number(event.target.value);
                    const found = books.find((item) => item.id === nextId) ?? null;
                    setBook(found);
                    setPages([]);
                    setPagesLoading(found !== null && found.status !== "ingesting");
                    selectPageForEdit(null);
                    setPreviewOpen(false);
                    setPreviewStatus("all");
                    setUploadMessage("");
                    setSaveMessage("");
                  }}
                >
                  {books.map((item) => (
                    <option key={item.id} value={item.id}>
                      #{item.id} · {item.title} ({item.total_pdf_pages} صفحه)
                    </option>
                  ))}
                </select>
              </label>
            )}

            {!book ? (
              <div className="admin-empty">
                <div>
                  <BookOpen size={22} />
                </div>
                <b>هنوز کتابی برای پردازش نیست</b>
                <span>بعد از آپلود، وضعیت هر صفحه اینجا نمایش داده می‌شود.</span>
              </div>
            ) : (
              <div className="progress-content">
                <div className="processing-book">
                  <div className="mini-book-icon">
                    <BookOpen size={20} />
                  </div>
                  <div>
                    <b>{book.title}</b>
                    <span>شناسهٔ کتاب: {book.id}</span>
                  </div>
                  <span className={`status-chip ${book.status}`}>
                    {book.status === "ingesting" ? (
                      <>
                        <LoaderCircle className="spin" size={13} />
                        در حال پردازش
                      </>
                    ) : book.status === "ready" ? (
                      <>
                        <CheckCircle2 size={13} />
                        آمادهٔ بازبینی
                      </>
                    ) : (
                      <>
                        <XCircle size={13} />
                        ناموفق
                      </>
                    )}
                  </span>
                </div>
                <div className="progress-label">
                  <span>صفحه‌های پردازش‌شده</span>
                  <b>
                    {processedPages} / {book.total_pdf_pages}
                  </b>
                </div>
                <div className="progress-track">
                  <span style={{ width: `${progress}%` }} />
                </div>
                <div className="status-counts">
                  <div>
                    <i className="done-dot" />
                    موفق <b>{book.pages.done ?? 0}</b>
                  </div>
                  <div>
                    <i className="review-dot" />
                    بازبینی <b>{book.pages.needs_review ?? 0}</b>
                  </div>
                  <div>
                    <i className="failed-dot" />
                    خطا <b>{book.pages.failed ?? 0}</b>
                  </div>
                </div>
                {uploadMessage && (
                  <div className="success-note">
                    <CheckCircle2 size={15} />
                    {uploadMessage}
                  </div>
                )}
                {book.status === "failed" && processedPages === 0 && (
                  <div className="inline-error" style={{ marginTop: 12 }}>
                    پردازش کتاب ناموفق بود و صفحه‌ای ثبت نشد.
                  </div>
                )}
                {book.status !== "ingesting" && processedPages > 0 && (
                  <button
                    className="outline-button preview-button"
                    type="button"
                    onClick={() => {
                      setPreviewStatus("all");
                      setPreviewVersion((current) => current + 1);
                      setPreviewOpen(true);
                    }}
                  >
                    <ExternalLink size={16} />
                    بازکردن پیش‌نمایش مقایسه‌ای
                  </button>
                )}
              </div>
            )}
            <div className="review-tip">
              <Sparkles size={15} />
              <span>صفحه‌های نیازمند بازبینی را پیش از ایندکس و استفادهٔ آموزشی اصلاح و تأیید کن.</span>
            </div>
          </section>
        </div>

        {book && book.status !== "ingesting" && (
          <section className="admin-card review-panel">
            <div className="card-heading">
              <div>
                <h2>بازبینی و ویرایش دستی صفحه‌ها</h2>
                <p>تصویر صفحهٔ واقعی PDF را با متن و مشخصات فصل مقایسه کن و پس از اصلاح، صفحه را تأیید کن.</p>
              </div>
              <span className="step-badge">۳</span>
            </div>

            {pagesLoading ? (
              <div className="review-loading">
                <LoaderCircle className="spin" size={18} />
                <span>در حال دریافت صفحه‌های کتاب...</span>
              </div>
            ) : pages.length === 0 ? (
              <div className="review-empty">صفحه‌ای برای این کتاب ثبت نشده است.</div>
            ) : (
              <>
                <div className="page-tabs" role="tablist" aria-label="صفحه‌های کتاب">
                  {pages.map((item) => (
                    <button
                      key={item.pdf_page_index}
                      type="button"
                      className={`page-tab ${item.status} ${selectedIdx === item.pdf_page_index ? "active" : ""}`}
                      onClick={() => {
                        selectPageForEdit(item);
                        setSaveMessage("");
                      }}
                    >
                      <i />
                      <span>PDF {item.pdf_page_index}</span>
                      {item.printed_page_number !== null && <small>(چاپی {item.printed_page_number})</small>}
                    </button>
                  ))}
                </div>

                {selectedPage && (
                  <div className="review-grid">
                    <div className="review-image-box">
                      <div className="review-image-head">
                        <span>تصویر رندرشده (صفحهٔ PDF {selectedPage.pdf_page_index})</span>
                        <span className={`badge-pill ${selectedPage.status}`}>
                          {statusLabel[selectedPage.status] ?? selectedPage.status}
                          {selectedPage.edited_by_human ? " · ویرایش انسانی" : ""}
                        </span>
                      </div>
                      <div className="review-image-frame">
                        {imageError ? (
                          <div className="review-image-missing">
                            <FileText size={20} />
                            <span>تصویر صفحه در دسترس نیست</span>
                          </div>
                        ) : pageImageSrc ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={pageImageSrc}
                            alt={`صفحه PDF ${selectedPage.pdf_page_index}`}
                            onError={() => setImageError(true)}
                          />
                        ) : (
                          <div className="review-image-missing">
                            <LoaderCircle className="spin" size={18} />
                            <span>در حال بارگذاری تصویر...</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <form className="review-form" onSubmit={handleSavePage}>
                      {selectedPage.warnings.length > 0 && (
                        <div className="review-alerts">
                          <b>هشدارهای پردازش خودکار:</b>
                          <ul>
                            {selectedPage.warnings.map((warning, idx) => (
                              <li key={idx}>{warning}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {selectedPage.error_message && (
                        <div className="inline-error">{selectedPage.error_message}</div>
                      )}

                      <div className="form-row">
                        <label className="form-field">
                          <span>شمارهٔ صفحهٔ چاپی</span>
                          <input
                            type="number"
                            min={0}
                            placeholder="خالی = بدون شماره"
                            value={editPrintedPage}
                            onChange={(event) => setEditPrintedPage(event.target.value)}
                          />
                        </label>
                        <label className="form-field">
                          <span>شمارهٔ فصل</span>
                          <input
                            type="number"
                            min={0}
                            placeholder="مثلاً 1"
                            value={editChapterNumber}
                            onChange={(event) => setEditChapterNumber(event.target.value)}
                          />
                        </label>
                      </div>

                      <label className="form-field">
                        <span>عنوان فصل</span>
                        <input
                          placeholder="مثلاً حرکت بر خط راست"
                          value={editChapterTitle}
                          onChange={(event) => setEditChapterTitle(event.target.value)}
                        />
                      </label>

                      <label className="form-field">
                        <span>متن مارک‌داون و LaTeX صفحه</span>
                        <textarea
                          className="review-markdown"
                          rows={12}
                          value={editMarkdown}
                          onChange={(event) => setEditMarkdown(event.target.value)}
                        />
                      </label>

                      {selectedPage.visual_elements.length > 0 && (
                        <div className="review-visuals">
                          <span>اجزای تصویری استخراج‌شده:</span>
                          {selectedPage.visual_elements.map((el, idx) => (
                            <div key={idx} className="review-visual-item">
                              <b>{el.label ?? "شکل"}</b> ({el.type ?? "تصویر"}) — {el.scientific_description}
                            </div>
                          ))}
                        </div>
                      )}

                      {saveError && (
                        <div className="inline-error">
                          {saveError}
                          <button type="button" onClick={() => setSaveError("")}>
                            <XCircle size={15} />
                          </button>
                        </div>
                      )}
                      {saveMessage && (
                        <div className="success-note">
                          <CheckCircle2 size={15} />
                          {saveMessage}
                        </div>
                      )}

                      <button className="primary-button admin-submit" type="submit" disabled={savingPage}>
                        {savingPage ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}
                        ذخیره و تأیید نهایی صفحه
                      </button>
                    </form>
                  </div>
                )}
              </>
            )}
          </section>
        )}

        {previewOpen && book && (
          <section className="preview-panel">
            <div className="preview-head">
              <div>
                <b>پیش‌نمایش کتاب</b>
                <span>تصویر اصلی در کنار متن استخراج‌شده و خروجی KaTeX</span>
              </div>
              <div className="preview-controls">
                {(["all", "needs_review", "done", "failed"] as const).map((statusKey) => {
                  const count =
                    statusKey === "all" ? processedPages : (book.pages[statusKey] ?? 0);
                  if (statusKey !== "all" && count === 0) return null;
                  return (
                    <button
                      key={statusKey}
                      type="button"
                      className={`preview-filter ${previewStatus === statusKey ? "active" : ""}`}
                      onClick={() => setPreviewStatus(statusKey)}
                    >
                      {statusKey === "all" ? "همه" : statusLabel[statusKey]} ({count})
                    </button>
                  );
                })}
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => setPreviewOpen(false)}
                  aria-label="بستن پیش‌نمایش"
                >
                  <XCircle size={18} />
                </button>
              </div>
            </div>
            <iframe
              key={`${book.id}-${previewStatus}-${previewVersion}`}
              title="پیش‌نمایش صفحات کتاب"
              srcDoc={previewHtml || "<html><body dir='rtl' style='font-family:sans-serif;padding:24px;color:#667'>در حال بارگذاری پیش‌نمایش...</body></html>"}
            />
          </section>
        )}
        </>
        )}
      </div>
    </main>
  );
}
