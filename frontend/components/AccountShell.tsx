"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CircleHelp,
  Crown,
  LoaderCircle,
  LogIn,
  LogOut,
  Phone,
  Settings,
  ShieldCheck,
  User as UserIcon,
} from "lucide-react";
import AccountAvatar from "@/components/AccountAvatar";
import { useAppContext } from "@/components/AppProvider";
import { COPY } from "@/lib/i18n";

type AccountShellProps = {
  title: string;
  subtitle?: string;
  requireAuth?: boolean;
  children: React.ReactNode;
};

export default function AccountShell({
  title,
  subtitle,
  requireAuth = true,
  children,
}: AccountShellProps) {
  const pathname = usePathname();
  const { user, authReady, preferences, openLoginModal, requestLogout } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const copy = COPY[lang];
  const BackArrow = lang === "en" ? ArrowLeft : ArrowRight;

  const navLinks = [
    { href: "/account/upgrade", label: copy.nav.upgrade, icon: Crown, match: "/account/upgrade" },
    { href: "/account/profile", label: copy.nav.profile, icon: UserIcon, match: "/account/profile" },
    {
      href: "/account/settings/general",
      label: copy.nav.settings,
      icon: Settings,
      match: "/account/settings",
    },
    { href: "/account/help", label: copy.nav.help, icon: CircleHelp, match: "/account/help" },
  ];

  return (
    <div className="account-page-shell" dir={lang === "en" ? "ltr" : "rtl"}>
      <header className="account-topbar">
        <div className="account-topbar-inner">
          <div className="account-topbar-left">
            <Link href="/" className="account-back-link">
              <BackArrow size={16} />
              <span>{copy.backToClassroom}</span>
            </Link>
            <div className="account-topbar-divider" />
            <Link href="/" className="account-brand-chip">
              <span className="brand-mark small-mark">{lang === "en" ? "D" : "د"}</span>
              <div>
                <b>{copy.brandName}</b>
                <span>{copy.accountSectionTitle}</span>
              </div>
            </Link>
          </div>

          <nav className="account-top-nav" aria-label={copy.accountSectionTitle}>
            {navLinks.map((item) => {
              const Icon = item.icon;
              const isActive = pathname?.startsWith(item.match);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`account-top-nav-item ${isActive ? "active" : ""}`}
                >
                  <Icon size={15} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          <div className="account-topbar-right">
            {user ? (
              <div className="account-topbar-user">
                <AccountAvatar size={30} />
                <span className="account-topbar-name">
                  {user.full_name ||
                    (preferences.privacy.show_phone_masked
                      ? user.masked_phone
                      : user.phone_number)}
                </span>
                <button
                  type="button"
                  className="account-topbar-logout"
                  onClick={requestLogout}
                  title={copy.menu.logOut}
                >
                  <LogOut size={15} />
                  <span>{copy.menu.logOut}</span>
                </button>
              </div>
            ) : authReady ? (
              <button
                type="button"
                className="primary-button"
                onClick={() => openLoginModal()}
              >
                <LogIn size={15} />
                <span>{copy.auth.loginCta}</span>
              </button>
            ) : null}
          </div>
        </div>
      </header>

      <main className="account-main">
        {requireAuth && !authReady ? (
          <div className="account-guard-card">
            <LoaderCircle className="spin" size={26} />
            <p>{lang === "en" ? "Verifying your session..." : "در حال بررسی نشست کاربری..."}</p>
          </div>
        ) : requireAuth && !user ? (
          <div className="account-guard-card">
            <div className="modal-icon">
              <ShieldCheck size={24} />
            </div>
            <h1>{copy.auth.loginPromptTitle}</h1>
            <p>{copy.auth.loginPromptBody}</p>
            <div className="account-guard-actions">
              <button
                type="button"
                className="primary-button"
                onClick={() => openLoginModal()}
              >
                <Phone size={16} />
                <span>{copy.auth.loginCta}</span>
              </button>
              <Link href="/" className="outline-button">
                {copy.backToClassroom}
              </Link>
            </div>
          </div>
        ) : (
          <div className="account-container">
            <div className="account-page-header">
              <h1>{title}</h1>
              {subtitle && <p>{subtitle}</p>}
            </div>
            {children}
          </div>
        )}
      </main>
    </div>
  );
}
