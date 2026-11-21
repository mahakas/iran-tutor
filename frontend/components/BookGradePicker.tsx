"use client";

import { useEffect, useState } from "react";
import { toPersianDigits, type BookListItem } from "@/lib/phase5";

type Props = {
  value: number | null;
  onChange: (bookId: number | null) => void;
};

/** Grade → book picker using the public curriculum list (grade_number required by the API). */
export default function BookGradePicker({ value, onChange }: Props) {
  const [grade, setGrade] = useState(1);
  const [books, setBooks] = useState<BookListItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await fetch(`/api/v1/curriculum/books?grade_number=${grade}`, { cache: "no-store", credentials: "same-origin" });
      if (!res.ok) {
        if (!cancelled) setBooks([]);
        return;
      }
      const payload = (await res.json()) as BookListItem[];
      if (!cancelled) setBooks(payload.filter((book) => book.status === "ready" || book.status === "done" || !book.status));
    })();
    return () => {
      cancelled = true;
    };
  }, [grade]);

  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      <label>
        پایه{" "}
        <select value={grade} onChange={(event) => setGrade(Number(event.target.value))}>
          {Array.from({ length: 12 }, (_, i) => i + 1).map((g) => (
            <option key={g} value={g}>
              {toPersianDigits(g)}
            </option>
          ))}
        </select>
      </label>
      <label>
        کتاب{" "}
        <select value={value ?? ""} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}>
          <option value="">انتخاب کنید</option>
          {books.map((book) => (
            <option key={book.id} value={book.id}>
              {book.title}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
