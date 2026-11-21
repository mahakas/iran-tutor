"use client";

import { useState } from "react";
import {
  Activity,
  BookOpen,
  Cpu,
  Crown,
  Database,
  Eye,
  KeyRound,
  Layers,
  Menu,
  Palette,
  ShieldCheck,
  Sparkles,
  ToggleRight,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";

export type AdminNavKey =
  | "overview"
  | "observability"
  | "appearance"
  | "integrations"
  | "providers"
  | "capabilities"
  | "skills"
  | "flashcards"
  | "deep_learning"
  | "rich_study"
  | "books"
  | "kb"
  | "users"
  | "plans"
  | "roles";

type NavItem = { key: AdminNavKey; label: string; icon: LucideIcon };
type NavCategory = { title: string; items: NavItem[] };

// Five operational groups from the UI polish spec. Labels stay in Persian and match the
// previous flat tab bar so existing muscle memory still works.
export const ADMIN_NAV_CATEGORIES: NavCategory[] = [
  {
    title: "نمای کلی و مانیتورینگ",
    items: [
      { key: "overview", label: "نمای کلی و مانیتورینگ", icon: Activity },
      { key: "observability", label: "مرکز شفافیت (Observability)", icon: Eye },
      { key: "appearance", label: "ظاهر و دسترس‌پذیری", icon: Palette },
    ],
  },
  {
    title: "هوش مصنوعی و مسیردهی",
    items: [
      { key: "integrations", label: "هوش مصنوعی، API و درگاه‌ها", icon: Cpu },
      { key: "providers", label: "ارائه‌دهنده‌ها و مسیر مدل", icon: KeyRound },
    ],
  },
  {
    title: "قابلیت‌ها و مهارت‌ها",
    items: [
      { key: "capabilities", label: "قابلیت‌ها و فلگ‌ها", icon: ToggleRight },
      { key: "skills", label: "مهارت‌ها و پرامپت‌ها", icon: Sparkles },
      { key: "flashcards", label: "فلش‌کارت‌ها", icon: Layers },
      { key: "deep_learning", label: "یادگیری عمیق", icon: Layers },
      { key: "rich_study", label: "مطالعهٔ غنی", icon: Layers },
    ],
  },
  {
    title: "کتاب‌ها و پایگاه دانش",
    items: [
      { key: "books", label: "کتاب‌ها و پردازش PDF", icon: BookOpen },
      { key: "kb", label: "پایگاه دانش و مدل‌ها", icon: Database },
    ],
  },
  {
    title: "کاربران و سهمیه‌ها",
    items: [
      { key: "users", label: "کاربران و سهمیه‌ها", icon: Users },
      { key: "plans", label: "پلن‌ها و قیمت توکن", icon: Crown },
      { key: "roles", label: "نقش‌ها و سهمیه‌ها", icon: ShieldCheck },
    ],
  },
];

type Props = {
  active: string;
  onSelect: (key: AdminNavKey) => void;
};

export default function AdminSideNav({ active, onSelect }: Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const activeItem = ADMIN_NAV_CATEGORIES.flatMap((c) => c.items).find((i) => i.key === active);

  const choose = (key: AdminNavKey) => {
    onSelect(key);
    setDrawerOpen(false);
  };

  return (
    <>
      <button
        type="button"
        className="admin-nav-toggle"
        aria-expanded={drawerOpen}
        aria-controls="admin-side-nav"
        onClick={() => setDrawerOpen(true)}
      >
        <Menu size={18} /> <span>{activeItem?.label ?? "بخش‌های مدیریت"}</span>
      </button>
      {drawerOpen && (
        <button
          type="button"
          className="admin-nav-scrim"
          aria-label="بستن منوی مدیریت"
          onClick={() => setDrawerOpen(false)}
        />
      )}
      <nav
        id="admin-side-nav"
        className={`admin-side-nav ${drawerOpen ? "open" : ""}`}
        aria-label="بخش‌های پنل مدیریت"
      >
        <div className="admin-nav-drawer-head">
          <b>بخش‌های مدیریت</b>
          <button
            type="button"
            className="icon-button"
            aria-label="بستن منو"
            onClick={() => setDrawerOpen(false)}
          >
            <X size={18} />
          </button>
        </div>
        {ADMIN_NAV_CATEGORIES.map((category) => (
          <div className="admin-nav-group" key={category.title}>
            <span className="admin-nav-group-title">{category.title}</span>
            {category.items.map((item) => {
              const Icon = item.icon;
              const isActive = active === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  className={`admin-nav-item ${isActive ? "active" : ""}`}
                  aria-current={isActive ? "page" : undefined}
                  onClick={() => choose(item.key)}
                >
                  <Icon size={16} /> <span>{item.label}</span>
                </button>
              );
            })}
          </div>
        ))}
      </nav>
    </>
  );
}
