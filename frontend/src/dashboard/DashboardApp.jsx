import { Fragment, useCallback, useEffect, useState } from 'react';

const ADMIN_BASE = new URL('./', window.location.href.replace(/\/+$/, ''));
const THEME_KEY = 'mitsu_theme';
const PAGE_LIMIT = 10;
const MODES = ['all', 'manual', 'backfill', 'auto'];

function readStored(key) {
  try {
    return localStorage.getItem(key) || '';
  } catch {
    return '';
  }
}

function initialTheme() {
  const saved = readStored(THEME_KEY);
  return saved === 'light' ? 'light' : 'dark';
}

function api(path, method = 'GET', payload = null) {
  const options = {
    method,
    cache: 'no-store',
    credentials: 'same-origin',
    headers: {},
  };
  if (payload !== null) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(payload);
  }
  return fetch(new URL(path, ADMIN_BASE), options).then(
    async (res) => {
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = body.detail;
        const message =
          typeof detail === 'string'
            ? detail
            : detail?.message || `HTTP ${res.status}`;
        const error = new Error(message);
        error.status = res.status;
        error.retry = res.headers.get('Retry-After');
        throw error;
      }
      return body;
    },
  );
}

function pad(value) {
  return String(value).padStart(2, '0');
}

function duration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return '–';
  const total = Math.max(0, Math.floor(Number(seconds)));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${pad(minutes)}m`;
  return `${minutes}m ${pad(secs)}s`;
}

function fmtShort(value) {
  if (!value) return '–';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '–';
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtDateShort(value) {
  if (!value) return '–';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '–';
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function fmtTime(value) {
  if (!value) return '–';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '–';
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function fmtUtcStamp(value) {
  if (!value) return '–';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '–';
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}Z`
  );
}

function percentLabel(value) {
  const pct = Number(value) || 0;
  return Number.isInteger(pct) ? `${pct}%` : `${pct.toFixed(1)}%`;
}

function toneForPercent(value) {
  const pct = Number(value) || 0;
  if (pct >= 100) return 'coral';
  if (pct >= 70) return 'amber';
  return 'sage';
}

function toneForStatus(status) {
  if (status === 'success') return 'sage';
  if (status === 'failed') return 'coral';
  if (status === 'running' || status === 'partial' || status === 'rejected' || status === 'skipped') {
    return 'amber';
  }
  return 'slate';
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M20.8 14.2A8.5 8.5 0 0 1 9.8 3.2 8.6 8.6 0 1 0 20.8 14.2Z" strokeLinejoin="round" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <circle cx="12" cy="12" r="3.6" />
      <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" strokeLinecap="round" />
    </svg>
  );
}

function RefreshIcon({ spinning }) {
  return (
    <svg
      className={spinning ? 'spin' : undefined}
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      aria-hidden="true"
    >
      <path d="M20 11.2A8.1 8.1 0 0 0 4.7 8.4M4 4v5h5M4 12.8a8.1 8.1 0 0 0 15.3 2.8M20 20v-5h-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SectionHead({ title, note }) {
  return (
    <div className="section-head">
      <h2 className="section-title">{title}</h2>
      <p className="section-note">{note}</p>
    </div>
  );
}

function Pill({ tone = 'slate', children }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

function QuotaCard({ name, description, budget }) {
  const used = budget?.used ?? 0;
  const limit = budget?.limit ?? 0;
  const pct = budget?.percent ?? 0;
  const tone = toneForPercent(pct);
  return (
    <article className="panel quota-panel">
      <div className="panel-top">
        <h3>{name}</h3>
        <Pill tone={tone}>{percentLabel(pct)} used</Pill>
      </div>
      <p className="desc">{description}</p>
      <div className="hero-metric">
        <strong>{used}</strong>
        <span>/ {limit} requests</span>
      </div>
      <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin="0" aria-valuemax="100">
        <span className={`progress-fill ${tone}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </div>
      <div className="panel-foot">
        <span>{budget?.remaining ?? 0} left</span>
        <span>resets in {duration(budget?.seconds_to_reset)}</span>
      </div>
    </article>
  );
}

function GuardrailsCard({ guardrails, anilist }) {
  const runs = guardrails?.runs_today ?? 0;
  const limit = guardrails?.daily_run_limit ?? 0;
  const atLimit = limit > 0 && runs >= limit;
  return (
    <article className="panel quota-panel guardrails-panel">
      <div className="panel-top">
        <h3>Guardrails</h3>
        <Pill tone={atLimit ? 'amber' : 'sage'}>{atLimit ? 'limit' : 'ok'}</Pill>
      </div>
      <p className="desc">Run cap and manual cooldown, checked before any provider request.</p>
      <dl className="kv-grid">
        <div>
          <dt>Runs today</dt>
          <dd>{runs} / {limit}</dd>
        </div>
        <div>
          <dt>Cooldown</dt>
          <dd>{duration(guardrails?.cooldown_seconds)}</dd>
        </div>
        <div>
          <dt>Next manual</dt>
          <dd>{guardrails?.next_manual_at ? fmtShort(guardrails.next_manual_at) : 'now'}</dd>
        </div>
        <div>
          <dt>AniList left</dt>
          <dd>{anilist?.remaining ?? 0} / {anilist?.limit ?? 0}</dd>
        </div>
      </dl>
      <div className="divider" />
      <div className="panel-foot">
        <span>Budget day</span>
        <span>in {duration(guardrails?.seconds_to_reset)}</span>
      </div>
    </article>
  );
}

function ActionField({ id, value, max, disabled, onChange }) {
  const suffix = max > 0 ? `≤ ${max}` : 'none';
  return (
    <div className="action-field">
      <label htmlFor={id}>Pages</label>
      <input
        id={id}
        className="page-input"
        type="number"
        min={max > 0 ? 1 : 0}
        max={Math.max(1, max)}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      <span className="suffix">{suffix}</span>
    </div>
  );
}

function BackfillPanel({ backfill }) {
  const pct = Number(backfill?.percent) || 0;
  const complete = !!backfill?.complete;
  const method = complete
    ? 'Complete'
    : backfill?.progress_basis === 'pages'
      ? 'Page-based'
      : 'Time-based estimate';
  const remaining = complete
    ? 'nothing left after the cutoff'
    : backfill?.remaining_pages != null
      ? `${backfill.remaining_pages} pages left`
      : backfill?.remaining_days != null
        ? `~${backfill.remaining_days} days left (time-based estimate)`
        : '–';
  return (
    <article className="panel backfill-panel">
      <div className="backfill-top">
        <div>
          <span className="micro-label">Complete</span>
          <div className="backfill-value">
            <strong>{percentLabel(pct)}</strong>
            <Pill tone="slate">{method}</Pill>
          </div>
        </div>
        <Pill tone={complete ? 'sage' : 'amber'}>{complete ? 'complete' : 'in progress'}</Pill>
      </div>
      <div className="progress progress-tall" role="progressbar" aria-valuenow={pct} aria-valuemin="0" aria-valuemax="100">
        <span
          className="progress-fill sage"
          style={{ width: `${Math.min(100, Math.max(0, pct))}%`, minWidth: pct > 0 ? 6 : 0 }}
        />
      </div>
      <div className="panel-foot">
        <span>{fmtDateShort(backfill?.cutoff_at)} → {fmtDateShort(new Date())}</span>
        <span>{remaining}</span>
      </div>
      <div className="divider" />
      <dl className="meta-grid">
        <div>
          <dt>Cutoff</dt>
          <dd>{fmtUtcStamp(backfill?.cutoff_at)}</dd>
          {backfill?.last_attempt_at && <small>attempted {fmtShort(backfill.last_attempt_at)}</small>}
        </div>
        <div>
          <dt>Oldest processed</dt>
          <dd>{fmtShort(backfill?.progress_at)}</dd>
        </div>
        <div>
          <dt>Next page</dt>
          <dd>{complete ? 'done' : backfill?.next_page ?? '–'}</dd>
        </div>
        <div>
          <dt>Pages done</dt>
          <dd>{backfill?.pages_done ?? 0}{backfill?.total_pages ? ` / ${backfill.total_pages}` : ' done'}</dd>
        </div>
        <div>
          <dt>Last success</dt>
          <dd>{fmtShort(backfill?.last_success_at)}</dd>
        </div>
        <div>
          <dt>Reserve / limit</dt>
          <dd>{backfill?.reserve ?? '–'} reserved / {backfill?.limit ?? '–'} max</dd>
        </div>
      </dl>
      {backfill?.last_error && <p className="inline-error">Last error: {backfill.last_error}</p>}
    </article>
  );
}

function pageList(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  const pages = new Set([1, total, current - 1, current, current + 1]);
  const sorted = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
  const out = [];
  sorted.forEach((page, index) => {
    if (index > 0 && page - sorted[index - 1] > 1) out.push('…');
    out.push(page);
  });
  return out;
}

function Pagination({ page, totalPages, onPage, disabled }) {
  if (totalPages <= 1) return null;
  return (
    <nav className="pager" aria-label="Run history pagination">
      <button
        type="button"
        className="btn ghost pager-step"
        onClick={() => onPage(page - 1)}
        disabled={disabled || page === 0}
      >
        Previous
      </button>
      <div className="pager-numbers">
        {pageList(page + 1, totalPages).map((item, index) =>
          item === '…' ? (
            <span key={`gap-${index}`} className="pager-gap">…</span>
          ) : (
            <button
              key={item}
              type="button"
              className={`pager-number ${item === page + 1 ? 'is-current' : ''}`}
              aria-current={item === page + 1 ? 'page' : undefined}
              onClick={() => onPage(item - 1)}
              disabled={disabled}
            >
              {item}
            </button>
          ),
        )}
      </div>
      <button
        type="button"
        className="btn ghost pager-step"
        onClick={() => onPage(page + 1)}
        disabled={disabled || page >= totalPages - 1}
      >
        Next
      </button>
    </nav>
  );
}

function LoginScreen({ theme, onTheme, onLogin, busy, error, loginEnabled }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const submit = (event) => {
    event.preventDefault();
    onLogin(username, password);
  };
  return (
    <main className="auth-page">
      <div className="auth-top">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">M</div>
          <span className="brand-tag">MITSU</span>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={onTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        >
          {theme === 'dark' ? '☀' : '☾'}
        </button>
      </div>
      <section className="auth-card" aria-labelledby="login-title">
        <p className="eyebrow">Catalog control</p>
        <h1 id="login-title">Sign in</h1>
        <p className="auth-lead">Use the admin account configured on this server.</p>
        {!loginEnabled && (
          <div className="auth-note">
            Password login is not configured. Set
            <code>SYNC_ADMIN_USERNAME</code> and <code>SYNC_ADMIN_PASSWORD</code> in
            <code>.env</code>, then restart the API.
          </div>
        )}
        <form onSubmit={submit}>
          <label className="field">
            <span>Username</span>
            <input
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              disabled={!loginEnabled || busy}
              required
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={!loginEnabled || busy}
              required
            />
          </label>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button
            type="submit"
            className="btn primary auth-submit"
            disabled={!loginEnabled || busy}
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="auth-foot">Internal admin page · UTC budgets</p>
      </section>
    </main>
  );
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    const area = document.createElement('textarea');
    area.value = value;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    let copied = false;
    try {
      copied = document.execCommand('copy');
    } catch {
      copied = false;
    }
    area.remove();
    return copied;
  }
}

function runDetailsText(run) {
  return [
    `Run ${run.run_id}`,
    `Mode: ${run.mode}${run.dry_run ? ' (dry run)' : ''}`,
    `Status: ${run.status}`,
    `Started: ${run.started_at || '—'}`,
    `Finished: ${run.finished_at || '—'}`,
    `Pages fetched: ${run.pages_fetched ?? 0}`,
    `Requests attempted: ${run.details?.backfill?.requests_attempted ?? '—'}`,
    `Rows seen: ${run.rows_seen ?? 0}`,
    `Inserted: ${run.rows_inserted ?? 0}`,
    `Updated: ${run.rows_updated ?? 0}`,
    `Details: ${JSON.stringify(run.details || {}, null, 2)}`,
    '',
    'Error:',
    run.error || '—',
  ].join('\n');
}

function RunsTable({ runs, total, page, totalPages, filter, onFilter, onPage, notify, loading }) {
  const [expanded, setExpanded] = useState(null);
  const [copied, setCopied] = useState(null);
  const filtered = filter === 'all' ? runs : runs.filter((run) => run.mode === filter);
  const totalRuns = Number(total) || 0;
  const start = totalRuns ? page * PAGE_LIMIT + 1 : 0;
  const end = page * PAGE_LIMIT + filtered.length;
  const filterNote = filter === 'all' ? '' : ` · ${filtered.length} ${filter} on this page`;
  const countLabel = totalRuns
    ? `showing ${start}–${end} of ${totalRuns}${filterNote} · page ${page + 1} of ${totalPages}`
    : 'no runs yet';
  const copyRun = async (run) => {
    const ok = await copyText(runDetailsText(run));
    if (ok) {
      setCopied(run.run_id);
      notify('Run details copied');
      setTimeout(() => setCopied((value) => (value === run.run_id ? null : value)), 1800);
    } else {
      notify('Could not copy run details', true);
    }
  };
  return (
    <section className="section">
      <SectionHead title="Recent runs" note={countLabel} />
      <div className="runs-toolbar">
        <p className="desc">
          Each row is one attempt. Pages counts successful provider pages; a retried request
          spends daily budget without adding a page. Open a row for details and a multiline copy.
        </p>
        <div className="filters" role="group" aria-label="Filter runs by mode">
          {MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              className={`filter ${filter === mode ? 'is-active' : ''}`}
              onClick={() => onFilter(mode)}
            >
              {mode === 'all' ? 'All' : mode.charAt(0).toUpperCase() + mode.slice(1)}
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        <table className="runs-table">
          <thead>
            <tr>
              <th>Started</th>
              <th>Mode</th>
              <th>Status</th>
              <th className="num">Pages</th>
              <th className="num">Seen</th>
              <th className="num">New</th>
              <th className="num">Updated</th>
              <th className="num">Error</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan="8" className="empty-row">No runs match this filter on this page.</td>
              </tr>
            ) : (
              filtered.map((run) => (
                <Fragment key={run.run_id}>
                  <tr className={expanded === run.run_id ? 'is-expanded' : undefined}>
                    <td className="mono start-cell">
                      <button
                        type="button"
                        className="row-toggle"
                        aria-expanded={expanded === run.run_id}
                        aria-controls={`run-${run.run_id}`}
                        onClick={() =>
                          setExpanded((value) => (value === run.run_id ? null : run.run_id))
                        }
                        title="Show run details"
                      >
                        {expanded === run.run_id ? '▾' : '▸'}
                      </button>
                      {fmtShort(run.started_at)}
                    </td>
                    <td className="mono">
                      {run.mode}
                      {run.dry_run && <span className="pill slate dry">dry</span>}
                    </td>
                    <td>
                      <span className={`run-status ${toneForStatus(run.status)}`}>
                        <span className="dot" />
                        {run.status}
                      </span>
                    </td>
                    <td
                      className="num mono"
                      title="Successful provider pages. Retried requests spend budget but do not add a page."
                    >
                      {Number(run.pages_fetched || 0).toLocaleString('en-US')}
                    </td>
                    <td className="num mono">{Number(run.rows_seen || 0).toLocaleString('en-US')}</td>
                    <td className="num mono">{Number(run.rows_inserted || 0).toLocaleString('en-US')}</td>
                    <td className="num mono">{Number(run.rows_updated || 0).toLocaleString('en-US')}</td>
                    <td className="num error-cell" title={run.error || undefined}>
                      {run.error || '—'}
                    </td>
                  </tr>
                  {expanded === run.run_id && (
                    <tr className="run-detail-row" id={`run-${run.run_id}`}>
                      <td colSpan="8">
                        <div className="run-detail">
                          <div className="run-detail-head">
                            <span className="mono">run {run.run_id}</span>
                            <button
                              type="button"
                              className="mini-btn"
                              onClick={() => copyRun(run)}
                            >
                              {copied === run.run_id ? 'Copied' : 'Copy details'}
                            </button>
                          </div>
                          <pre>{runDetailsText(run)}</pre>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>
      <Pagination page={page} totalPages={totalPages} onPage={onPage} disabled={loading} />
    </section>
  );
}

export default function DashboardApp() {
  const [theme, setTheme] = useState(initialTheme);
  const [auth, setAuth] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState(null);
  const [data, setData] = useState(null);
  const [runs, setRuns] = useState([]);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [spinning, setSpinning] = useState(false);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [filter, setFilter] = useState('all');
  const [manualPages, setManualPages] = useState(1);
  const [backfillPages, setBackfillPages] = useState(5);

  const manualMax = Math.max(0, Number(data?.limits?.manual_pages) || 0);
  const backfillMax = Math.max(0, Number(data?.limits?.backfill_pages) || 0);
  const anilist = data?.budgets?.anilist;
  const mangadex = data?.budgets?.mangadex;
  const guardrails = data?.guardrails;
  const backfill = data?.backfill;
  const autoEnabled = !!data?.auto_enabled;
  const complete = !!backfill?.complete;
  const totalRuns = Number(data?.runs_total) || 0;
  const totalPages = Math.max(1, Math.ceil(totalRuns / PAGE_LIMIT));
  const activeRun = runs.some((run) => run.status === 'running');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Local storage may be unavailable; the theme still applies for this load.
    }
  }, [theme]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    setManualPages((value) => (manualMax > 0 ? Math.min(Math.max(1, value || 1), manualMax) : 0));
  }, [manualMax]);

  useEffect(() => {
    setBackfillPages((value) => (backfillMax > 0 ? Math.min(Math.max(1, value || 1), backfillMax) : 0));
  }, [backfillMax]);

  const loadPage = useCallback(async (index = 0, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const body = await api(`sync/status?limit=${PAGE_LIMIT}&offset=${index * PAGE_LIMIT}`);
      const lastPage = Math.max(0, Math.ceil((Number(body.runs_total) || 0) / PAGE_LIMIT) - 1);
      if (index > lastPage) {
        return loadPage(lastPage, silent);
      }
      setData(body);
      setRuns(body.runs || []);
      setPage(index);
      setError(null);
      setUpdatedAt(new Date());
    } catch (err) {
      if (err.status === 401) {
        setAuth((current) => ({
          ...(current || {}),
          authenticated: false,
          auth_required: true,
        }));
        setLoginError('Your session expired. Sign in again.');
      }
      setError({ status: err.status, message: err.message, retry: err.retry });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api('session')
      .then((session) => {
        if (cancelled) return;
        setAuth(session);
        setAuthLoading(false);
        if (session.authenticated || !session.auth_required) {
          loadPage(0);
        } else {
          setLoading(false);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setAuth({ authenticated: false, auth_required: true, login_enabled: true });
        setAuthLoading(false);
        setLoading(false);
        setLoginError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [loadPage]);

  const notify = (message, bad = false) => setToast({ message, bad });

  const refresh = () => {
    setSpinning(true);
    loadPage(page).finally(() => setTimeout(() => setSpinning(false), 600));
  };

  const handleLogin = async (username, password) => {
    setLoginBusy(true);
    setLoginError(null);
    try {
      const session = await api('login', 'POST', { username, password });
      setAuth(session);
      await loadPage(0);
    } catch (err) {
      setLoginError(err.message);
    } finally {
      setLoginBusy(false);
    }
  };

  const logout = async () => {
    try {
      await api('logout', 'POST');
    } catch {
      // The cookie may already be gone; clear the UI either way.
    }
    setAuth({
      authenticated: false,
      auth_required: true,
      login_enabled: auth?.login_enabled !== false,
    });
    setData(null);
    setRuns([]);
    setPage(0);
    setError(null);
    setLoginError(null);
    setLoading(false);
  };

  const trigger = async (kind) => {
    setBusy(kind);
    const label = kind === 'backfill' ? 'Backfill' : 'Manual sync';
    try {
      const path =
        kind === 'backfill'
          ? `backfill?max_pages=${backfillPages}`
          : `sync?mode=manual&max_pages=${manualPages}`;
      const body = await api(path, 'POST');
      notify(`${label} queued · ${String(body.run_id || '').slice(0, 8) || 'accepted'}`);
      setFilter('all');
      setTimeout(() => loadPage(0, true), 1000);
      setTimeout(() => loadPage(0, true), 6000);
    } catch (err) {
      const wait = err.retry ? ` Retry in ${duration(Number(err.retry))}.` : '';
      notify(`${label} rejected: ${err.message}${wait}`, true);
      if (err.status === 401) {
        setAuth((current) => ({
          ...(current || {}),
          authenticated: false,
          auth_required: true,
        }));
      }
      if (err.status === 429) setTimeout(() => loadPage(page, true), 800);
    } finally {
      setBusy(null);
    }
  };

  const toggleAuto = async (next) => {
    try {
      const body = await api(`auto?enabled=${next}`, 'POST');
      setData((current) =>
        current
          ? { ...current, auto_enabled: body.enabled, auto_source: body.source }
          : current,
      );
      notify(`Scheduled auto sync ${next ? 'enabled' : 'disabled'}`);
    } catch (err) {
      notify(err.message, true);
      if (err.status === 401) {
        setAuth((current) => ({
          ...(current || {}),
          authenticated: false,
          auth_required: true,
        }));
      }
    }
  };

  const changePage = (index) => {
    const next = Math.max(0, Math.min(totalPages - 1, index));
    if (next !== page) loadPage(next);
  };

  useEffect(() => {
    if (!auth || (auth.auth_required && !auth.authenticated)) return undefined;
    const timer = setInterval(
      () => {
        if (!document.hidden) loadPage(page, true);
      },
      activeRun ? 5000 : 30000,
    );
    return () => clearInterval(timer);
  }, [auth, activeRun, page, loadPage]);

  if (authLoading) {
    return (
      <main className="auth-page">
        <section className="auth-card auth-loading">Checking session…</section>
      </main>
    );
  }

  if (auth?.auth_required && !auth.authenticated) {
    return (
      <LoginScreen
        theme={theme}
        onTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        onLogin={handleLogin}
        busy={loginBusy}
        error={loginError}
        loginEnabled={auth.login_enabled !== false}
      />
    );
  }

  const online = !!data && !error;
  const onlineLabel = !data && !error ? 'connecting' : online ? 'online' : 'offline';

  return (
    <main className="dash">
      <div className="shell">
        <header className="masthead">
          <div className="identity">
            <div className="brand-mark" aria-hidden="true">M</div>
            <div>
              <div className="title-row">
                <h1>Catalog control</h1>
                <span className="brand-tag">MITSU</span>
              </div>
              <p className="subtitle">
                AniList and MangaDex synchronization, budgets, and resumable backfill{' '}
                <span className="updated">{updatedAt ? `updated ${fmtTime(updatedAt)}` : 'updated –'}</span>
              </p>
            </div>
          </div>
          <div className="header-actions">
            {auth?.auth_required && (
              <div className="account-chip">
                <span className="account-name">{auth.username || 'admin'}</span>
                <button type="button" className="text-btn" onClick={logout}>
                  Log out
                </button>
              </div>
            )}
            <span className={`online ${online ? 'is-online' : !data && !error ? 'is-pending' : 'is-offline'}`}>
              <span className="dot" />
              {onlineLabel}
            </span>
            <button
              type="button"
              className="btn"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {theme === 'dark' ? <MoonIcon /> : <SunIcon />}
              <span>{theme === 'dark' ? 'Dark' : 'Light'}</span>
            </button>
            <button type="button" className="btn" onClick={refresh} disabled={loading}>
              <RefreshIcon spinning={spinning} />
              <span>Refresh</span>
            </button>
          </div>
        </header>

        {error && (
          <div className={`alert ${error.status === 401 ? 'is-warn' : 'is-bad'}`} role="alert">
            <strong>{error.status === 401 ? 'Session expired' : 'Status unavailable'}</strong>
            <span>{error.message}</span>
          </div>
        )}

        <section className="section">
          <SectionHead
            title="Today"
            note={<>Counters use the database UTC date; resets <span className="mono">{fmtUtcStamp(guardrails?.day_reset_at)}</span>.</>}
          />
          <div className="grid grid-3">
            <QuotaCard
              name="AniList"
              description="Daily request budget shared by sync and backfill pages."
              budget={anilist}
            />
            <QuotaCard
              name="MangaDex"
              description="Daily request budget for manga link matching."
              budget={mangadex}
            />
            <GuardrailsCard guardrails={guardrails} anilist={anilist} />
          </div>
        </section>

        <section className="section">
          <SectionHead
            title="Run a sync"
            note="One-off actions. The scheduled job is controlled separately."
          />
          <div className="grid grid-3">
            <article className="panel action-panel">
              <div className="panel-top">
                <h3>Manual sync</h3>
                <Pill tone={manualMax > 0 ? 'slate' : 'amber'}>
                  {manualMax > 0 ? `max ${manualMax}` : 'no requests'}
                </Pill>
              </div>
              <p className="desc">
                Fetches recent AniList changes and refreshes MangaDex links. Each page spends
                provider requests.
              </p>
              <div className="action-bottom">
                <ActionField
                  id="manual-pages"
                  value={manualPages}
                  max={manualMax}
                  disabled={manualMax <= 0 || !!busy}
                  onChange={(value) =>
                    setManualPages(Math.max(1, Math.min(manualMax, Number(value) || 1)))
                  }
                />
                <button
                  type="button"
                  className="btn action-btn"
                  onClick={() => trigger('manual')}
                  disabled={manualMax <= 0 || !!busy}
                >
                  {busy === 'manual' ? 'Queuing…' : manualMax > 0 ? 'Run manual sync' : 'No requests left'}
                </button>
              </div>
            </article>

            <article className="panel action-panel">
              <div className="panel-top">
                <h3>Backfill</h3>
                <Pill tone={backfillMax > 0 && !complete ? 'slate' : 'amber'}>
                  {complete ? 'complete' : backfillMax > 0 ? `max ${backfillMax}` : 'no requests'}
                </Pill>
              </div>
              <p className="desc">
                Walks AniList history toward the cutoff. Resumable, and keeps a reserve for the
                daily sync.
              </p>
              <div className="action-bottom">
                <ActionField
                  id="backfill-pages"
                  value={backfillPages}
                  max={backfillMax}
                  disabled={backfillMax <= 0 || complete || !!busy}
                  onChange={(value) =>
                    setBackfillPages(Math.max(1, Math.min(backfillMax, Number(value) || 1)))
                  }
                />
                <button
                  type="button"
                  className="btn action-btn"
                  onClick={() => trigger('backfill')}
                  disabled={backfillMax <= 0 || complete || !!busy}
                >
                  {busy === 'backfill'
                    ? 'Queuing…'
                    : complete
                      ? 'Backfill complete'
                      : backfillMax > 0
                        ? 'Advance backfill'
                        : 'Backfill paused'}
                </button>
              </div>
            </article>

            <article className="panel action-panel">
              <div className="panel-top">
                <h3>Scheduled sync</h3>
                <Pill tone={autoEnabled ? 'sage' : 'slate'}>{autoEnabled ? 'on' : 'off'}</Pill>
              </div>
              <p className="desc">
                Permits the external scheduler to run <code className="chip">mode=auto</code>. Off
                by default; manual actions still work.
              </p>
              <label className="switch-row">
                <input
                  type="checkbox"
                  className="switch-input"
                  checked={autoEnabled}
                  onChange={(event) => toggleAuto(event.target.checked)}
                  disabled={!data}
                />
                <span className="switch" aria-hidden="true"><span className="switch-knob" /></span>
                <span className="switch-label">Auto sync <span>{data?.auto_source || 'env'}</span></span>
              </label>
              <dl className="auto-meta">
                <div>
                  <dt>Run mode</dt>
                  <dd>auto</dd>
                </div>
                <div>
                  <dt>Trigger</dt>
                  <dd>scheduler</dd>
                </div>
              </dl>
              <div className="action-spacer" />
              <div className="divider" />
              <p className="footnote">Stored in the database. Use exactly one external scheduler.</p>
            </article>
          </div>
        </section>

        <section className="section">
          <SectionHead
            title="Backfill progress"
            note="From the UTC cutoff to now. The cursor only moves forward."
          />
          <BackfillPanel backfill={backfill} />
        </section>

        <RunsTable
          runs={runs}
          total={totalRuns}
          page={page}
          totalPages={totalPages}
          filter={filter}
          onFilter={setFilter}
          onPage={changePage}
          notify={notify}
          loading={loading}
        />

        <footer className="page-foot">
          <span>
            Budget day {guardrails?.day || '–'} · resets {fmtUtcStamp(guardrails?.day_reset_at)} ·
            backfill cutoff {fmtUtcStamp(backfill?.cutoff_at)}
          </span>
          <span>Internal admin page · UTC budgets</span>
        </footer>
      </div>

      {toast && (
        <div className={`toast ${toast.bad ? 'is-bad' : ''}`} role="status">
          {toast.message}
        </div>
      )}

      <span className="sr-only" aria-live="polite">
        {runs.length} runs visible
      </span>
    </main>
  );
}
