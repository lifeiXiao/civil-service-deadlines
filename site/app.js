import { STAGES, instant, stageState, nextMilestone, formatDate, escapeHTML as esc, buildICS } from './lib.js';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const state = { data: null, tab: 'all', regions: new Set(), favorites: new Set(), year: null, search: '', stage: 'all' };
let toastTimer;
try { const saved = JSON.parse(localStorage.getItem('gk-calendar-favorites') || '[]'); if (Array.isArray(saved)) state.favorites = new Set(saved.filter(id => typeof id === 'string')); } catch { /* Storage may be disabled. */ }

function toast(message) {
  clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3500);
}

function href(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? esc(url.href) : '#'; } catch { return '#'; }
}
function external(url, label, className = '') { return `<a class="${className}" href="${href(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`; }
function sourceError(message) {
  if (/timed out|timeout/i.test(message)) return '官网连接超时，将在下轮检查重试';
  if (/certificate|SSL/i.test(message)) return '官网证书或加密连接异常';
  if (/404/.test(message)) return '来源页面暂不可用，需要核对入口';
  if (/403|412|418|robots|验证|间隔/.test(message)) return '官网限制自动读取，请直接查看官方入口';
  return '本轮未能读取部分页面，保留已收录的时间';
}
function regionMap() { return new Map(state.data.regions.map(region => [region.id, region])); }
function records() {
  return state.data.regions.map(region => ({ region, exam: state.data.exams.find(exam => exam.region_id === region.id && exam.year === state.year) || { id: `${region.id}-${state.year}`, region_id: region.id, year: state.year, events: {} } }));
}

function filteredRows() {
  const now = new Date();
  return records().filter(({ region, exam }) => {
    if (state.regions.size && !state.regions.has(region.id)) return false;
    if (state.tab === 'favorites' && !state.favorites.has(region.id)) return false;
    if (state.search && !`${region.name}${region.group}${region.id}${region.id === 'national' ? '国家公务员中央机关' : '省考公务员'}`.toLowerCase().includes(state.search.toLowerCase())) return false;
    const events = Object.entries(exam.events);
    const active = events.filter(([, event]) => stageState(event, now) === 'active');
    if (state.stage === 'active' && !active.some(([key]) => key !== 'exam')) return false;
    if (state.stage === 'upcoming' && !nextMilestone(exam, now)) return false;
    if (state.stage === 'pending' && events.length) return false;
    if (['registration', 'admission'].includes(state.stage) && stageState(exam.events[state.stage], now) !== 'active') return false;
    return true;
  }).sort((a, b) => {
    const nextA = nextMilestone(a.exam, now), nextB = nextMilestone(b.exam, now);
    if (nextA && nextB) return instant(nextA.value) - instant(nextB.value);
    if (nextA || nextB) return nextA ? -1 : 1;
    return Number(Object.keys(b.exam.events).length > 0) - Number(Object.keys(a.exam.events).length > 0) || state.data.regions.indexOf(a.region) - state.data.regions.indexOf(b.region);
  });
}

function stageHTML(key, event, now) {
  const stage = stageState(event, now);
  let date = '待收录';
  if (event) {
    const start = formatDate(event.start);
    if (event.end) date = `${esc(start.split(' ')[0])} — ${esc(formatDate(event.end).split(' ')[0])}<span class="time">${event.start.length > 10 ? esc(event.start.slice(11,16)) : '未注明时刻'} → ${event.end.length > 10 ? esc(event.end.slice(11,16)) : '未注明时刻'}</span>`;
    else date = `${esc(start.split(' ')[0])}<span class="time">${event.start.length > 10 ? esc(event.start.slice(11,16)) + ' 起 · 截止未注明' : '具体时段见公告'}</span>`;
  }
  return `<div class="stage ${stage}"><span class="stage-marker"></span><span class="stage-label">${STAGES[key]}</span><span class="stage-date">${date}</span>${event ? external(event.source_url, '原文 ↗', 'stage-link') : ''}</div>`;
}

function countdownHTML(value, today = false) {
  if (today) return '今日笔试';
  if (value.length === 10) {
    const chinaToday = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    const days = Math.round((instant(value) - instant(chinaToday)) / 86400000);
    return days > 0 ? `${days}<span>天后</span>` : '今日安排';
  }
  const seconds = Math.max(0, Math.floor((instant(value) - new Date()) / 1000));
  const days = Math.floor(seconds / 86400), hours = Math.floor(seconds / 3600) % 24, minutes = Math.floor(seconds / 60) % 60;
  return days ? `${days}<span>天</span>${hours}<span>时</span>` : `${String(hours).padStart(2,'0')}<span>时</span>${String(minutes).padStart(2,'0')}<span>分</span>${String(seconds % 60).padStart(2,'0')}<span>秒</span>`;
}

function cardHTML({ region, exam }) {
  const known = Object.keys(exam.events).length > 0, now = new Date(), next = nextMilestone(exam, now);
  const saved = state.favorites.has(region.id), manual = Object.values(exam.events).some(event => event.verification === 'manual');
  const nextLabel = next ? `${STAGES[next.key]}${next.action}` : (known ? '后续安排以官网为准' : '持续关注官方公告');
  const content = known ? `<div class="stages">${Object.keys(STAGES).map(key => stageHTML(key, exam.events[key], now)).join('')}</div>` : '<p class="pending-message">本站尚未核验本年度时间表。<br>可先关注此地区，或前往官方入口查看。</p>';
  const urgent = next && !next.today && (instant(next.value) - now) < 3 * 86400000;
  const verification = known ? (manual ? '含人工核验' : '官方原文提取') : '时间待核验';
  return `<article class="exam-card ${known ? '' : 'pending-card'}" data-exam="${esc(exam.id)}"><div class="card-main"><div class="card-heading"><div><h2 class="exam-title">${esc(region.name)}${region.id === 'national' ? '' : '省考'}<span class="year-badge">${exam.year}</span><span class="type-badge">${region.id === 'national' ? '全国招录' : region.group}</span></h2><p class="card-subtitle">${region.id === 'national' ? '中央机关及其直属机构考试录用公务员' : `${esc(region.name)}公务员考试 · ${exam.year} 招录年度`}</p></div><button class="favorite-button ${saved ? 'saved' : ''}" data-favorite="${esc(region.id)}" aria-label="${saved ? '取消关注' : '关注'}${esc(region.name)}" aria-pressed="${saved}" title="${saved ? '取消关注' : '关注此考试'}">${saved ? '★' : '☆'}</button></div><div class="card-content">${content}<div class="deadline-box"><span class="deadline-label">${nextLabel}</span><strong class="countdown ${urgent ? 'urgent' : ''}" ${next ? `data-deadline="${esc(next.value)}" data-today="${!!next.today}"` : ''}>${next ? countdownHTML(next.value, next.today) : known ? '查看公告' : '待收录'}</strong><span class="deadline-exact">${next ? formatDate(next.value, true) : '不推测未确认的日期'}</span></div></div></div>${known ? `<details class="card-detail"><summary>来源与核验说明</summary>${(exam.notes || []).map(note => `<p>${esc(note)}</p>`).join('')}<ul>${Object.entries(exam.events).map(([key, event]) => `<li>${STAGES[key]} · ${event.verification === 'manual' ? '人工核验' : '自动提取'}<br><span class="evidence">${esc(event.evidence)}</span></li>`).join('')}</ul></details>` : ''}<div class="card-footer"><div class="card-links">${exam.announcement_url ? external(exam.announcement_url, '招考公告 ↗') : ''}${external(region.portal, '官方入口 ↗')}${known ? `<button class="calendar-button" data-calendar="${esc(exam.id)}">↓ 加入日历</button>` : ''}</div><span class="verification">${verification}</span></div></article>`;
}

function renderRegions() {
  const groups = [...new Set(state.data.regions.map(region => region.group))];
  $('#region-filters').innerHTML = groups.map(group => `<div class="region-group"><h3>${esc(group)}</h3><div class="region-buttons">${state.data.regions.filter(region => region.group === group).map(region => `<button class="region-button ${state.regions.has(region.id) ? 'selected' : ''} ${state.data.exams.some(exam => exam.region_id === region.id && exam.year === state.year && Object.keys(exam.events).length) ? 'has-date' : ''}" data-region="${esc(region.id)}" aria-pressed="${state.regions.has(region.id)}">${esc(region.name)}</button>`).join('')}</div></div>`).join('');
  $('#all-regions').classList.toggle('selected', !state.regions.size); $('#all-regions').setAttribute('aria-pressed', !state.regions.size);
}

function renderSources() {
  const statuses = new Map((state.data.status.sources || []).map(item => [item.id, item]));
  $('#source-health').innerHTML = state.data.regions.map(region => {
    const item = statuses.get(region.id), status = item?.state || 'pending';
    const labels = { ok: '找到公告', limited: '读取受限', error: '检查失败', pending: '尚未检查' };
    return `<div class="source-row"><strong>${esc(region.name)}</strong><div>${external(region.portal, esc(new URL(region.portal).hostname) + ' ↗')}<small>${item?.checked_at ? '最近尝试 ' + esc(formatDate(item.checked_at, true)) : '等待首次云端检查'}</small>${item?.errors?.length ? `<small>${esc(sourceError(item.errors[0].message))}</small>` : ''}</div><span class="source-state ${status}">${labels[status]}${item?.last_success_at ? `<small>最近找到公告<br>${esc(formatDate(item.last_success_at, true))}</small>` : ''}</span></div>`;
  }).join('');
}

function renderStats() {
  const rows = records(), now = new Date();
  $('#active-count').textContent = rows.filter(({ exam }) => Object.entries(exam.events).some(([key,event]) => key !== 'exam' && stageState(event, now) === 'active')).length;
  $('#verified-count').textContent = rows.filter(({exam}) => Object.keys(exam.events).length).length;
  $('#region-count').textContent = state.data.regions.length;
  $('#cycle-label').textContent = `${state.year} 招录年度 · 均有原文来源`;
  $('#favorite-count').textContent = state.favorites.size;
  $('#check-time').textContent = state.data.status.last_full_check_at ? `最近检查 ${formatDate(state.data.status.last_full_check_at)}` : '等待首次完整官网检查';
  const last = state.data.status.last_full_check_at;
  const outage = state.data.status.summary?.readable === 0;
  const stale = !last || outage || (now - instant(last)) > 36 * 3600000;
  $('#freshness').hidden = !stale;
  $('#freshness').textContent = outage ? '最近一轮官网读取均未成功，当前显示保留的时间表。请同时查看官方公告。' : last ? '最近一次完整检查距今已超过 36 小时。当前显示上次保留的数据，请同时查看官方公告。' : '自动检查尚未完成首次全量运行。当前显示已人工核验的时间表。';
}

function renderUpdates() {
  const names = regionMap();
  const entries = state.data.notices.length ? state.data.notices : state.data.exams.map(exam => ({ region_id: exam.region_id, year: exam.year, title: `${names.get(exam.region_id)?.name} ${exam.year} 年度考试时间表已核验收录`, url: exam.announcement_url, first_seen_at: exam.updated_at, review: false, manual: true }));
  const visible = entries.filter(item => item.year === state.year && (!state.regions.size || state.regions.has(item.region_id)) && (!state.search || `${names.get(item.region_id)?.name}${item.title}`.includes(state.search))).slice(0,100);
  $('#updates-list').innerHTML = visible.length ? visible.map(item => `<article class="update-card"><div class="update-meta"><span>${esc(names.get(item.region_id)?.name || item.region_id)} · ${item.year}</span><span>${esc(formatDate(item.changed_at || item.first_seen_at, true))}</span>${item.review ? '<span class="review-badge">待核验</span>' : ''}</div><h3>${esc(item.title)}</h3><p>${item.review ? '发现新公告或日期冲突，暂未据此覆盖已确认的时间。请查看官方原文。' : item.manual ? '时间已人工对照官方来源核验。' : '已检查公告；能明确提取且不与现有记录冲突的时间会自动收录。'}${item.changed_at ? ' 原文内容较上次检查有变化。' : ''}</p>${external(item.url, '阅读官方公告 ↗')}</article>`).join('') : '<div class="empty">当前筛选下暂无公告更新。</div>';
  $('#result-caption').textContent = `展示 ${visible.length} 条公告记录 · 待核验信息不会直接覆盖已确认时间`;
}

function render() {
  if (!state.data) return;
  renderRegions(); renderStats();
  $$('.tab').forEach(tab => { const active = tab.dataset.tab === state.tab; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', active); tab.tabIndex = active ? 0 : -1; });
  const updates = state.tab === 'updates';
  $('#exam-list').hidden = updates; $('#updates-list').hidden = !updates;
  $('#stage-select').disabled = updates; $('#export-favorites').hidden = updates; $('#list-footnote').hidden = updates;
  if (updates) { renderUpdates(); return; }
  const rows = filteredRows();
  $('#list-count').textContent = records().length;
  const known = rows.filter(({exam}) => Object.keys(exam.events).length).length;
  $('#result-caption').textContent = `${rows.length} 场考试 · ${known} 份时间表已收录 · 按最近时间节点排序`;
  $('#exam-list').innerHTML = rows.length ? rows.map(cardHTML).join('') : `<div class="empty"><strong>${state.tab === 'favorites' && !state.favorites.size ? '把重要的考试，放在一起。' : '没有符合条件的考试'}</strong>${state.tab === 'favorites' && !state.favorites.size ? '点击考试右上角的 ☆，即可加入关注。关注只保存在当前浏览器。' : '试试更换地区、阶段或搜索关键词。'}<br><button data-clear>查看全部考试 →</button></div>`;
}

async function loadData() {
  $('#refresh-button').disabled = true;
  try {
    const response = await fetch(`./data/catalog.json?v=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.schema_version !== 1 || !Array.isArray(data.regions) || !Array.isArray(data.exams)) throw new Error('数据格式错误');
    state.data = data;
    const years = [...new Set([data.cycle_year, ...data.exams.map(exam => exam.year)])].sort((a,b) => b-a);
    if (!years.includes(state.year)) state.year = data.cycle_year;
    $('#year-select').innerHTML = years.map(year => `<option value="${year}">${year} 招录年度</option>`).join(''); $('#year-select').value = state.year;
    render(); renderSources();
  } catch (error) {
    if (state.data) toast('暂时无法读取新数据，已保留当前时间表。');
    else $('#exam-list').innerHTML = '<div class="empty"><strong>暂时无法读取时间表</strong>请检查网络后重试。<br><button data-retry>重新加载 →</button></div>';
    console.error('Calendar data load failed:', error);
  } finally { $('#refresh-button').disabled = false; }
}

function exportCalendar(exams) {
  const populated = exams.filter(exam => Object.keys(exam.events).length);
  if (!populated.length) return toast('请先关注已收录时间表的考试，再导出日历。');
  const blob = new Blob([buildICS(populated, regionMap())], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob), anchor = document.createElement('a');
  anchor.href = url; anchor.download = `公考日历-${state.year}.ics`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('已导出日历文件，可导入手机或电脑日历。后续变更需重新导入。');
}

function reset() { state.regions.clear(); state.search = ''; state.stage = 'all'; $('#search').value = ''; $('#stage-select').value = 'all'; render(); }
$('#all-regions').addEventListener('click', () => { state.regions.clear(); render(); });
$('#reset-filters').addEventListener('click', reset);
$('#region-filters').addEventListener('click', event => { const button = event.target.closest('[data-region]'); if (!button) return; state.regions.has(button.dataset.region) ? state.regions.delete(button.dataset.region) : state.regions.add(button.dataset.region); render(); });
$$('.tab').forEach(tab => {
  tab.addEventListener('click', () => { state.tab = tab.dataset.tab; render(); });
  tab.addEventListener('keydown', event => { if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; event.preventDefault(); const tabs = $$('.tab'), index = tabs.indexOf(tab); const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length; state.tab = tabs[next].dataset.tab; render(); tabs[next].focus(); });
});
$('#search').addEventListener('input', event => { state.search = event.target.value.trim(); render(); });
$('#year-select').addEventListener('change', event => { state.year = Number(event.target.value); render(); });
$('#stage-select').addEventListener('change', event => { state.stage = event.target.value; render(); });
$('#refresh-button').addEventListener('click', async () => { await loadData(); if (state.data) toast('已读取最新已发布的数据；官网检查每天由云端运行。'); });
$('#export-favorites').addEventListener('click', () => exportCalendar(records().filter(({region}) => state.favorites.has(region.id)).map(({exam}) => exam)));
$('#exam-list').addEventListener('click', event => {
  const favorite = event.target.closest('[data-favorite]'), calendar = event.target.closest('[data-calendar]');
  if (favorite) { const id = favorite.dataset.favorite; state.favorites.has(id) ? state.favorites.delete(id) : state.favorites.add(id); try { localStorage.setItem('gk-calendar-favorites', JSON.stringify([...state.favorites])); } catch { toast('浏览器禁止保存，关注将在关闭页面后丢失。'); } render(); }
  if (calendar) exportCalendar(records().filter(({exam}) => exam.id === calendar.dataset.calendar).map(({exam}) => exam));
  if (event.target.closest('[data-clear]')) { state.tab = 'all'; reset(); }
  if (event.target.closest('[data-retry]')) loadData();
});
$('#source-button').addEventListener('click', () => $('#sources-dialog').showModal());
$('#close-dialog').addEventListener('click', () => $('#sources-dialog').close());
$('#sources-dialog').addEventListener('click', event => { if (event.target === $('#sources-dialog')) { const box = event.target.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) event.target.close(); } });
document.addEventListener('keydown', event => { if (event.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName) && !$('#sources-dialog').open) { event.preventDefault(); $('#search').focus(); } });
function updateClock() {
  const now = new Date();
  $('#today-date').textContent = new Intl.DateTimeFormat('zh-CN', { timeZone:'Asia/Shanghai', year:'numeric', month:'long', day:'numeric' }).format(now);
  $('#today-weekday').textContent = new Intl.DateTimeFormat('zh-CN', { timeZone:'Asia/Shanghai', weekday:'long' }).format(now);
  $$('[data-deadline]').forEach(node => { node.innerHTML = countdownHTML(node.dataset.deadline, node.dataset.today === 'true'); });
}
updateClock(); setInterval(updateClock, 1000);
setInterval(() => { if (!document.hidden && !$('#sources-dialog').open) render(); }, 60000);
setInterval(() => { if (!document.hidden) loadData(); }, 5 * 60000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) loadData(); });
loadData();
