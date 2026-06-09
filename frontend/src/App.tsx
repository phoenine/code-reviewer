import { useEffect, useState } from 'react';
import { fetchFilterOptions, fetchMembers, fetchReviews, fetchSummary } from './api/dashboard';
import type { DashboardSummary, FilterOptions, MemberItem, MembersResponse, ReviewItem, ReviewListResponse, ReviewType } from './types/dashboard';

type TimePeriod = 'week' | 'two_weeks' | 'month' | 'custom';

function periodToTimestamps(period: TimePeriod): { start?: number; end?: number } {
  if (period === 'custom') return {};
  const now = Math.floor(Date.now() / 1000);
  return { start: now - periodDays(period) * 86400, end: now };
}

function periodDays(period: TimePeriod): number {
  return period === 'week' ? 7 : period === 'two_weeks' ? 14 : period === 'month' ? 30 : 0;
}

function periodLabel(period: TimePeriod): string {
  return period === 'week' ? 'Last Week' : period === 'two_weeks' ? 'Last 2 Weeks' : period === 'month' ? 'Last Month' : 'All';
}

function compareNote(period: TimePeriod): string {
  return period === 'week' ? 'vs Last Week' : period === 'two_weeks' ? 'vs Prev 2 Weeks' : 'vs Last Month';
}

function trendArrow(delta: number): string {
  return delta > 0 ? '↑' : delta < 0 ? '↓' : '—';
}

function trendColor(delta: number): string {
  return delta > 0 ? '#22C55E' : delta < 0 ? '#EF4444' : '#5A7A9A';
}

function formatTrend(delta: number, isPct: boolean): string {
  const arrow = trendArrow(delta);
  const val = isPct ? `${Math.abs(delta)}%` : Math.abs(delta).toFixed(1);
  return delta === 0 ? '—' : `${arrow} ${val}`;
}

type Page = 'dashboard' | 'reviews' | 'members';
type LoadState<T> = { data: T | null; loading: boolean; error: string | null };

const emptySummary: DashboardSummary = { total_reviews: 0, average_score: 0, active_projects: 0, active_members: 0, project_counts: [], project_scores: [], recent_reviews: [], previous: null };
const emptyReviews: ReviewListResponse = { items: [], page: 1, page_size: 10, total: 0 };
const emptyMembers: MembersResponse = { items: [], summary: { total_reviews: 0, team_average_score: 0, total_additions: 0, total_deletions: 0, active_members: 0 } };

const scoreColor = (score: number) => (score >= 85 ? '#22C55E' : score >= 70 ? '#F59E0B' : '#EF4444');
const scoreStatus = (score: number) => (score >= 90 ? 'Excellent' : score >= 80 ? 'Passed' : score >= 70 ? 'Needs Improvement' : 'Failed');
const statusBg = (score: number) => (score >= 80 ? '#0D2D25' : score >= 70 ? '#2D250D' : '#2D0D0D');

function formatTime(value: number): string {
  if (!value) return '-';
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }).replace(/\//g, '-');
}

function App() {
  const [page, setPage] = useState<Page>('dashboard');
  return <div className="app-shell"><Sidebar page={page} setPage={setPage} /><main className="main">{page === 'dashboard' && <DashboardPage onNavigate={setPage} />}{page === 'reviews' && <ReviewsPage />}{page === 'members' && <MembersPage />}</main></div>;
}

function Sidebar({ page, setPage }: { page: Page; setPage: (page: Page) => void }) {
  const items: Array<[Page, string, string]> = [['dashboard', '▣', 'Dashboard'], ['reviews', '◇', 'Reviews'], ['members', '◈', 'Members']];
  return <aside className="sidebar"><div className="brand"><div className="brand-icon">▣</div><div><div className="brand-title">Code Reviewer</div><div className="brand-subtitle">AI Code Review</div></div></div><nav className="nav">{items.map(([key, icon, label]) => <button key={key} className={`nav-button ${page === key ? 'active' : ''}`} onClick={() => setPage(key)}><span className="nav-icon">{icon}</span><span>{label}</span>{page === key && <span className="nav-dot">●</span>}</button>)}</nav><div className="sidebar-footer"><div>v2.1.0</div><div>AI Code Review Platform</div></div></aside>;
}

function Header({ current, right }: { current: string; right?: React.ReactNode }) {
  return <div className="top-header"><div className="breadcrumb"><span>Home</span><span>/</span><strong>{current}</strong></div>{right}</div>;
}

function TimeSegments({ active, onChange }: { active: TimePeriod; onChange: (p: TimePeriod) => void }) {
  const items: TimePeriod[] = ['week', 'two_weeks', 'month', 'custom'];
  return <div className="time-segments">{items.map((p) => <button key={p} className={p === active ? 'active' : ''} onClick={() => onChange(p)}>{periodLabel(p)}</button>)}</div>;
}

function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ data: null, loading: true, error: null });
  useEffect(() => {
    let alive = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    loader().then((data) => alive && setState({ data, loading: false, error: null })).catch((error: Error) => alive && setState({ data: null, loading: false, error: error.message }));
    return () => { alive = false; };
  }, deps);
  return state;
}

function DashboardPage({ onNavigate }: { onNavigate: (page: Page) => void }) {
  const [period, setPeriod] = useState<TimePeriod>('week');
  const timestamps = periodToTimestamps(period);
  const { data, loading, error } = useAsync(() => fetchSummary(timestamps.start, timestamps.end), [period]);
  const summary = data ?? emptySummary;
  const maxCount = Math.max(1, ...summary.project_counts.map((item) => item.count));
  const maxScore = Math.max(100, ...summary.project_scores.map((item) => item.average_score));
  const badge = periodLabel(period);
  const prev = summary.previous;
  const note = period === 'custom' ? '' : compareNote(period);
  const kpis: Array<{ label: string; icon: string; iconColor: string; value: number | string; delta: number; deltaIsPct: boolean }> = [
    { label: 'Total Reviews', icon: '▣', iconColor: '#3B82F6', value: loading ? '...' : summary.total_reviews, delta: prev?.deltas.total_reviews_pct ?? 0, deltaIsPct: true },
    { label: 'Avg Score', icon: '⬡', iconColor: '#F59E0B', value: loading ? '...' : summary.average_score, delta: prev?.deltas.average_score_diff ?? 0, deltaIsPct: false },
    { label: 'Active Projects', icon: '◆', iconColor: '#8B5CF6', value: loading ? '...' : summary.active_projects, delta: prev?.deltas.active_projects_diff ?? 0, deltaIsPct: false },
    { label: 'Active Members', icon: '◈', iconColor: '#22C55E', value: loading ? '...' : summary.active_members, delta: prev?.deltas.active_members_diff ?? 0, deltaIsPct: false },
  ];
  return <><Header current="Dashboard" right={<TimeSegments active={period} onChange={setPeriod} />} />{error && <div className="error">{error}</div>}<div className="kpi-row">{kpis.map((kpi) => <KpiCard key={kpi.label} label={kpi.label} icon={kpi.icon} iconColor={kpi.iconColor} value={kpi.value} trend={prev ? formatTrend(kpi.delta, kpi.deltaIsPct) : ''} trendColor={prev ? trendColor(kpi.delta) : '#5A7A9A'} note={prev ? note : ''} />)}</div><div className="chart-row-2"><ChartCard title="Reviews by Project" dot="#3B82F6" badge={badge}>{summary.project_counts.length === 0 ? <Empty text="No project review data" /> : summary.project_counts.slice(0, 5).map((item) => <BarRow key={item.project_name} label={item.project_name} value={item.count} max={maxCount} color="#3B82F6" />)}</ChartCard><ChartCard title="Avg Score by Project" dot="#F59E0B" badge={badge}>{summary.project_scores.length === 0 ? <Empty text="No project score data" /> : summary.project_scores.slice(0, 5).map((item) => <BarRow key={item.project_name} label={item.project_name} value={item.average_score} max={maxScore} color={scoreColor(item.average_score)} />)}</ChartCard></div><RecentReviewsTable items={summary.recent_reviews} onViewAll={() => onNavigate('reviews')} /></>;
}

function KpiCard({ label, icon, iconColor, value, trend, note, trendColor }: { label: string; icon: string; iconColor: string; value: string | number; trend: string; note: string; trendColor: string }) {
  return <section className="card kpi-card"><div className="kpi-top"><span>{label}</span><span style={{ color: iconColor }}>{icon}</span></div><div className="card-divider" /><div className="kpi-value">{value}</div>{trend && <div className="kpi-trend"><span style={{ color: trendColor }}>{trend}</span>{note && <span>{note}</span>}</div>}</section>;
}

function ChartCard({ title, dot, badge, children }: { title: string; dot: string; badge: string; children: React.ReactNode }) {
  return <section className="card chart-card"><div className="card-title-row"><div><span style={{ color: dot }}>●</span><span>{title}</span></div><span className="title-badge">{badge}</span></div><div className="card-divider" /><div className="chart-list">{children}</div></section>;
}

function BarRow({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  return <div className="bar-row"><div title={label}>{label}</div><div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, (value / max) * 100)}%`, background: color }} /></div><strong>{value}</strong></div>;
}

function RecentReviewsTable({ items, onViewAll }: { items: ReviewItem[]; onViewAll: () => void }) {
  return <section className="card recent-card"><div className="card-title-row"><div><span style={{ color: '#8B5CF6' }}>●</span><span>Recent Reviews</span></div><button className="view-all" onClick={onViewAll}>View All →</button></div><div className="card-divider" />{items.length === 0 ? <Empty text="No recent reviews" /> : <div className="mini-table"><div className="mini-head"><span>Date</span><span>Project</span><span>Branch</span><span>Commit</span><span>Author</span><span>Score</span><span>Status</span></div>{items.slice(0, 5).map((item, index) => <div className="mini-row" key={`${item.type}-${item.project_name}-${item.updated_at}-${index}`}><div>{formatTime(item.updated_at)}</div><div title={item.project_name}>{item.project_name}</div><div title={item.branch || ''}>{item.branch || '-'}</div><div title={item.commit_messages}>{item.commit_messages || '-'}</div><div>{item.author}</div><span><ScoreBadge score={item.score} /></span><span><StatusPill score={item.score} /></span></div>)}</div>}</section>;
}

function ReviewsPage() {
  const [type, setType] = useState<ReviewType>('mr');
  const [author, setAuthor] = useState('');
  const [projectName, setProjectName] = useState('');
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [startDate, setStartDate] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 30);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const optionsState = useAsync<FilterOptions>(fetchFilterOptions, []);
  const reviewsState = useAsync(() => fetchReviews({
    type, author, project_name: projectName, keyword, page, page_size: pageSize,
    start: String(Math.floor(new Date(startDate + 'T00:00:00').getTime() / 1000)),
    end: String(Math.floor(new Date(endDate + 'T23:59:59').getTime() / 1000)),
  }), [type, author, projectName, keyword, page, pageSize, startDate, endDate]);
  const response = reviewsState.data ?? emptyReviews;
  const totalPages = Math.max(1, Math.ceil(response.total / response.page_size));
  const options = optionsState.data ?? { authors: [], project_names: [] };
  function resetFilters() {
    setAuthor(''); setProjectName(''); setKeyword(''); setPage(1);
    const d = new Date(); d.setDate(d.getDate() - 30);
    setStartDate(d.toISOString().slice(0, 10));
    setEndDate(new Date().toISOString().slice(0, 10));
  }
  return <><Header current="Reviews" />{(optionsState.error || reviewsState.error) && <div className="error">{optionsState.error || reviewsState.error}</div>}<section className="filter-card"><div className="filter-row"><input type="date" className="chip chip-date" value={startDate} onChange={(e) => { setStartDate(e.target.value); setPage(1); }} /><span className="to-text">to</span><input type="date" className="chip chip-date" value={endDate} onChange={(e) => { setEndDate(e.target.value); setPage(1); }} /><select className="chip-select" value={author} onChange={(e) => { setAuthor(e.target.value); setPage(1); }}><option value="">👤 Author</option>{options.authors.map((item) => <option key={item} value={item}>{item}</option>)}</select><select className="chip-select" value={projectName} onChange={(e) => { setProjectName(e.target.value); setPage(1); }}><option value="">📁 Project</option>{options.project_names.map((item) => <option key={item} value={item}>{item}</option>)}</select><input className="chip-search" value={keyword} onChange={(e) => { setKeyword(e.target.value); setPage(1); }} placeholder="⌕ Search..." /><button className="reset-btn" onClick={resetFilters}>Reset</button></div></section><div className="underline-tabs"><button className={type === 'mr' ? 'active' : ''} onClick={() => { setType('mr'); setPage(1); }}>Merge Request</button><button className={type === 'push' ? 'active' : ''} onClick={() => { setType('push'); setPage(1); }}>Push</button></div><ReviewTable type={type} items={response.items} loading={reviewsState.loading} /><Pagination page={page} totalPages={totalPages} pageSize={pageSize} setPage={setPage} onPageSizeChange={(s) => { setPageSize(s); setPage(1); }} /></>;
}

function ReviewTable({ type, items, loading }: { type: ReviewType; items: ReviewItem[]; loading: boolean }) {
  if (!loading && items.length === 0) return <section className="table-card"><Empty text="No reviews match the current filters" /></section>;
  return <section className="table-card"><table><thead><tr><th style={{ width: 150 }}>Project</th><th style={{ width: 100 }}>Author</th><th style={{ width: 150 }}>Branch</th><th style={{ width: 170 }}>Updated</th><th>Commit Message</th><th style={{ width: 120 }}>+/- Lines</th><th style={{ width: 70 }}>Score</th>{type === 'mr' && <th style={{ width: 100 }}>Actions</th>}</tr></thead><tbody>{items.map((item, index) => <tr key={`${item.type}-${item.project_name}-${item.updated_at}-${index}`}><td title={item.project_name}>{item.project_name}</td><td title={item.author}>{item.author}</td><td title={item.branch || ''}>{item.branch || '-'}</td><td title={formatTime(item.updated_at)}>{formatTime(item.updated_at)}</td><td title={item.commit_messages}>{item.commit_messages || '-'}</td><td><CodeChange additions={item.additions} deletions={item.deletions} /></td><td><ScoreBadge score={item.score} /></td>{type === 'mr' && <td>{item.url ? <a className="action-link" href={item.url} target="_blank" rel="noopener noreferrer">Details</a> : '—'}</td>}</tr>)}</tbody></table>{loading && <div className="empty">Loading...</div>}</section>;
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score == null || score === 0) return <span className="score-badge" style={{ background: '#4A6A8A' }}>-</span>;
  return <span className="score-badge" style={{ background: scoreColor(score) }}>{score}</span>;
}
function StatusPill({ score }: { score: number | null }) {
  if (score == null || score === 0) return <span className="status-pill" style={{ background: '#1A2F52', color: '#5A7A9A' }}>—</span>;
  return <span className="status-pill" style={{ background: statusBg(score), color: scoreColor(score) }}>{scoreStatus(score)}</span>;
}
function CodeChange({ additions, deletions }: { additions: number; deletions: number }) { return <span className="code-change"><b>+{additions}</b><span>/</span><i>-{deletions}</i></span>; }

function Pagination({ page, totalPages, pageSize, setPage, onPageSizeChange }: { page: number; totalPages: number; pageSize: number; setPage: (value: number | ((prev: number) => number)) => void; onPageSizeChange: (size: number) => void }) {
  return <div className="pagination"><div className="page-buttons"><button disabled={page <= 1} onClick={() => setPage((v) => Math.max(1, v - 1))}>‹</button><button className="active">{page}</button>{page + 1 <= totalPages && <button onClick={() => setPage(page + 1)}>{page + 1}</button>}{page + 2 <= totalPages && <button onClick={() => setPage(page + 2)}>{page + 2}</button>}{page + 2 < totalPages && <span>...</span>}{page + 2 < totalPages && <button onClick={() => setPage(totalPages)}>{totalPages}</button>}<button disabled={page >= totalPages} onClick={() => setPage((v) => Math.min(totalPages, v + 1))}>›</button></div><select className="page-size" value={pageSize} onChange={(e) => { onPageSizeChange(Number(e.target.value)); }}><option value={10}>10 / page</option><option value={20}>20 / page</option><option value={50}>50 / page</option></select></div>;
}

function MembersPage() {
  const [period, setPeriod] = useState<TimePeriod>('week');
  const ts = periodToTimestamps(period);
  const { data, error } = useAsync(() => fetchMembers(ts.start, ts.end), [period]);
  const members = data ?? emptyMembers;
  return <><Header current="Members" right={<TimeSegments active={period} onChange={setPeriod} />} />{error && <div className="error">{error}</div>}{members.items.length === 0 ? <Empty text="No member data available" /> : <MemberGrid items={members.items} period={period} />}<TeamSummary data={members} /></>;
}

function MemberGrid({ items, period }: { items: MemberItem[]; period: TimePeriod }) {
  const colors = ['#3B82F6', '#F59E0B', '#22C55E', '#8B5CF6', '#EC4899', '#06B6D4', '#F97316', '#64748B'];
  const days = periodDays(period);
  return <div className="member-grid">{items.map((item, index) => <section className="card member-card" key={item.author}><div className="member-top"><div className="avatar" style={{ background: colors[index % colors.length] }}>{item.author.slice(0, 1).toUpperCase()}</div><div className="member-name">{item.author}</div></div><div className="card-divider" /><div className="member-stats"><MiniStat label="Commits" value={item.review_count} color="#3B82F6" /><MiniStat label="Daily Avg" value={days > 0 ? Math.round((item.review_count / days) * 10) / 10 : '-'} color="#F59E0B" /><MiniStat label="Avg Score" value={item.average_score} color="#22C55E" /></div></section>)}</div>;
}

function MiniStat({ label, value, color }: { label: string; value: string | number; color: string }) { return <div className="mini-stat"><strong style={{ color }}>{value}</strong><span>{label}</span></div>; }

function TeamSummary({ data }: { data: MembersResponse }) {
  const metrics = [['Total Reviews', data.summary.total_reviews, '#3B82F6'], ['Team Avg', data.summary.team_average_score, '#22C55E'], ['Additions', data.summary.total_additions, '#8B5CF6'], ['Deletions', data.summary.total_deletions, '#F59E0B'], ['Active Members', data.summary.active_members, '#EC4899']] as const;
  return <section className="card team-card"><div className="card-title-row"><div><span style={{ color: '#8B5CF6' }}>●</span><span>Team Overview</span></div></div><div className="card-divider" /><div className="team-metrics">{metrics.map(([label, value, color]) => <div className="team-pill" key={label}><span>{label}</span><strong style={{ color }}>{value}</strong></div>)}</div></section>;
}

function Empty({ text }: { text: string }) { return <div className="empty">{text}</div>; }

export default App;
