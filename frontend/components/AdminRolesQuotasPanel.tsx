"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Gauge,
  LoaderCircle,
  RefreshCw,
  Save,
  ShieldCheck,
  Users,
} from "lucide-react";

export type AdminRoleUser = {
  id: string;
  phone_number?: string;
  full_name?: string | null;
  role?: string;
  grade_level?: number | null;
  major?: string | null;
  plan_id?: number | null;
  is_active?: boolean;
};

type QuotaPolicy = {
  daily_tokens: number;
  monthly_tokens: number;
  daily_requests: number;
  requests_per_minute: number;
};

const ROLE_LABELS: Record<string, string> = {
  admin: "مدیر",
  teacher: "معلم",
  student: "دانش‌آموز",
  guardian: "ولی",
};

const MAJOR_LABELS: Record<string, string> = {
  math_physics: "ریاضی‌فیزیک",
  experimental: "علوم تجربی",
  humanities: "علوم انسانی",
};

const POLICY_FIELDS: { key: keyof QuotaPolicy; label: string; hint: string }[] = [
  { key: "daily_tokens", label: "سقف توکن روزانه", hint: "برای هر کاربر در هر روز" },
  { key: "monthly_tokens", label: "سقف توکن ماهانه", hint: "برای هر کاربر در هر ماه" },
  { key: "daily_requests", label: "سقف درخواست روزانه", hint: "قبل از هر فراخوانی بررسی می‌شود" },
  { key: "requests_per_minute", label: "سقف درخواست در دقیقه", hint: "پنجرهٔ لغزان Redis" },
];

export default function AdminRolesQuotasPanel({
  authHeaders,
  onUnauthorized,
}: {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
}) {
  const [policy, setPolicy] = useState<QuotaPolicy | null>(null);
  const [defaults, setDefaults] = useState<QuotaPolicy | null>(null);
  const [users, setUsers] = useState<AdminRoleUser[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [busyUser, setBusyUser] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const handle = useCallback(
    (status: number) => {
      if (status === 401) onUnauthorized();
      return status >= 200 && status < 300;
    },
    [onUnauthorized],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [policyRes, usersRes] = await Promise.all([
        fetch("/api/v1/admin/quotas", { credentials: "same-origin", headers: authHeaders }),
        fetch("/api/v1/admin/users?limit=50", {
          credentials: "same-origin",
          headers: authHeaders,
        }),
      ]);
      if (!handle(policyRes.status) || !handle(usersRes.status)) {
        setError("دسترسی مدیریت منقضی شده است.");
        return;
      }
      const policyPayload = await policyRes.json();
      setPolicy(policyPayload.policy as QuotaPolicy);
      setDefaults(policyPayload.defaults as QuotaPolicy);
      const usersPayload = await usersRes.json();
      const rows = Array.isArray(usersPayload)
        ? usersPayload
        : (usersPayload.users ?? usersPayload.items ?? []);
      setUsers(rows as AdminRoleUser[]);
    } catch {
      setError("بارگذاری اطلاعات کاربران ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, handle]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function savePolicy(event: React.FormEvent) {
    event.preventDefault();
    if (!policy) return;
    setSavingPolicy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/v1/admin/quotas", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(policy),
      });
      if (!handle(response.status)) {
        setError("ذخیرهٔ سیاست سهمیه ناموفق بود.");
        return;
      }
      setMessage("سیاست سهمیه و نرخ ذخیره شد.");
      await load();
    } finally {
      setSavingPolicy(false);
    }
  }

  async function updateUser(
    userId: string,
    patch: Partial<Pick<AdminRoleUser, "role" | "grade_level" | "major" | "is_active">>,
  ) {
    setBusyUser(userId);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/v1/admin/users/${userId}/role`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(patch),
      });
      if (!handle(response.status)) {
        const detail = await response.json().catch(() => ({}));
        setError(detail?.detail ?? "به‌روزرسانی نقش ناموفق بود.");
        return;
      }
      const payload = await response.json();
      setUsers((prev) =>
        prev.map((user) =>
          user.id === userId ? { ...user, ...(payload.user as AdminRoleUser) } : user,
        ),
      );
      setMessage("نقش و دسترسی کاربر به‌روزرسانی شد.");
    } finally {
      setBusyUser(null);
    }
  }

  const visibleUsers = users.filter((user) => {
    const term = search.trim().toLowerCase();
    if (!term) return true;
    return (
      (user.full_name ?? "").toLowerCase().includes(term) ||
      (user.phone_number ?? "").includes(term) ||
      user.id.toLowerCase().includes(term)
    );
  });

  if (loading) {
    return (
      <div className="admin-card admin-empty">
        <div>
          <LoaderCircle size={22} className="spin" />
        </div>
        <b>بارگذاری نقش‌ها و سهمیه‌ها…</b>
      </div>
    );
  }

  return (
    <div className="admin-billing-stack">
      {message && (
        <div className="success-note admin-banner">
          <CheckCircle2 size={15} />
          {message}
        </div>
      )}
      {error && <div className="inline-error admin-banner">{error}</div>}

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>سیاست سهمیه و محدودسازی نرخ</h2>
            <p>
              قبل از هر فراخوانی هوش مصنوعی، این محدودیت‌ها اعمال می‌شوند. مقادیر در تنظیمات
              سامانه ذخیره می‌شوند و بلافاصله فعال می‌گردند.
            </p>
          </div>
          <div className="admin-chip-row">
            {defaults && (
              <button
                type="button"
                className="admin-theme-chip"
                onClick={() => setPolicy({ ...defaults })}
              >
                بازگردانی پیش‌فرض
              </button>
            )}
            <span className="step-badge">
              <Gauge size={14} />
            </span>
          </div>
        </div>

        {policy && (
          <form className="admin-form" onSubmit={savePolicy}>
            <div className="admin-grid">
              {POLICY_FIELDS.map((field) => (
                <label key={field.key} className="form-field">
                  <span>
                    {field.label} <small className="admin-muted">({field.hint})</small>
                  </span>
                  <input
                    dir="ltr"
                    type="number"
                    min={0}
                    value={policy[field.key]}
                    onChange={(event) =>
                      setPolicy({ ...policy, [field.key]: Number(event.target.value) || 0 })
                    }
                  />
                </label>
              ))}
            </div>
            <button className="primary-button admin-submit" type="submit" disabled={savingPolicy}>
              {savingPolicy ? <LoaderCircle size={17} className="spin" /> : <Save size={17} />}
              ذخیرهٔ سیاست سهمیه
            </button>
          </form>
        )}
      </section>

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>کاربران، نقش‌ها و سطوح دسترسی</h2>
            <p>
              نقش‌ها: مدیر، معلم، دانش‌آموز، ولی. فقط نقش «مدیر» به بخش مدیریت دسترسی دارد؛
              دانش‌آموز هرگز نمی‌تواند به تنظیمات هوش مصنوعی دست پیدا کند.
            </p>
          </div>
          <div className="admin-chip-row">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="جست‌وجوی نام یا شماره…"
            />
            <button type="button" className="admin-theme-chip" onClick={() => void load()}>
              <RefreshCw size={14} /> بازخوانی
            </button>
          </div>
        </div>

        {visibleUsers.length === 0 ? (
          <div className="admin-empty">
            <div>
              <Users size={22} />
            </div>
            <b>کاربری یافت نشد</b>
          </div>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>کاربر</th>
                  <th>نقش</th>
                  <th>پایه</th>
                  <th>رشته</th>
                  <th>وضعیت</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visibleUsers.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <b>{user.full_name || "بدون نام"}</b>
                      <div className="admin-muted" dir="ltr">
                        {user.phone_number ?? user.id}
                      </div>
                      <a className="admin-chip-btn" href={`/admin/users/${user.id}`} style={{ marginTop: 6, display: "inline-flex" }}>
                        پروندهٔ حافظه
                      </a>
                    </td>
                    <td>
                      <select
                        value={user.role ?? "student"}
                        onChange={(event) =>
                          void updateUser(user.id, { role: event.target.value })
                        }
                        disabled={busyUser === user.id}
                      >
                        {Object.entries(ROLE_LABELS).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select
                        value={user.grade_level ?? ""}
                        onChange={(event) =>
                          void updateUser(user.id, {
                            grade_level: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        disabled={busyUser === user.id}
                      >
                        <option value="">—</option>
                        {Array.from({ length: 12 }, (_, index) => index + 1).map((grade) => (
                          <option key={grade} value={grade}>
                            {grade}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select
                        value={user.major ?? ""}
                        onChange={(event) =>
                          void updateUser(user.id, { major: event.target.value || undefined })
                        }
                        disabled={busyUser === user.id}
                      >
                        <option value="">—</option>
                        {Object.entries(MAJOR_LABELS).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`admin-theme-chip ${user.is_active === false ? "" : "active"}`}
                        onClick={() =>
                          void updateUser(user.id, { is_active: !(user.is_active !== false) })
                        }
                        disabled={busyUser === user.id}
                      >
                        <ShieldCheck size={14} />
                        {user.is_active === false ? "غیرفعال" : "فعال"}
                      </button>
                    </td>
                    <td>
                      {busyUser === user.id && <LoaderCircle size={14} className="spin" />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
