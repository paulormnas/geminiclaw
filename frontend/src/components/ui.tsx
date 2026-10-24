import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import styles from "./ui.module.css";

type Variant = "default" | "primary" | "signal" | "ghost" | "danger";

export function Button({
  variant = "default",
  loading = false,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  const cls = [styles["btn"], variant !== "default" ? styles[variant] : ""].join(" ");
  return (
    <button {...rest} className={cls} disabled={disabled || loading} aria-busy={loading || undefined}>
      {loading ? <span className={styles["spinner"]} aria-hidden="true" /> : null}
      {children}
    </button>
  );
}

export function TextField({
  label,
  error,
  hint,
  multiline = false,
  ...rest
}: {
  label: string;
  error?: string | null;
  hint?: string;
  multiline?: boolean;
} & Record<string, unknown>) {
  const id = useId();
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
  const common = {
    id,
    className: styles["input"],
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy,
    ...rest,
  };
  return (
    <div className={styles["field"]}>
      <label className={styles["label"]} htmlFor={id}>
        {label}
      </label>
      {multiline ? <textarea {...common} /> : <input {...common} />}
      {error ? (
        <span className={styles["error"]} id={`${id}-err`} role="alert">
          {error}
        </span>
      ) : hint ? (
        <span className={styles["hint"]} id={`${id}-hint`}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

const BADGES: Record<string, { label: string; tone: string }> = {
  ativo: { label: "Ativo", tone: "pos" },
  pausado: { label: "Pausado", tone: "warn" },
  concluido: { label: "Concluído", tone: "info" },
  arquivado: { label: "Arquivado", tone: "neu" },
};

export function StatusBadge({ status }: { status: string }) {
  const entry = BADGES[status] ?? { label: status, tone: "neu" };
  return <span className={`${styles["badge"]} ${styles[entry.tone]}`}>{entry.label}</span>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={styles["state"]}>
      <h2>{title}</h2>
      {children}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className={styles["state"]} role="alert">
      <h2>Algo deu errado</h2>
      <span className={styles["error"]}>{message}</span>
      {onRetry ? <Button onClick={onRetry}>Tentar de novo</Button> : null}
    </div>
  );
}

export function Spinner({ label = "Carregando…" }: { label?: string }) {
  return (
    <span role="status" style={{ display: "inline-flex", gap: 8, alignItems: "center", color: "var(--text-muted)" }}>
      <span className={styles["spinner"]} aria-hidden="true" />
      {label}
    </span>
  );
}

export function Dialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, textarea, button, [tabindex]")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className={styles["backdrop"]} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={styles["dialog"]} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export const dialogActions = styles["actions"];
