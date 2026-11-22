"use client";

import { useEffect, useState } from "react";
import { toPersianDigits, type BookListItem } from "@/lib/phase5";

type BranchOption = {
  code: string;
  title: string;
  min_grade: number;
  max_grade: number;
};
type FieldOption = {
  code: string;
  title: string;
  branch_code: string;
  branch_title: string;
};

type Props = {
  value: number | null;
  onChange: (bookId: number | null) => void;
};

/** Curriculum-aware grade → branch/field → textbook selector. */
export default function BookGradePicker({ value, onChange }: Props) {
  const [grade, setGrade] = useState(1);
  const [branches, setBranches] = useState<BranchOption[]>([]);
  const [branchCode, setBranchCode] = useState("");
  const [fields, setFields] = useState<FieldOption[]>([]);
  const [fieldCode, setFieldCode] = useState("");
  const [books, setBooks] = useState<BookListItem[]>([]);

  const isUpperSecondary = grade >= 10;
  const fieldRequired = isUpperSecondary && (branchCode === "theoretical" || fields.length > 0);

  useEffect(() => {
    if (!isUpperSecondary) {
      setBranches([]);
      setBranchCode("");
      return;
    }
    const controller = new AbortController();
    fetch(`/api/v1/curriculum/branches?grade_number=${grade}`, {
      cache: "no-store",
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("شاخه‌های تحصیلی دریافت نشد");
        const data = (await response.json()) as BranchOption[];
        setBranches(data);
        setBranchCode((current) =>
          data.some((item) => item.code === current)
            ? current
            : data.find((item) => item.code === "theoretical")?.code ?? data[0]?.code ?? ""
        );
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setBranches([]);
        setBranchCode("");
      });
    return () => controller.abort();
  }, [grade, isUpperSecondary]);

  useEffect(() => {
    if (!isUpperSecondary || !branchCode) {
      setFields([]);
      setFieldCode("");
      return;
    }
    const controller = new AbortController();
    fetch(`/api/v1/curriculum/fields?branch_code=${encodeURIComponent(branchCode)}`, {
      cache: "no-store",
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("رشته‌های تحصیلی دریافت نشد");
        const data = (await response.json()) as FieldOption[];
        setFields(data);
        setFieldCode((current) => data.some((item) => item.code === current) ? current : "");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setFields([]);
        setFieldCode("");
      });
    return () => controller.abort();
  }, [branchCode, isUpperSecondary]);

  useEffect(() => {
    if (isUpperSecondary && (!branchCode || (fieldRequired && !fieldCode))) {
      setBooks([]);
      return;
    }
    const query = new URLSearchParams({ grade_number: String(grade) });
    if (isUpperSecondary) {
      query.set("branch_code", branchCode);
      if (fieldCode) query.set("field_code", fieldCode);
    }
    const controller = new AbortController();
    fetch(`/api/v1/curriculum/books?${query.toString()}`, {
      cache: "no-store",
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("کتاب‌های این انتخاب دریافت نشد");
        const data = (await response.json()) as BookListItem[];
        setBooks(data.filter((book) => book.status === "ready" || book.status === "done" || !book.status));
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setBooks([]);
      });
    return () => controller.abort();
  }, [grade, branchCode, fieldCode, fieldRequired, isUpperSecondary]);

  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <label>
        پایه{" "}
        <select
          value={grade}
          onChange={(event) => {
            const next = Number(event.target.value);
            setGrade(next);
            setBranchCode(next >= 10 ? "theoretical" : "");
            setFieldCode("");
            setBooks([]);
            onChange(null);
          }}
        >
          {Array.from({ length: 12 }, (_, i) => i + 1).map((item) => (
            <option key={item} value={item}>{toPersianDigits(item)}</option>
          ))}
        </select>
      </label>
      {isUpperSecondary && (
        <label>
          شاخه{" "}
          <select
            value={branchCode}
            onChange={(event) => {
              setBranchCode(event.target.value);
              setFieldCode("");
              setBooks([]);
              onChange(null);
            }}
          >
            <option value="">انتخاب شاخه</option>
            {branches.map((item) => <option key={item.code} value={item.code}>{item.title}</option>)}
          </select>
        </label>
      )}
      {isUpperSecondary && (branchCode === "theoretical" || fields.length > 0) && (
        <label>
          رشته{" "}
          <select
            value={fieldCode}
            onChange={(event) => {
              setFieldCode(event.target.value);
              setBooks([]);
              onChange(null);
            }}
          >
            <option value="">انتخاب رشته</option>
            {fields.map((item) => <option key={item.code} value={item.code}>{item.title}</option>)}
          </select>
        </label>
      )}
      <label>
        کتاب{" "}
        <select
          value={value ?? ""}
          onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
          disabled={books.length === 0}
        >
          <option value="">انتخاب کنید</option>
          {books.map((book) => (
            <option key={book.id} value={book.id}>
              {[book.title, book.academic_year_code, book.edition_label, book.print_year]
                .filter(Boolean)
                .join(" — ")}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
