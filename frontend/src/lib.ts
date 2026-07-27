export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let message = "عملیات انجام نشد.";
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep the safe fallback.
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const toman = (value: number) => `${new Intl.NumberFormat("fa-IR").format(value)} تومان`;

export function bytes(value: number, unlimited = false): string {
  if (!value && unlimited) return "نامحدود";
  if (value < 1024 ** 2) return `${Math.max(0, value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(value >= 10 * 1024 ** 3 ? 1 : 2)} GB`;
}

export function date(value: string | null): string {
  if (!value) return "نامحدود";
  return new Intl.DateTimeFormat("fa-IR", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Tehran",
  }).format(new Date(value));
}

export function relativeDays(value: string | null): string {
  if (!value) return "بدون محدودیت زمانی";
  const days = Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return "منقضی شده";
  if (days === 0) return "کمتر از یک روز";
  return `${new Intl.NumberFormat("fa-IR").format(days)} روز باقی‌مانده`;
}

export const statusLabel = (status: string) =>
  ({
    active: "فعال",
    on_hold: "در انتظار شروع",
    disabled: "غیرفعال",
    expired: "منقضی",
    limited: "اتمام حجم",
    deleted: "حذف‌شده",
  })[status] || status;

