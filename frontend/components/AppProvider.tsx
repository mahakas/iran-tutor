"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { Check, LoaderCircle, LogOut, Phone, Send, X } from "lucide-react";
import { COPY } from "@/lib/i18n";
import {
  applyPreferencesToDocument,
  DEFAULT_PREFERENCES,
  normalizePreferencesClient,
  readCachedPreferences,
  writeCachedPreferences,
} from "@/lib/preferences";
import type { StudentUser, UserPreferences } from "@/lib/types";

const USER_TOKEN_KEY = "iran_tutor_user_token";

export function readStoredUserToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(USER_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function storeUserToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.sessionStorage.setItem(USER_TOKEN_KEY, token);
    } else {
      window.sessionStorage.removeItem(USER_TOKEN_KEY);
    }
  } catch {
    // ignore storage errors
  }
}

export function buildUserAuthHeaders(token: string | null): Record<string, string> {
  if (!token) return {};
  return {
    Authorization: `Bearer ${token}`,
    "X-User-Token": token,
  };
}

export type PreferencesPatch = Partial<{
  general: Partial<UserPreferences["general"]>;
  appearance: Partial<
    Omit<UserPreferences["appearance"], "light" | "dark"> & {
      light: Partial<UserPreferences["appearance"]["light"]>;
      dark: Partial<UserPreferences["appearance"]["dark"]>;
    }
  >;
  notifications: Partial<UserPreferences["notifications"]>;
  privacy: Partial<UserPreferences["privacy"]>;
}>;

type AppContextValue = {
  user: StudentUser | null;
  token: string | null;
  authReady: boolean;
  preferences: UserPreferences;
  systemIsDark: boolean;
  getActiveToken: () => string | null;
  setAuthSession: (token: string | null, user: StudentUser | null) => void;
  setUser: React.Dispatch<React.SetStateAction<StudentUser | null>>;
  refreshAccount: () => Promise<StudentUser | null>;
  authFetch: (input: string, init?: RequestInit) => Promise<Response>;
  updatePreferences: (patch: PreferencesPatch) => Promise<UserPreferences | null>;
  resetPreferences: (
    section: "all" | "general" | "appearance" | "notifications" | "privacy"
  ) => Promise<UserPreferences | null>;
  openLoginModal: (notice?: string) => void;
  requestLogout: () => void;
  performLogoutNow: () => Promise<void>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useAppContext must be used within AppProvider");
  }
  return ctx;
}

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return fallback;
}

function mergePrefsLocal(current: UserPreferences, patch: PreferencesPatch): UserPreferences {
  return normalizePreferencesClient({
    general: { ...current.general, ...(patch.general ?? {}) },
    appearance: {
      ...current.appearance,
      ...(patch.appearance ?? {}),
      light: { ...current.appearance.light, ...(patch.appearance?.light ?? {}) },
      dark: { ...current.appearance.dark, ...(patch.appearance?.dark ?? {}) },
    },
    notifications: { ...current.notifications, ...(patch.notifications ?? {}) },
    privacy: { ...current.privacy, ...(patch.privacy ?? {}) },
  });
}

export default function AppProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const tokenRef = useRef<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<StudentUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [preferences, setPreferences] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [systemIsDark, setSystemIsDark] = useState(false);

  // Auth modal state
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

  // Logout confirmation dialog state
  const [logoutModalOpen, setLogoutModalOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);

  const getActiveToken = useCallback((): string | null => {
    return tokenRef.current ?? readStoredUserToken();
  }, []);

  const clearClientAuth = useCallback(() => {
    tokenRef.current = null;
    setToken(null);
    storeUserToken(null);
    setUser(null);
    writeCachedPreferences(null);
    setPreferences(DEFAULT_PREFERENCES);
  }, []);

  const setAuthSession = useCallback(
    (nextToken: string | null, nextUser: StudentUser | null) => {
      tokenRef.current = nextToken;
      setToken(nextToken);
      storeUserToken(nextToken);
      setUser(nextUser);
      if (nextUser?.preferences) {
        const normalized = normalizePreferencesClient(nextUser.preferences);
        setPreferences(normalized);
        writeCachedPreferences(normalized);
      } else if (!nextUser) {
        writeCachedPreferences(null);
        setPreferences(DEFAULT_PREFERENCES);
      }
    },
    []
  );

  // Sync system dark-mode listener on mount
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (event: MediaQueryListEvent) => setSystemIsDark(event.matches);
    const initialTimer = window.setTimeout(() => {
      setSystemIsDark(mq.matches);
      const cached = readCachedPreferences();
      if (cached && readStoredUserToken()) {
        setPreferences(cached);
      }
    }, 0);
    mq.addEventListener?.("change", handler);
    return () => {
      window.clearTimeout(initialTimer);
      mq.removeEventListener?.("change", handler);
    };
  }, []);

  // Apply CSS variables & document dir/lang whenever preferences or system theme change
  useEffect(() => {
    applyPreferencesToDocument(preferences, systemIsDark);
  }, [preferences, systemIsDark]);

  const updateUserSynced = useCallback(
    (updater: React.SetStateAction<StudentUser | null>) => {
      setUser(updater);
      if (typeof updater !== "function") {
        if (updater?.preferences) {
          const normalized = normalizePreferencesClient(updater.preferences);
          setPreferences(normalized);
          writeCachedPreferences(normalized);
        } else if (!updater) {
          setPreferences(DEFAULT_PREFERENCES);
          writeCachedPreferences(null);
        }
      }
    },
    []
  );

  const refreshAccount = useCallback(async (): Promise<StudentUser | null> => {
    const activeToken = getActiveToken();
    try {
      const res = await fetch("/api/v1/auth/me", {
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(activeToken),
      });
      if (!res.ok) {
        clearClientAuth();
        return null;
      }
      const payload = (await res.json()) as {
        authenticated?: boolean;
        user?: StudentUser | null;
      };
      if (payload.authenticated && payload.user) {
        tokenRef.current = activeToken;
        setToken(activeToken);
        setUser(payload.user);
        if (payload.user.preferences) {
          const normalized = normalizePreferencesClient(payload.user.preferences);
          setPreferences(normalized);
          writeCachedPreferences(normalized);
        }
        return payload.user;
      }
      clearClientAuth();
      return null;
    } catch {
      return null;
    }
  }, [clearClientAuth, getActiveToken]);

  useEffect(() => {
    const stored = readStoredUserToken();
    tokenRef.current = stored;
    let active = true;
    void (async () => {
      await refreshAccount();
      if (active) setAuthReady(true);
    })();
    return () => {
      active = false;
    };
  }, [refreshAccount]);

  // Re-validate session on browser bfcache restore (`pageshow`) so back button cannot resurrect logged-out views
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        void refreshAccount();
      }
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [refreshAccount]);

  // OTP resend timer
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = window.setInterval(() => {
      setResendCooldown((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [resendCooldown]);

  const authFetch = useCallback(
    async (input: string, init?: RequestInit): Promise<Response> => {
      const activeToken = getActiveToken();
      const mergedHeaders = new Headers(init?.headers ?? {});
      for (const [k, v] of Object.entries(buildUserAuthHeaders(activeToken))) {
        if (!mergedHeaders.has(k)) mergedHeaders.set(k, v);
      }
      const res = await fetch(input, {
        ...init,
        cache: "no-store",
        credentials: "same-origin",
        headers: mergedHeaders,
      });
      if (res.status === 401) {
        clearClientAuth();
        if (pathname?.startsWith("/account") && pathname !== "/account/help") {
          router.replace("/");
        }
      }
      return res;
    },
    [clearClientAuth, getActiveToken, pathname, router]
  );

  const updatePreferences = useCallback(
    async (patch: PreferencesPatch): Promise<UserPreferences | null> => {
      const optimistic = mergePrefsLocal(preferences, patch);
      setPreferences(optimistic);
      writeCachedPreferences(optimistic);

      const activeToken = getActiveToken();
      if (!activeToken && !user) return optimistic;

      const res = await authFetch("/api/v1/account/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (user?.preferences) {
          const rollback = normalizePreferencesClient(user.preferences);
          setPreferences(rollback);
          writeCachedPreferences(rollback);
        }
        throw new Error(errorMessage(payload, "ذخیره تنظیمات انجام نشد."));
      }
      const saved = normalizePreferencesClient(payload.preferences);
      setPreferences(saved);
      writeCachedPreferences(saved);
      if (payload.user) {
        setUser(payload.user as StudentUser);
      } else {
        setUser((prev) => (prev ? { ...prev, preferences: saved } : prev));
      }
      return saved;
    },
    [authFetch, getActiveToken, preferences, user]
  );

  const resetPreferences = useCallback(
    async (
      section: "all" | "general" | "appearance" | "notifications" | "privacy"
    ): Promise<UserPreferences | null> => {
      const res = await authFetch("/api/v1/account/preferences/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(errorMessage(payload, "بازنشانی تنظیمات انجام نشد."));
      }
      const saved = normalizePreferencesClient(payload.preferences);
      setPreferences(saved);
      writeCachedPreferences(saved);
      if (payload.user) {
        setUser(payload.user as StudentUser);
      } else {
        setUser((prev) => (prev ? { ...prev, preferences: saved } : prev));
      }
      return saved;
    },
    [authFetch]
  );

  const openLoginModal = useCallback((notice?: string) => {
    setAuthError(notice ?? "");
    setAuthStep("phone");
    setOtpInput("");
    setDemoOtpHint(null);
    setAuthModalOpen(true);
  }, []);

  const performLogoutNow = useCallback(async () => {
    const activeToken = getActiveToken();
    setLogoutBusy(true);
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(activeToken),
      });
    } catch {
      // proceed with client cleanup even if network fails
    } finally {
      clearClientAuth();
      setLogoutBusy(false);
      setLogoutModalOpen(false);
      if (pathname?.startsWith("/account")) {
        router.replace("/");
      }
    }
  }, [clearClientAuth, getActiveToken, pathname, router]);

  const requestLogout = useCallback(() => {
    setLogoutModalOpen(true);
  }, []);

  const handleRequestOtp = async (event?: React.FormEvent) => {
    event?.preventDefault();
    setAuthError("");
    setAuthBusy(true);
    try {
      const res = await fetch("/api/v1/auth/request-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number: phoneInput.trim() }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorMessage(payload, "ارسال کد تأیید انجام نشد."));
      setNormalizedPhone(String(payload.phone_number ?? phoneInput.trim()));
      setDemoOtpHint(typeof payload.demo_code === "string" ? payload.demo_code : null);
      setResendCooldown(Number(payload.resend_after_seconds ?? 60));
      setAuthStep("otp");
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "خطا در ارسال کد پیامکی");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleVerifyOtp = async (event: React.FormEvent) => {
    event.preventDefault();
    setAuthError("");
    setAuthBusy(true);
    try {
      const res = await fetch("/api/v1/auth/verify-otp", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone_number: normalizedPhone || phoneInput.trim(),
          code: otpInput.trim(),
          full_name: fullNameInput.trim() || null,
        }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorMessage(payload, "تأیید کد ناموفق بود."));
      const nextToken = typeof payload.token === "string" ? payload.token : null;
      const loggedUser = (payload.user ?? null) as StudentUser | null;
      setAuthSession(nextToken, loggedUser);
      setAuthModalOpen(false);
      setOtpInput("");
      setDemoOtpHint(null);
      setAuthError("");
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "کد تأیید نادرست است");
    } finally {
      setAuthBusy(false);
    }
  };

  const lang = preferences.general.language === "en" ? "en" : "fa";
  const copy = COPY[lang];

  const contextValue = useMemo<AppContextValue>(
    () => ({
      user,
      token,
      authReady,
      preferences,
      systemIsDark,
      getActiveToken,
      setAuthSession,
      setUser: updateUserSynced,
      refreshAccount,
      authFetch,
      updatePreferences,
      resetPreferences,
      openLoginModal,
      requestLogout,
      performLogoutNow,
    }),
    [
      user,
      token,
      authReady,
      preferences,
      systemIsDark,
      getActiveToken,
      setAuthSession,
      updateUserSynced,
      refreshAccount,
      authFetch,
      updatePreferences,
      resetPreferences,
      openLoginModal,
      requestLogout,
      performLogoutNow,
    ]
  );

  return (
    <AppContext.Provider value={contextValue}>
      {children}

      {/* Global SMS OTP Login Modal */}
      {authModalOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) setAuthModalOpen(false);
          }}
        >
          <section
            className="exam-setup-modal otp-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="global-otp-modal-title"
          >
            <button
              className="modal-close icon-button"
              onClick={() => setAuthModalOpen(false)}
              aria-label="بستن"
            >
              <X size={18} />
            </button>
            <div className="modal-icon">
              <Phone size={22} />
            </div>
            <span className="eyebrow">
              {lang === "en" ? "SMS Verification" : "احراز هویت پیامکی"}
            </span>
            <h2 id="global-otp-modal-title">
              {authStep === "phone"
                ? lang === "en"
                  ? "Sign in with mobile"
                  : "ورود یا ثبت‌نام با موبایل"
                : lang === "en"
                ? "Verify SMS code"
                : "تأیید کد پیامکی"}
            </h2>
            {authStep === "phone" ? (
              <form onSubmit={handleRequestOtp}>
                <p>
                  {lang === "en"
                    ? "Enter your Iranian mobile number to receive a 6-digit verification code."
                    : "شماره موبایل خودت را وارد کن تا کد ۶ رقمی ورود برایت پیامک شود. کاربران تازه هدیهٔ شروع دریافت می‌کنند."}
                </p>
                <label className="form-field">
                  <span>{lang === "en" ? "Mobile Number" : "شماره موبایل (ایران)"}</span>
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
                  <span>
                    {lang === "en"
                      ? "Full Name (optional for new accounts)"
                      : "نام و نام خانوادگی (اختیاری — برای ثبت‌نام تازه)"}
                  </span>
                  <input
                    type="text"
                    value={fullNameInput}
                    onChange={(event) => setFullNameInput(event.target.value)}
                    placeholder={lang === "en" ? "e.g. Ali Rezaei" : "مثلاً علی رضایی"}
                  />
                </label>
                {authError && <div className="inline-error">{authError}</div>}
                <button className="primary-button modal-submit" type="submit" disabled={authBusy}>
                  {authBusy ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
                  {lang === "en" ? "Send verification code" : "ارسال کد تأیید پیامکی"}
                </button>
              </form>
            ) : (
              <form onSubmit={handleVerifyOtp}>
                <p>
                  {lang === "en" ? (
                    <>
                      Enter the 6-digit code sent to <b dir="ltr">{normalizedPhone}</b>.
                    </>
                  ) : (
                    <>
                      کد ۶ رقمی ارسال‌شده به شمارهٔ <b dir="ltr">{normalizedPhone}</b> را وارد کن.
                    </>
                  )}
                </p>
                {demoOtpHint && (
                  <div className="demo-otp-box">
                    <div>
                      <b>{lang === "en" ? "Demo Mode" : "حالت آزمایشی"}</b>
                      <span>
                        {lang === "en" ? "Code: " : "کد تأیید شما: "}
                        <strong dir="ltr">{demoOtpHint}</strong>
                      </span>
                    </div>
                    <button
                      type="button"
                      className="outline-button"
                      onClick={() => setOtpInput(demoOtpHint)}
                    >
                      {lang === "en" ? "Auto-fill" : "درج خودکار کد"}
                    </button>
                  </div>
                )}
                <label className="form-field">
                  <span>{lang === "en" ? "6-digit code" : "کد تأیید ۶ رقمی"}</span>
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
                  {lang === "en" ? "Verify & Sign In" : "تأیید و ورود به کلاس"}
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
                    {lang === "en" ? "Change number" : "تغییر شماره موبایل"}
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    disabled={resendCooldown > 0 || authBusy}
                    onClick={() => void handleRequestOtp()}
                  >
                    {resendCooldown > 0
                      ? lang === "en"
                        ? `Resend (${resendCooldown}s)`
                        : `ارسال مجدد (${resendCooldown} ثانیه)`
                      : lang === "en"
                      ? "Resend code"
                      : "ارسال مجدد کد"}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}

      {/* Global Log Out Confirmation Dialog */}
      {logoutModalOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (!logoutBusy && event.target === event.currentTarget) setLogoutModalOpen(false);
          }}
        >
          <section
            className="exam-setup-modal logout-confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="logout-dialog-title"
          >
            <button
              className="modal-close icon-button"
              onClick={() => setLogoutModalOpen(false)}
              disabled={logoutBusy}
              aria-label={copy.auth.logoutConfirmNo}
            >
              <X size={18} />
            </button>
            <div className="modal-icon danger-icon">
              <LogOut size={22} />
            </div>
            <h2 id="logout-dialog-title">{copy.auth.logoutConfirmTitle}</h2>
            <p>{copy.auth.logoutConfirmBody}</p>
            <div className="dialog-actions-row">
              <button
                type="button"
                className="outline-button"
                disabled={logoutBusy}
                onClick={() => setLogoutModalOpen(false)}
              >
                {copy.auth.logoutConfirmNo}
              </button>
              <button
                type="button"
                className="danger-button"
                disabled={logoutBusy}
                onClick={() => void performLogoutNow()}
              >
                {logoutBusy ? (
                  <>
                    <LoaderCircle className="spin" size={16} />
                    {copy.auth.loggingOut}
                  </>
                ) : (
                  <>
                    <LogOut size={16} />
                    {copy.auth.logoutConfirmYes}
                  </>
                )}
              </button>
            </div>
          </section>
        </div>
      )}
    </AppContext.Provider>
  );
}
