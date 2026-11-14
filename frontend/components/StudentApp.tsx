"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUp, AudioLines, BookOpen, Check, ChevronDown, CircleHelp, Clock3,
  FileImage, GraduationCap, LoaderCircle, Menu, MessageSquare, Mic, Paperclip,
  Plus, Send, ShieldCheck, Sparkles, Square, Trash2, X,
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
  Source,
  TutorMode,
  TutorResponse,
} from "@/lib/types";

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

function makeChatTitle(text: string) {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return "گفت‌وگو با معلم";
  return clean.length > 44 ? `${clean.slice(0, 44)}…` : clean;
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

  const currentGrade = grades.find((grade) => grade.number === gradeNumber);
  const selectedBook = books.find((book) => String(book.id) === bookId);
  const hasMajor = currentGrade?.has_major ?? false;
  const canAsk = Boolean(bookId && !busy);

  const loadChatHistory = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/tutor/sessions", { cache: "no-store" });
      if (!response.ok) return;
      const items = (await response.json()) as ChatSessionSummary[];
      setChatHistory(items);
    } catch {
      // Ignore silent history fetch failure
    }
  }, []);

  const loadExamHistory = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/exams", { cache: "no-store" });
      if (!response.ok) return;
      const items = (await response.json()) as ExamSummary[];
      setExamHistory(items);
    } catch {
      // Ignore silent history fetch failure
    }
  }, []);

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
    fetch("/api/v1/system/status")
      .then((response) => response.ok ? response.json() : null)
      .then((status: { mode?: string } | null) => { if (active) setDemoMode(status?.mode === "demo"); })
      .catch(() => { if (active) setDemoMode(false); });
    fetch("/api/v1/tutor/sessions", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((items: ChatSessionSummary[] | null) => { if (active && items) setChatHistory(items); })
      .catch(() => undefined);
    fetch("/api/v1/exams", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((items: ExamSummary[] | null) => { if (active && items) setExamHistory(items); })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

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
      try {
        if (existingSessionId) {
          const response = await fetch(`/api/v1/tutor/sessions/${existingSessionId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode, messages: nextMessages }),
          });
          if (response.ok) {
            await loadChatHistory();
            return existingSessionId;
          }
        }
        const response = await fetch("/api/v1/tutor/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
        await loadChatHistory();
        return created.id;
      } catch {
        return existingSessionId;
      }
    },
    [loadChatHistory]
  );

  const sendMessage = useCallback(async () => {
    const query = draft.trim();
    if ((!query && !imageFile && !audioFile) || !bookId || gradeNumber === null || busy) return;
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
            form.set(imageFile ? "image" : "audio", imageFile ?? audioFile as File);
            form.set("grade_number", String(gradeNumber));
            form.set("book_id", bookId);
            form.set("mode", tutoringMode);
            if (hasMajor && majorCode) form.set("major_code", majorCode);
            if (imageFile) return fetch("/api/v1/tutor/ask-image", { method: "POST", body: form });
            return fetch("/api/v1/tutor/ask-audio", { method: "POST", body: form });
          })()
        : fetch("/api/v1/tutor/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query, grade_number: gradeNumber, major_code: hasMajor ? majorCode : null, book_id: Number(bookId), mode: tutoringMode }),
          }));
      const payload = await response.json();
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
  }, [activeChatId, audioFile, bookId, busy, clearAttachments, draft, gradeNumber, hasMajor, imageFile, majorCode, messages, persistConversation, tutoringMode]);

  const openChatSession = async (sessionId: string) => {
    setMessageError("");
    try {
      const response = await fetch(`/api/v1/tutor/sessions/${sessionId}`, { cache: "no-store" });
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
    try {
      const response = await fetch(`/api/v1/tutor/sessions/${sessionId}`, { method: "DELETE" });
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
    setSidebarOpen(false);
    setExamHistoryOpen(true);
    setHistoryLoading(true);
    await loadExamHistory();
    setHistoryLoading(false);
  };

  const openSavedExam = async (examId: string) => {
    setBusy(true);
    setMessageError("");
    try {
      const response = await fetch(`/api/v1/exams/${examId}`, { cache: "no-store" });
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
    setBusy(true);
    setMessageError("");
    try {
      const response = await fetch("/api/v1/exams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grade_number: gradeNumber,
          major_code: hasMajor ? majorCode : null,
          book_id: Number(bookId),
          question_count: questionCount,
          time_limit_minutes: timeLimit,
          exam_type: examType,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload, "ساخت آزمون انجام نشد"));
      setActiveExam(payload as Exam);
      setExamSetupOpen(false);
      void loadExamHistory();
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

  if (activeExam) {
    return (
      <ExamRunner
        exam={activeExam}
        onExit={() => {
          setActiveExam(null);
          void loadExamHistory();
        }}
      />
    );
  }

  return (
    <div className="app-shell" dir="rtl">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-brand">
          <div className="brand-mark">ه</div>
          <div><strong>هم‌درس</strong><span>معلم خصوصی هوشمند</span></div>
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
        <div className="sidebar-section-label recent-label">گفت‌وگوهای اخیر</div>
        {chatHistory.length > 0 ? (
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
        <Link className="admin-link" href="/admin"><ShieldCheck size={17} /><span>پنل مدیریت</span><span className="admin-local">محلی</span></Link>
        <div className="profile-row"><div className="avatar">د</div><div><b>دانش‌آموز</b><span>پلن آزمایشی</span></div><ChevronDown size={16} /></div>
      </aside>
      {sidebarOpen && <button className="sidebar-scrim" aria-label="بستن منو" onClick={() => setSidebarOpen(false)} />}

      <main className="main-panel">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="بازکردن منو" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button>
          <div className="context-title"><span className="online-indicator" /><div><b>{selectedBook?.title ?? "کلاس درس"}</b><span>{currentGrade?.title ?? "انتخاب پایه"}{hasMajor && majorCode ? ` · ${majors.find((major) => major.code === majorCode)?.title ?? ""}` : ""}</span></div><ChevronDown size={15} /></div>
          <div className="topbar-actions">{demoMode && <span className="private-badge demo-badge"><Sparkles size={14} /> حالت آزمایشی</span>}<span className="private-badge"><ShieldCheck size={14} /> فضای خصوصی</span><button className="icon-button help-button" aria-label="راهنما" onClick={() => setHelpOpen(true)}><CircleHelp size={18} /></button></div>
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
            <button className="mode-tab" onClick={() => setExamSetupOpen(true)}><GraduationCap size={15} />آزمون زمان‌دار</button>
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
              <div className="suggestion-grid">{suggestions.map((text) => <button key={text} onClick={() => { setDraft(text); inputRef.current?.focus(); }}><span>{text}</span><ArrowUp size={15} /></button>)}</div>
              <div className="trust-note"><ShieldCheck size={15} /> پاسخ‌ها همراه با ارجاع به فصل و صفحهٔ کتاب ارائه می‌شوند.</div>
            </div>
          ) : (
            <div className="message-list">
              {messages.map((message) => (
                <article key={message.id} className={`message-row ${message.role}`}>
                  {message.role === "assistant" ? <div className="assistant-avatar"><Sparkles size={15} /></div> : <div className="user-avatar">د</div>}
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
            <textarea ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); } }} placeholder={!bookId ? "اول پایه، رشته و کتابت را انتخاب کن" : tutoringMode === "problem_solver" ? "صورت تمرینت را بنویس یا از آن عکس بگیر..." : tutoringMode === "question_designer" ? "از کدام مبحث برایت سؤال طراحی کنم؟" : "از معلمت هر چیزی دربارهٔ درس بپرس..."} disabled={!bookId || busy} rows={2} />
            <div className="composer-tools">
              <div className="tool-group">
                <button className="tool-button" disabled={!bookId || busy} onClick={() => imageInputRef.current?.click()} title="پیوست تصویر"><Paperclip size={18} /><span>تصویر سؤال</span></button>
                <input ref={imageInputRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) { setImageFile(file); setAudioFile(null); } }} />
                <button className={`tool-button ${recording ? "recording" : ""}`} disabled={!bookId || busy} onClick={() => void startRecording()} title={recording ? "پایان ضبط" : "ضبط صدا"}>{recording ? <Square size={16} /> : <Mic size={18} />}<span>{recording ? "پایان ضبط" : "صدا"}</span></button>
                {recording && <span className="recording-status"><i />در حال ضبط</span>}
              </div>
              <button className="send-button" disabled={!canAsk || (!draft.trim() && !imageFile && !audioFile)} onClick={() => void sendMessage()} aria-label="ارسال پرسش">{busy ? <LoaderCircle className="spin" size={18} /> : <Send size={18} />}</button>
            </div>
          </div>
          <div className="composer-disclaimer"><span>هم‌درس ممکن است اشتباه کند؛ پاسخ را با کتاب درسی تطبیق بده.</span><span><Check size={13} /> اطلاعات رسانه‌ای برای این پرسش ذخیره نمی‌شود</span></div>
        </footer>
      </main>

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
          <div className="modal-icon"><CircleHelp size={22} /></div><span className="eyebrow">راهنمای هم‌درس</span><h2 id="help-modal-title">نحوهٔ استفاده</h2>
          <p>۱. پایه، رشته (برای پایه‌های ۱۰ تا ۱۲) و کتاب درسی را انتخاب کن.<br />۲. حالت یادگیری را از نوار ابزار برگزین: معلم خصوصی، حل تمرین، طراحی سؤال یا آزمون زمان‌دار.<br />۳. می‌توانی سوالت را تایپ کنی، عکس تمرین را پیوست کنی یا با صدا بپرسی. میانبر گفت‌وگوی تازه: Cmd/Ctrl + K.</p>
          <button className="primary-button modal-submit" onClick={() => setHelpOpen(false)}>متوجه شدم</button>
        </section>
      </div>}
    </div>
  );
}
