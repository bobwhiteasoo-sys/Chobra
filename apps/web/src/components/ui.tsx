"use client";

import { AlertTriangle, Check, CircleAlert, CircleCheck, Copy, Info, Loader2, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { createContext, useCallback, useContext, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

import { ApiError, errorMessage } from "@/lib/api";
import { CHECK_STATUS, RUN_STATUS, VERDICT } from "@/lib/format";

type Tone = "neutral" | "accent" | "success" | "danger" | "info";

export function Button({ variant = "secondary", compact, busy, children, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; compact?: boolean; busy?: boolean }) {
  return (
    <button className={`btn btn-${variant}${compact ? " btn-compact" : ""} ${className}`} disabled={busy || rest.disabled} aria-busy={busy || undefined} {...rest}>
      {busy ? <Loader2 size={16} className="spin" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function ButtonLink({ href, variant = "secondary", compact, children }: { href: string; variant?: "primary" | "secondary" | "ghost"; compact?: boolean; children: ReactNode }) {
  return (
    <Link href={href} className={`btn btn-${variant}${compact ? " btn-compact" : ""}`}>
      {children}
    </Link>
  );
}

const TONE_ICON: Record<Tone, ReactNode> = {
  neutral: null,
  accent: null,
  success: <CircleCheck size={14} aria-hidden />,
  danger: <OctagonAlert size={14} aria-hidden />,
  info: <Info size={14} aria-hidden />,
};

export function Pill({ tone = "neutral", icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={`pill pill-${tone}`}>
      {icon ?? TONE_ICON[tone]}
      {children}
    </span>
  );
}

export function RunStatus({ status }: { status: string }) {
  const info = RUN_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <Pill tone={info.tone}>{info.label}</Pill>;
}

export function Verdict({ verdict }: { verdict: string | null | undefined }) {
  if (!verdict) return <Pill>Аудит не завершен</Pill>;
  const info = VERDICT[verdict] ?? { label: verdict, tone: "neutral" as const };
  return <Pill tone={info.tone}>{info.label}</Pill>;
}

export function CheckStatus({ status }: { status: string }) {
  const info = CHECK_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <Pill tone={info.tone}>{info.label}</Pill>;
}

export function Notice({ tone = "info", title, children }: { tone?: "info" | "warn" | "danger"; title?: string; children: ReactNode }) {
  const icon = tone === "danger" ? <OctagonAlert size={18} color="#FF637D" aria-hidden /> : tone === "warn" ? <AlertTriangle size={18} color="#FFD447" aria-hidden /> : <Info size={18} color="#71C8FF" aria-hidden />;
  return (
    <div className={`notice notice-${tone}`} role={tone === "danger" ? "alert" : "note"}>
      {icon}
      <div>
        {title ? <strong style={{ display: "block", marginBottom: 2 }}>{title}</strong> : null}
        <div className="t-secondary">{children}</div>
      </div>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const requestId = error instanceof ApiError ? error.requestId : "";
  const status = error instanceof ApiError ? error.status : 0;
  const title = status === 404 ? "Объект не найден или недоступен" : status === 403 ? "Недостаточно прав" : "Не удалось загрузить данные";
  return (
    <div className="empty" role="alert">
      {status === 404 ? (
        <img src="/brand/chobra-404.webp" width={220} height={112} alt="" style={{ height: "auto" }} />
      ) : (
        <CircleAlert size={22} color="#FF637D" aria-hidden />
      )}
      <div>
        <div className="t-panel">{title}</div>
        <p className="t-secondary" style={{ margin: "4px 0 0" }}>
          {errorMessage(error)}
        </p>
        {requestId ? <p className="t-caption">Идентификатор обращения: {requestId}</p> : null}
      </div>
      {onRetry ? (
        <Button compact onClick={onRetry}>
          Повторить
        </Button>
      ) : null}
    </div>
  );
}

export function Loading({ lines = 3 }: { lines?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Загрузка">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ height: i === 0 ? 32 : 18, width: i === 0 ? "40%" : `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="t-panel">{title}</div>
      {children ? <div className="t-secondary measure">{children}</div> : null}
      {action}
    </div>
  );
}

export function IdChip({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="id-chip"
      title={value}
      onClick={() => {
        void navigator.clipboard?.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
      aria-label={`Скопировать ${label ?? "идентификатор"} ${value}`}
    >
      {label ? `${label} ` : ""}
      {value.length > 12 ? `${value.slice(0, 8)}…` : value}
      {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
    </button>
  );
}

export function Metric({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="metric">
      <span className="label">{label}</span>
      <span className="t-value">{value}</span>
      {note ? <span className="note">{note}</span> : null}
    </div>
  );
}

/* ---------- toasts ---------- */
type ToastItem = { id: number; title: string; body?: string; tone?: "info" | "danger" | "success" };
const ToastContext = createContext<(toast: Omit<ToastItem, "id">) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((toast: Omit<ToastItem, "id">) => {
    const id = Date.now() + Math.random();
    setItems((current) => [...current.slice(-3), { ...toast, id }]);
    window.setTimeout(() => setItems((current) => current.filter((t) => t.id !== id)), 6000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-region" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="toast">
            <strong style={{ color: t.tone === "danger" ? "#FFB3C0" : t.tone === "success" ? "#8FE6C0" : undefined }}>{t.title}</strong>
            {t.body ? <div className="t-caption" style={{ marginTop: 2 }}>{t.body}</div> : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
