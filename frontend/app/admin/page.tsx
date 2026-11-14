"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BookOpen, CheckCircle2, ExternalLink, FileUp, LoaderCircle, ShieldAlert, Sparkles, XCircle } from "lucide-react";

type BookStatus = {
  id: number;
  title: string;
  total_pdf_pages: number;
  status: string;
  pages: Record<string, number>;
};

const majors = [
  { code: "math_physics", label: "ریاضی‌فیزیک" },
  { code: "experimental", label: "علوم تجربی" },
  { code: "humanities", label: "علوم انسانی" },
];

export default function AdminPage() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("فیزیک ۳");
  const [grade, setGrade] = useState(12);
  const [major, setMajor] = useState("math_physics");
  const [startPage, setStartPage] = useState(8);
  const [endPage, setEndPage] = useState(12);
  const [book, setBook] = useState<BookStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");

  useEffect(() => {
    if (!book || !["ingesting"].includes(book.status)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/v1/admin/books/${book.id}/status`, { cache: "no-store" });
        const payload = (await response.json()) as BookStatus;
        if (active && response.ok) setBook(payload);
      } catch {
        if (active) setError("وضعیت پردازش دریافت نشد؛ ارتباط بک‌اند را بررسی کن.");
      }
    }, 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [book]);

  const processedPages = useMemo(() => book ? Object.values(book.pages).reduce((total, count) => total + count, 0) : 0, [book]);
  const progress = book?.total_pdf_pages ? Math.min(100, (processedPages / book.total_pdf_pages) * 100) : 0;

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) { setError("ابتدا فایل PDF را انتخاب کن."); return; }
    if (startPage < 1 || endPage < startPage) { setError("بازهٔ صفحه‌ها معتبر نیست."); return; }
    setSubmitting(true);
    setError("");
    setBook(null);
    setPreviewOpen(false);
    setUploadMessage("");
    const form = new FormData();
    form.set("pdf_file", file);
    form.set("grade_number", String(grade));
    form.set("book_title", title);
    form.set("start_page", String(startPage));
    form.set("end_page", String(endPage));
    if (grade >= 10) form.set("major_code", major);
    try {
      const response = await fetch("/api/v1/admin/books/upload-and-ingest", { method: "POST", body: form });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "آپلود و پردازش شروع نشد.");
      setUploadMessage(`پردازش کتاب با شناسهٔ ${payload.book_id} شروع شد.`);
      setBook({ id: payload.book_id, title, total_pdf_pages: endPage - startPage + 1, status: "ingesting", pages: {} });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "خطا در ارتباط با سرور");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="admin-shell" dir="rtl">
      <header className="admin-topbar">
        <div className="admin-brand"><div className="brand-mark">ه</div><div><b>مدیریت هم‌درس</b><span>مرکز محتوای آموزشی</span></div></div>
        <Link className="back-link" href="/"><ArrowRight size={17} /> بازگشت به کلاس</Link>
      </header>
      <div className="admin-content">
        <div className="admin-heading"><div><span className="eyebrow">مدیریت کتابخانه</span><h1>افزودن کتاب درسی</h1><p>کتاب را وارد کن، چند صفحه را آزمایشی پردازش کن و خروجی را با PDF بسنج.</p></div><div className="admin-heading-mark"><BookOpen size={25} /></div></div>
        <div className="admin-warning"><ShieldAlert size={18} /><span><b>محیط توسعهٔ محلی</b> · API مدیریت هنوز ورود ادمین ندارد؛ این پنل را عمومی منتشر نکن.</span></div>

        <div className="admin-grid">
          <section className="admin-card">
            <div className="card-heading"><div><h2>اطلاعات کتاب</h2><p>برای تست اول، بازه‌ای کوچک از فصل را وارد کن.</p></div><span className="step-badge">۱</span></div>
            <form onSubmit={submit} className="admin-form">
              <label className="form-field"><span>عنوان کتاب</span><input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
              <div className="form-row">
                <label className="form-field"><span>پایه</span><select value={grade} onChange={(event) => setGrade(Number(event.target.value))}>{Array.from({ length: 12 }, (_, index) => index + 1).map((number) => <option key={number} value={number}>{number === 12 ? "دوازدهم" : `پایهٔ ${number}`}</option>)}</select></label>
                {grade >= 10 && <label className="form-field"><span>رشته</span><select value={major} onChange={(event) => setMajor(event.target.value)}>{majors.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>}
              </div>
              <div className="form-row">
                <label className="form-field"><span>از صفحهٔ PDF</span><input type="number" min={1} value={startPage} onChange={(event) => setStartPage(Number(event.target.value))} /></label>
                <label className="form-field"><span>تا صفحهٔ PDF</span><input type="number" min={1} value={endPage} onChange={(event) => setEndPage(Number(event.target.value))} /></label>
              </div>
              <label className={`pdf-dropzone ${file ? "has-file" : ""}`}>
                <input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                <span className="drop-icon">{file ? <CheckCircle2 size={21} /> : <FileUp size={21} />}</span>
                <b>{file ? file.name : "فایل PDF کتاب را انتخاب کن"}</b>
                <small>{file ? `${(file.size / (1024 * 1024)).toFixed(1)} مگابایت` : "فقط PDF · فایل در مخزن خصوصی پروژه ذخیره می‌شود"}</small>
              </label>
              {error && <div className="inline-error">{error}<button type="button" onClick={() => setError("")}><XCircle size={15} /></button></div>}
              <button className="primary-button admin-submit" type="submit" disabled={submitting}>{submitting ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}آپلود و شروع پردازش</button>
            </form>
          </section>

          <section className="admin-card progress-card">
            <div className="card-heading"><div><h2>وضعیت پردازش</h2><p>استخراج صفحه‌به‌صفحه همراه با بازبینی‌پذیری.</p></div><span className="step-badge">۲</span></div>
            {!book ? <div className="admin-empty"><div><BookOpen size={22} /></div><b>هنوز کتابی برای پردازش نیست</b><span>بعد از آپلود، وضعیت هر صفحه اینجا نمایش داده می‌شود.</span></div> : (
              <div className="progress-content">
                <div className="processing-book"><div className="mini-book-icon"><BookOpen size={20} /></div><div><b>{book.title}</b><span>شناسهٔ کتاب: {book.id}</span></div><span className={`status-chip ${book.status}`}>{book.status === "ingesting" ? <><LoaderCircle className="spin" size={13} />در حال پردازش</> : book.status === "ready" ? <><CheckCircle2 size={13} />آمادهٔ بازبینی</> : <><XCircle size={13} />ناموفق</>}</span></div>
                <div className="progress-label"><span>صفحه‌های پردازش‌شده</span><b>{processedPages} / {book.total_pdf_pages}</b></div><div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
                <div className="status-counts"><div><i className="done-dot" />موفق <b>{book.pages.done ?? 0}</b></div><div><i className="review-dot" />بازبینی <b>{book.pages.needs_review ?? 0}</b></div><div><i className="failed-dot" />خطا <b>{book.pages.failed ?? 0}</b></div></div>
                {uploadMessage && <div className="success-note"><CheckCircle2 size={15} />{uploadMessage}</div>}
                {book.status !== "ingesting" && <button className="outline-button preview-button" onClick={() => setPreviewOpen(true)}><ExternalLink size={16} />بازکردن پیش‌نمایش مقایسه‌ای</button>}
              </div>
            )}
            <div className="review-tip"><Sparkles size={15} /><span>صفحه‌های نیازمند بازبینی را پیش از ایندکس و استفادهٔ آموزشی اصلاح کن.</span></div>
          </section>
        </div>
        {previewOpen && book && <section className="preview-panel"><div className="preview-head"><div><b>پیش‌نمایش کتاب</b><span>تصویر اصلی در کنار متن استخراج‌شده</span></div><button className="icon-button" onClick={() => setPreviewOpen(false)} aria-label="بستن پیش‌نمایش"><XCircle size={18} /></button></div><iframe title="پیش‌نمایش صفحات کتاب" src={`/api/v1/admin/books/${book.id}/preview?status=all`} /></section>}
      </div>
    </main>
  );
}
