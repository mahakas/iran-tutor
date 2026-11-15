import type { Metadata } from "next";
import "katex/dist/katex.min.css";
import AppProvider from "@/components/AppProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "درسیار | معلم خصوصی هوشمند",
  description: "یادگیری دقیق و مستند بر اساس کتاب‌های درسی ایران",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl">
      <body>
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
