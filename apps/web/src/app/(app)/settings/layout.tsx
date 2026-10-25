"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import "@/styles/settings.css";

const links = [
  { href: "/settings/profile", label: "Профиль" },
  { href: "/settings/workspace", label: "Пространство" },
  { href: "/settings/members", label: "Участники" },
  { href: "/settings/models", label: "Модели и ключи" },
];

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="settings-layout">
      <nav className="settings-tabs" aria-label="Разделы настроек">
        {links.map((link) => (
          <Link key={link.href} href={link.href} aria-current={pathname === link.href ? "page" : undefined}>
            {link.label}
          </Link>
        ))}
      </nav>
      <div className="stack-24">{children}</div>
    </div>
  );
}
