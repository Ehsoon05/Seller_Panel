import {
  Activity,
  ArrowLeft,
  Check,
  ChevronDown,
  Clipboard,
  Copy,
  Gauge,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Menu,
  PackagePlus,
  Pencil,
  Power,
  RefreshCw,
  RotateCcw,
  Search,
  Server,
  Trash2,
  Wallet,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { api, ApiError, bytes, date, relativeDays, statusLabel, toman } from "./lib";
import type { Dashboard, Ledger, Offer, RenewalQuote, Seller, Service } from "./types";

function Button({
  children,
  className = "",
  variant = "default",
  busy = false,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "secondary" | "danger" | "ghost";
  busy?: boolean;
}) {
  return (
    <button className={`button ${variant} ${className}`} disabled={busy || props.disabled} {...props}>
      {busy ? <LoaderCircle className="spin" size={17} /> : children}
    </button>
  );
}

function Toast({ message, tone, onClose }: { message: string; tone: "ok" | "error"; onClose: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, 3500);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return (
    <div className={`toast ${tone}`}>
      {tone === "ok" ? <Check size={18} /> : <X size={18} />}
      <span>{message}</span>
    </div>
  );
}

function Login({ onLogin }: { onLogin: (seller: Seller) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const seller = await api<Seller>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      onLogin(seller);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "ورود انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel">
        <div className="brand-mark">PH</div>
        <div>
          <p className="eyebrow">PHANTOM HUBS</p>
          <h1>پنل همکاری</h1>
          <p className="muted">مدیریت و ساخت سرویس‌های اختصاصی</p>
        </div>
        <form onSubmit={submit} className="form-stack">
          <label>
            نام کاربری
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
          </label>
          <label>
            رمز عبور
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          </label>
          {error && <p className="form-error">{error}</p>}
          <Button type="submit" busy={busy}>ورود به پنل <ArrowLeft size={18} /></Button>
        </form>
      </section>
    </main>
  );
}

function Shell({ seller, onLogout, onSellerRefresh }: { seller: Seller; onLogout: () => void; onSellerRefresh: () => Promise<void> }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setMenuOpen(false), [location.pathname]);
  const links = [
    { to: "/", label: "داشبورد", icon: LayoutDashboard, end: true },
    { to: "/services", label: "سرویس‌ها", icon: Server },
    { to: "/create", label: "ساخت سرویس", icon: PackagePlus },
    { to: "/ledger", label: "گردش حساب", icon: Wallet },
  ];
  return (
    <div className="app-shell">
      <header className="mobile-header">
        <button className="icon-button" onClick={() => setMenuOpen(!menuOpen)} aria-label="منو"><Menu /></button>
        <strong>Phantom Sellers</strong>
        <span className="header-balance">{toman(seller.wallet_balance)}</span>
      </header>
      <aside className={menuOpen ? "sidebar open" : "sidebar"}>
        <div className="sidebar-brand">
          <div className="brand-mark small">PH</div>
          <div><strong>Phantom Hubs</strong><span>Seller Panel</span></div>
        </div>
        <nav>
          {links.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => isActive ? "active" : ""}>
              <Icon size={19} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="seller-summary">
          <span className="avatar">{seller.display_name.slice(0, 1)}</span>
          <div><strong>{seller.display_name}</strong><small>@{seller.username}</small></div>
          <button className="icon-button" onClick={onLogout} aria-label="خروج"><LogOut size={18} /></button>
        </div>
      </aside>
      {menuOpen && <button className="scrim" onClick={() => setMenuOpen(false)} aria-label="بستن منو" />}
      <section className="workspace">
        <Routes>
          <Route index element={<DashboardPage />} />
          <Route path="services" element={<ServicesPage onSellerRefresh={onSellerRefresh} />} />
          <Route path="create" element={<CreatePage />} />
          <Route path="ledger" element={<LedgerPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </section>
    </div>
  );
}

function PageHead({ title, subtitle, action }: { title: string; subtitle: string; action?: React.ReactNode }) {
  return (
    <header className="page-head">
      <div><h1>{title}</h1><p>{subtitle}</p></div>
      {action}
    </header>
  );
}

function Stat({ label, value, icon: Icon, tone }: { label: string; value: string; icon: typeof Gauge; tone: string }) {
  return (
    <article className="stat">
      <span className={`stat-icon ${tone}`}><Icon size={20} /></span>
      <div><span>{label}</span><strong>{value}</strong></div>
    </article>
  );
}

function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [recent, setRecent] = useState<Service[]>([]);
  useEffect(() => {
    Promise.all([api<Dashboard>("/dashboard"), api<Service[]>("/services")]).then(([stats, rows]) => {
      setData(stats);
      setRecent(rows.slice(0, 5));
    });
  }, []);
  return (
    <>
      <PageHead title="داشبورد" subtitle="نمای کلی فعالیت پنل همکاری شما" />
      <div className="stats-grid">
        <Stat label="موجودی پنل" value={data ? toman(data.wallet_balance) : "..."} icon={Wallet} tone="blue" />
        <Stat label="سرویس‌های فعال" value={data ? data.active_services.toLocaleString("fa-IR") : "..."} icon={Activity} tone="green" />
        <Stat label="کل سرویس‌ها" value={data ? data.total_services.toLocaleString("fa-IR") : "..."} icon={Server} tone="violet" />
        <Stat label="خرید این ماه" value={data ? toman(data.monthly_spend) : "..."} icon={Gauge} tone="amber" />
      </div>
      <section className="section-block">
        <div className="section-title"><div><h2>آخرین سرویس‌ها</h2><p>آخرین موارد ساخته‌شده در پنل</p></div><NavLink to="/services">مشاهده همه <ArrowLeft size={16} /></NavLink></div>
        <ServiceTable services={recent} compact />
      </section>
    </>
  );
}

function Usage({ service }: { service: Service }) {
  const percent = service.data_limit_bytes
    ? Math.min(100, Math.round((service.used_bytes / service.data_limit_bytes) * 100))
    : 0;
  return (
    <div className="usage">
      <div><span>{bytes(service.used_bytes)}</span><small>{service.data_limit_bytes ? `از ${bytes(service.data_limit_bytes)}` : "حجم نامحدود"}</small></div>
      <div className="progress"><i style={{ width: `${percent}%` }} /></div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status ${status}`}>{statusLabel(status)}</span>;
}

function ServiceTable({
  services,
  compact = false,
  onRefresh,
  onToggle,
  onEdit,
  onRenew,
  onDelete,
  busyId,
  notify,
}: {
  services: Service[];
  compact?: boolean;
  onRefresh?: (service: Service) => void;
  onToggle?: (service: Service) => void;
  onEdit?: (service: Service) => void;
  onRenew?: (service: Service) => void;
  onDelete?: (service: Service) => void;
  busyId?: number | null;
  notify?: (message: string) => void;
}) {
  const copy = async (value: string) => {
    await navigator.clipboard.writeText(value);
    notify?.("لینک اشتراک کپی شد.");
  };
  if (!services.length) return <div className="empty"><Server size={30} /><strong>هنوز سرویسی وجود ندارد</strong><span>از بخش ساخت سرویس، اولین مورد را ایجاد کنید.</span></div>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>نام سرویس</th><th>وضعیت</th><th>مصرف</th><th>زمان</th>{!compact && <th>عملیات</th>}</tr></thead>
        <tbody>
          {services.map((service) => (
            <tr key={service.id}>
              <td data-label="نام سرویس">
                <div className="service-name"><span className="server-icon"><Server size={18} /></span><div><strong>{service.panel_username}</strong><small>{service.panel_key}</small></div></div>
                <details className="mobile-service-details">
                  <summary>جزئیات بیشتر <ChevronDown size={14} /></summary>
                  <div><span>وضعیت</span><StatusBadge status={service.status} /></div>
                  <div><span>مصرف</span><Usage service={service} /></div>
                  <div><span>زمان</span><div className="time-cell"><strong>{relativeDays(service.expires_at)}</strong><small>{service.expires_at ? date(service.expires_at) : "نامحدود"}</small></div></div>
                </details>
              </td>
              <td data-label="وضعیت"><StatusBadge status={service.status} /></td>
              <td data-label="مصرف"><Usage service={service} /></td>
              <td data-label="زمان"><div className="time-cell"><strong>{relativeDays(service.expires_at)}</strong><small>{service.expires_at ? date(service.expires_at) : "نامحدود"}</small></div></td>
              {!compact && (
                <td data-label="عملیات">
                  <div className="row-actions">
                    <button className="icon-button has-tooltip" onClick={() => copy(service.public_url)} aria-label="کپی لینک" data-tooltip="کپی لینک"><Copy size={17} /></button>
                    <button className="icon-button has-tooltip" onClick={() => onRefresh?.(service)} disabled={busyId === service.id} aria-label="به‌روزرسانی" data-tooltip="به‌روزرسانی">
                      <RefreshCw size={17} className={busyId === service.id ? "spin" : ""} />
                    </button>
                    <button className={`icon-button has-tooltip ${service.status === "disabled" ? "enable" : "disable"}`} onClick={() => onToggle?.(service)} disabled={busyId === service.id} aria-label={service.status === "disabled" ? "فعال‌کردن" : "غیرفعال‌کردن"} data-tooltip={service.status === "disabled" ? "فعال‌کردن" : "غیرفعال‌کردن"}><Power size={17} /></button>
                    <button className="icon-button has-tooltip renew-icon" onClick={() => onRenew?.(service)} disabled={busyId === service.id} aria-label="تمدید" data-tooltip="تمدید"><RotateCcw size={17} /></button>
                    <button className="icon-button has-tooltip" onClick={() => onEdit?.(service)} disabled={busyId === service.id} aria-label="ویرایش" data-tooltip="ویرایش"><Pencil size={17} /></button>
                    <button className="icon-button has-tooltip danger-icon" onClick={() => onDelete?.(service)} disabled={busyId === service.id} aria-label="حذف کامل" data-tooltip="حذف کامل"><Trash2 size={17} /></button>
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ServicesPage({ onSellerRefresh }: { onSellerRefresh: () => Promise<void> }) {
  const [services, setServices] = useState<Service[]>([]);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Service | null>(null);
  const [renewing, setRenewing] = useState<Service | null>(null);
  const [renewQuote, setRenewQuote] = useState<RenewalQuote | null>(null);
  const [editForm, setEditForm] = useState({ volume_gb: 0, duration_days: 30, time_mode: "date" });
  const [toast, setToast] = useState<{ message: string; tone: "ok" | "error" } | null>(null);
  const load = useCallback(async () => {
    const suffix = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
    setServices(await api<Service[]>(`/services${suffix}`));
  }, [query]);
  useEffect(() => { void api<Offer[]>("/offers").then(setOffers); }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 250); return () => window.clearTimeout(timer); }, [load]);
  async function action(service: Service, type: "refresh" | "toggle") {
    setBusyId(service.id);
    try {
      const updated = type === "refresh"
        ? await api<Service>(`/services/${service.id}/refresh`, { method: "POST" })
        : await api<Service>(`/services/${service.id}/status?enabled=${service.status === "disabled"}`, { method: "POST" });
      setServices((items) => items.map((item) => item.id === updated.id ? updated : item));
      setToast({ message: type === "refresh" ? "اطلاعات سرویس به‌روز شد." : "وضعیت سرویس تغییر کرد.", tone: "ok" });
    } catch (reason) {
      setToast({ message: reason instanceof Error ? reason.message : "عملیات انجام نشد.", tone: "error" });
    } finally {
      setBusyId(null);
    }
  }
  function openEdit(service: Service) {
    setEditing(service);
    setEditForm({
      volume_gb: service.volume_gb,
      duration_days: service.duration_days || 30,
      time_mode: service.time_mode,
    });
  }
  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const volumeDifference = editForm.volume_gb - editing.volume_gb;
    const priceDifference = editingOffer?.pricing_mode === "per_gb"
      ? volumeDifference * editingOffer.price_per_gb_toman
      : 0;
    if (priceDifference !== 0) {
      const message = priceDifference > 0
        ? `برای افزایش حجم، ${toman(priceDifference)} از موجودی شما کسر می‌شود. ادامه می‌دهید؟`
        : `با کاهش حجم، ${toman(Math.abs(priceDifference))} به موجودی شما برمی‌گردد. ادامه می‌دهید؟`;
      if (!window.confirm(message)) return;
    }
    setBusyId(editing.id);
    try {
      const updated = await api<Service>(`/services/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...editForm,
          duration_days: editForm.time_mode === "unlimited" ? 0 : editForm.duration_days,
        }),
      });
      setServices((items) => items.map((item) => item.id === updated.id ? updated : item));
      await onSellerRefresh();
      setEditing(null);
      setToast({ message: "مشخصات یوزر روی پنل سازنده ویرایش شد.", tone: "ok" });
    } catch (reason) {
      setToast({ message: reason instanceof Error ? reason.message : "ویرایش انجام نشد.", tone: "error" });
    } finally {
      setBusyId(null);
    }
  }
  async function openRenew(service: Service) {
    setBusyId(service.id);
    try {
      const quote = await api<RenewalQuote>(`/services/${service.id}/renewal-quote`);
      setRenewing(service);
      setRenewQuote(quote);
    } catch (reason) {
      setToast({ message: reason instanceof Error ? reason.message : "اطلاعات تمدید دریافت نشد.", tone: "error" });
    } finally {
      setBusyId(null);
    }
  }
  async function confirmRenew() {
    if (!renewing || !renewQuote) return;
    setBusyId(renewing.id);
    try {
      const updated = await api<Service>(`/services/${renewing.id}/renew`, {
        method: "POST",
        body: JSON.stringify({ request_id: crypto.randomUUID() }),
      });
      setServices((items) => items.map((item) => item.id === updated.id ? updated : item));
      await onSellerRefresh();
      setRenewing(null);
      setRenewQuote(null);
      setToast({ message: "سرویس با موفقیت تمدید شد؛ حجم و تاریخ از نو محاسبه شدند.", tone: "ok" });
    } catch (reason) {
      setToast({ message: reason instanceof Error ? reason.message : "تمدید انجام نشد.", tone: "error" });
    } finally {
      setBusyId(null);
    }
  }
  async function remove(service: Service) {
    if (!window.confirm(`یوزر «${service.panel_username}» از پنل سازنده و پنل ساب کاملاً حذف شود؟ این عملیات قابل بازگشت نیست.`)) return;
    setBusyId(service.id);
    try {
      await api(`/services/${service.id}`, { method: "DELETE" });
      setServices((items) => items.filter((item) => item.id !== service.id));
      setToast({ message: "یوزر از پنل سازنده و پنل ساب حذف شد.", tone: "ok" });
    } catch (reason) {
      setToast({ message: reason instanceof Error ? reason.message : "حذف انجام نشد.", tone: "error" });
    } finally {
      setBusyId(null);
    }
  }
  const editingOffer = editing ? offers.find((item) => item.id === editing.offer_id) : null;
  return (
    <>
      <PageHead title="سرویس‌ها" subtitle="جست‌وجو، بررسی مصرف و مدیریت سرویس‌های ساخته‌شده" action={<NavLink className="button default" to="/create"><PackagePlus size={18} /> ساخت سرویس</NavLink>} />
      <div className="toolbar">
        <label className="search"><Search size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="جست‌وجو با نام، یوزرنیم یا لینک..." /></label>
        <span>{services.length.toLocaleString("fa-IR")} سرویس</span>
      </div>
      <ServiceTable services={services} onRefresh={(value) => action(value, "refresh")} onToggle={(value) => action(value, "toggle")} onEdit={openEdit} onRenew={(value) => void openRenew(value)} onDelete={(value) => void remove(value)} busyId={busyId} notify={(message) => setToast({ message, tone: "ok" })} />
      {editing && (
        <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setEditing(null)}>
          <form className="edit-modal" onSubmit={saveEdit}>
            <div className="modal-head">
              <div><h2>ویرایش یوزر</h2><p>{editing.panel_username}</p></div>
              <button type="button" className="icon-button" onClick={() => setEditing(null)} aria-label="بستن"><X size={18} /></button>
            </div>
            <div className="form-grid">
              {editingOffer?.lock_volume ? <div className="locked-value"><strong>حجم خریداری‌شده</strong><span>{editForm.volume_gb ? `${editForm.volume_gb.toLocaleString("fa-IR")} GB` : "نامحدود"}</span></div> : <label>حجم (GB، صفر نامحدود)<input type="number" min={editingOffer?.pricing_mode === "per_gb" ? 1 : 0} max="100000" value={editForm.volume_gb} onChange={(event) => setEditForm({ ...editForm, volume_gb: Number(event.target.value) })} /></label>}
              {editingOffer?.lock_time_mode ? <div className="locked-value"><strong>نوع تاریخ ثابت</strong><span>{editForm.time_mode === "unlimited" ? "بدون محدودیت زمانی" : editForm.time_mode === "on_hold" ? "شروع با اولین اتصال - On Hold" : "تاریخ‌دار - Active"}</span></div> : <label>نوع تاریخ
                <select value={editForm.time_mode} onChange={(event) => setEditForm({ ...editForm, time_mode: event.target.value })}>
                  {(editingOffer?.allowed_time_modes || ["date", "on_hold", "unlimited"]).map((item) => (
                    <option key={item} value={item}>{item === "date" ? "تاریخ‌دار - Active" : item === "on_hold" ? "شروع با اولین اتصال - On Hold" : "بدون محدودیت زمانی - Active"}</option>
                  ))}
                </select>
              </label>}
              {editForm.time_mode !== "unlimited" && (editingOffer?.lock_duration
                ? <div className="locked-value"><strong>مدت ثابت</strong><span>{editingOffer.default_duration_days.toLocaleString("fa-IR")} روز</span></div>
                : <label className="wide">مدت از اکنون (روز)<input type="number" min="1" max="3650" value={editForm.duration_days} onChange={(event) => setEditForm({ ...editForm, duration_days: Number(event.target.value) })} /></label>)}
            </div>
            {editingOffer?.pricing_mode === "per_gb" && editForm.volume_gb !== editing.volume_gb && (
              <div className={`price-adjustment ${editForm.volume_gb > editing.volume_gb ? "charge" : "refund"}`}>
                <span>{editForm.volume_gb > editing.volume_gb ? "مبلغ قابل کسر" : "مبلغ قابل بازگشت"}</span>
                <strong>{toman(Math.abs(editForm.volume_gb - editing.volume_gb) * editingOffer.price_per_gb_toman)}</strong>
              </div>
            )}
            {editingOffer?.pricing_mode === "per_gb" && (
              <p className="volume-rule">
                حجم جدید نباید از مصرف فعلی کمتر باشد. اکنون {bytes(editing.used_bytes)} مصرف شده و حداکثر {bytes(editing.remaining_bytes)} قابل کاهش است.
              </p>
            )}
            <p className="edit-warning">ثبت ویرایش، حجم و تاریخ یوزر را روی پنل سازنده با همین مقادیر به‌روزرسانی می‌کند.</p>
            <div className="modal-actions">
              <Button type="button" variant="ghost" onClick={() => setEditing(null)}>انصراف</Button>
              <Button type="submit" busy={busyId === editing.id}><Pencil size={17} /> ذخیره تغییرات</Button>
            </div>
          </form>
        </div>
      )}
      {renewing && renewQuote && (
        <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setRenewing(null)}>
          <section className="edit-modal renewal-modal">
            <div className="modal-head">
              <div><h2>تأیید تمدید سرویس</h2><p>{renewing.panel_username}</p></div>
              <button type="button" className="icon-button" onClick={() => setRenewing(null)} aria-label="بستن"><X size={18} /></button>
            </div>
            <div className="renewal-summary">
              <div><span>حجم پس از تمدید</span><strong>{renewQuote.volume_gb ? `${renewQuote.volume_gb.toLocaleString("fa-IR")} GB` : "نامحدود"}</strong></div>
              <div><span>مدت جدید</span><strong>{renewQuote.duration_days ? `${renewQuote.duration_days.toLocaleString("fa-IR")} روز` : "نامحدود"}</strong></div>
              <div><span>هزینه تمدید</span><strong>{toman(renewQuote.price_toman)}</strong></div>
              <div><span>موجودی فعلی</span><strong>{toman(renewQuote.wallet_balance)}</strong></div>
            </div>
            <p className="edit-warning">با تأیید، مصرف حجم صفر می‌شود و تاریخ سرویس از ابتدا محاسبه خواهد شد.</p>
            {!renewQuote.can_afford && <p className="form-error">موجودی شما برای تمدید این سرویس کافی نیست.</p>}
            <div className="modal-actions">
              <Button type="button" variant="ghost" onClick={() => setRenewing(null)}>انصراف</Button>
              <Button type="button" busy={busyId === renewing.id} disabled={!renewQuote.can_afford} onClick={() => void confirmRenew()}><RotateCcw size={17} /> تأیید و پرداخت</Button>
            </div>
          </section>
        </div>
      )}
      {toast && <Toast {...toast} onClose={() => setToast(null)} />}
    </>
  );
}

function CreatePage() {
  const [offers, setOffers] = useState<Offer[]>([]);
  const [offerId, setOfferId] = useState<number | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [volume, setVolume] = useState(20);
  const [duration, setDuration] = useState(30);
  const [mode, setMode] = useState("date");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<Offer[]>("/offers").then((rows) => { setOffers(rows); if (rows[0]) setOfferId(rows[0].id); }); }, []);
  const offer = useMemo(() => offers.find((item) => item.id === offerId), [offers, offerId]);
  useEffect(() => {
    if (!offer) return;
    setVolume(offer.volume_gb);
    setDuration(offer.default_duration_days);
    setMode(offer.default_time_mode);
  }, [offer]);
  const finalPrice = useMemo(() => {
    if (!offer) return 0;
    return offer.pricing_mode === "per_gb"
      ? offer.price_per_gb_toman * volume
      : offer.price_toman;
  }, [offer, volume]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!offer) return;
    setBusy(true);
    setError("");
    try {
      await api<Service>("/services", {
        method: "POST",
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          offer_id: offer.id,
          panel_username: displayName.trim(),
          display_name: null,
          volume_gb: volume,
          duration_days: mode === "unlimited" ? 0 : duration,
          time_mode: mode,
        }),
      });
      window.location.assign("/services");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "ساخت سرویس انجام نشد.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHead title="ساخت سرویس" subtitle="پلن موردنظر را انتخاب و سرویس را مستقیم از پنل ایجاد کنید" />
      <form className="create-layout" onSubmit={submit}>
        <section className="form-panel">
          <div className="step-head"><span>۱</span><div><h2>انتخاب سرویس</h2><p>قیمت و ویژگی‌ها مخصوص حساب شماست.</p></div></div>
          <div className="offer-grid">
            {offers.map((item) => (
              <button type="button" key={item.id} className={offerId === item.id ? "offer selected" : "offer"} onClick={() => setOfferId(item.id)}>
                <div><strong>{item.title}</strong><span>{item.volume_gb ? `${item.volume_gb} GB` : "حجم نامحدود"}</span></div>
                <b>{item.pricing_mode === "per_gb" ? `${toman(item.price_per_gb_toman)} / گیگ` : toman(item.price_toman)}</b>
                <i>{offerId === item.id && <Check size={15} />}</i>
              </button>
            ))}
          </div>
          {!offers.length && <div className="empty"><PackagePlus size={30} /><strong>سرویسی برای شما تعریف نشده</strong><span>با مدیریت تماس بگیرید.</span></div>}
          {offer && (
            <>
              <div className="step-head"><span>۲</span><div><h2>مشخصات ساخت</h2><p>یوزرنیم مستقیماً داخل پنل سازنده ثبت می‌شود و باید یکتا باشد.</p></div></div>
              <div className="form-grid">
                <label className="wide">یوزرنیم کانفیگ<input dir="ltr" required minLength={3} maxLength={120} pattern="[A-Za-z0-9_-]+" value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
                {offer.lock_volume
                  ? <div className="locked-value"><strong>حجم ثابت</strong><span>{volume ? `${volume.toLocaleString("fa-IR")} GB` : "نامحدود"}</span></div>
                  : <label>حجم سرویس (GB)<input type="number" min={offer.pricing_mode === "per_gb" ? 1 : 0} max="100000" value={volume} onChange={(event) => setVolume(Number(event.target.value))} /></label>}
                {offer.lock_time_mode ? <div className="locked-value"><strong>نوع تاریخ ثابت</strong><span>{mode === "unlimited" ? "بدون محدودیت زمانی" : mode === "on_hold" ? "شروع با اولین اتصال - On Hold" : "تاریخ‌دار - Active"}</span></div> : <label>نوع تاریخ<select value={mode} onChange={(event) => setMode(event.target.value)}>{offer.allowed_time_modes.map((item) => <option key={item} value={item}>{item === "date" ? "تاریخ‌دار - Active" : item === "on_hold" ? "شروع با اولین اتصال - On Hold" : "بدون محدودیت زمانی - Active"}</option>)}</select></label>}
                {mode !== "unlimited" && (offer.lock_duration ? <div className="locked-value"><strong>مدت ثابت</strong><span>{offer.default_duration_days.toLocaleString("fa-IR")} روز</span></div> : <label>مدت سرویس (روز)<input type="number" min="1" max="3650" value={duration} onChange={(event) => setDuration(Number(event.target.value))} /></label>)}
              </div>
              {(offer.lock_volume || offer.lock_time_mode || offer.lock_duration) && <p className="hint">مقادیر قفل‌شده توسط مدیریت قابل تغییر نیستند.</p>}
            </>
          )}
          {error && <p className="form-error">{error}</p>}
        </section>
        <aside className="order-summary">
          <h2>خلاصه سفارش</h2>
          <dl>
            <div><dt>سرویس</dt><dd>{offer?.title || "-"}</dd></div>
            <div><dt>حجم</dt><dd>{offer ? (volume ? `${volume} GB` : "نامحدود") : "-"}</dd></div>
            <div><dt>مدت</dt><dd>{mode === "unlimited" ? "نامحدود" : `${duration.toLocaleString("fa-IR")} روز`}</dd></div>
            <div><dt>محدودیت دستگاه</dt><dd>{offer?.subscription_device_limit ? `${offer.subscription_device_limit.toLocaleString("fa-IR")} دستگاه` : "نامحدود"}</dd></div>
          </dl>
          {offer?.pricing_mode === "per_gb" && <p className="hint">محاسبه: {volume.toLocaleString("fa-IR")} گیگ × {toman(offer.price_per_gb_toman)}</p>}
          <div className="total"><span>مبلغ قابل پرداخت</span><strong>{offer ? toman(finalPrice) : "-"}</strong></div>
          <Button type="submit" busy={busy} disabled={!offer}>ساخت و دریافت لینک <ArrowLeft size={18} /></Button>
          <p className="hint">پس از ساخت موفق، مبلغ از موجودی پنل کسر می‌شود.</p>
        </aside>
      </form>
    </>
  );
}

function LedgerPage() {
  const [rows, setRows] = useState<Ledger[]>([]);
  useEffect(() => { api<Ledger[]>("/ledger").then(setRows); }, []);
  return (
    <>
      <PageHead title="گردش حساب" subtitle="ریز افزایش موجودی، خریدها و بازگشت وجه" />
      <div className="table-wrap">
        <table>
          <thead><tr><th>شرح</th><th>نوع</th><th>مبلغ</th><th>موجودی پس از تراکنش</th><th>تاریخ</th></tr></thead>
          <tbody>
            {rows.map((row) => <tr key={row.id}><td data-label="شرح"><strong>{row.description}</strong></td><td data-label="نوع"><span className={`ledger-kind ${row.amount >= 0 ? "positive" : "negative"}`}>{row.kind === "purchase" ? "خرید" : row.kind === "renewal" ? "تمدید" : row.kind === "volume_adjustment" ? "تغییر حجم" : row.kind === "refund" ? "بازگشت وجه" : row.amount >= 0 ? "افزایش" : "کاهش"}</span></td><td data-label="مبلغ" className={row.amount >= 0 ? "money positive" : "money negative"}>{row.amount >= 0 ? "+" : ""}{toman(row.amount)}</td><td data-label="موجودی">{toman(row.balance_after)}</td><td data-label="تاریخ"><small>{date(row.created_at)}</small></td></tr>)}
          </tbody>
        </table>
        {!rows.length && <div className="empty"><Clipboard size={30} /><strong>گردش حساب خالی است</strong></div>}
      </div>
    </>
  );
}

export function App() {
  const [seller, setSeller] = useState<Seller | null | undefined>(undefined);
  useEffect(() => {
    api<Seller>("/me").then(setSeller).catch((reason) => {
      if (reason instanceof ApiError && reason.status === 401) setSeller(null);
      else setSeller(null);
    });
  }, []);
  async function logout() {
    await api("/auth/logout", { method: "POST" });
    setSeller(null);
  }
  async function refreshSeller() {
    setSeller(await api<Seller>("/me"));
  }
  if (seller === undefined) return <div className="boot"><LoaderCircle className="spin" /><span>در حال آماده‌سازی پنل...</span></div>;
  if (!seller) return <Login onLogin={setSeller} />;
  return <Shell seller={seller} onLogout={logout} onSellerRefresh={refreshSeller} />;
}
