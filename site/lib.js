export const STAGES = { registration: '网上报名', payment: '确认缴费', admission: '准考证打印', exam: '公共科目笔试' };

// All date-only values are explicitly interpreted in China, never in the visitor's local zone.
export function instant(value, endOfDay = false) {
  if (!value) return null;
  return new Date(value.length === 10 ? `${value}T${endOfDay ? '23:59:59' : '00:00:00'}+08:00` : value);
}

export function stageState(event, now = new Date()) {
  if (!event) return 'unknown';
  if (now < instant(event.start)) return 'future';
  if (event.end && now <= instant(event.end, true)) return 'active';
  if (event.end) return 'past';
  if (event.start.length === 10) return now <= instant(event.start, true) ? 'active' : 'past';
  // An open-ended printing window must not be advertised as active indefinitely.
  return 'open';
}

export function nextMilestone(exam, now = new Date()) {
  const options = [];
  for (const [key, event] of Object.entries(exam.events || {})) {
    const state = stageState(event, now);
    if (state === 'active' && event.end) options.push({ key, value: event.end, action: '截止', event });
    else if (state === 'future') options.push({ key, value: event.start, action: key === 'exam' ? '开始' : '开放', event });
    else if (state === 'active' && key === 'exam') options.push({ key, value: event.start, action: '今日笔试', event, today: true });
  }
  return options.sort((a, b) => instant(a.value) - instant(b.value))[0] || null;
}

export function formatDate(value, withYear = false) {
  if (!value) return '待收录';
  const day = `${withYear ? value.slice(0,4) + '.' : ''}${value.slice(5,7)}.${value.slice(8,10)}`;
  return value.length > 10 ? `${day} ${value.slice(11,16)}` : day;
}

export function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function escapeICS(value) {
  return String(value ?? '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
}

function stamp(value) { return instant(value).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z'); }

function foldLine(line) {
  let output = '', current = '', width = 0;
  for (const char of line) {
    const size = new TextEncoder().encode(char).length;
    if (width + size > 73) { output += current + '\r\n '; current = ''; width = 1; }
    current += char; width += size;
  }
  return output + current;
}

export function buildICS(exams, regionMap, now = new Date()) {
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CivilServiceCalendar//CN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:公考日历', 'X-WR-TIMEZONE:Asia/Shanghai'];
  for (const exam of exams) {
    for (const [key, event] of Object.entries(exam.events || {})) {
      const dateOnly = event.start.length === 10;
      lines.push('BEGIN:VEVENT', `UID:${exam.id}-${key}@civil-service-deadlines`, `DTSTAMP:${stamp(now.toISOString())}`,
        `SUMMARY:${escapeICS(`${regionMap.get(exam.region_id)?.name || exam.region_id} ${exam.year} · ${STAGES[key]}`)}`,
        `DESCRIPTION:${escapeICS(`${event.evidence}\n时间以官方公告为准。\n${event.source_url}`)}`,
        `URL:${escapeICS(event.source_url)}`);
      if (dateOnly) {
        const mixedEnd = event.end && event.end.length > 10;
        const endDate = new Date(instant((mixedEnd ? event.start : event.end || event.start).slice(0,10)).getTime() + 86400000);
        const chinaDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(endDate).replace(/-/g, '');
        lines.push(`DTSTART;VALUE=DATE:${event.start.replace(/-/g, '')}`, `DTEND;VALUE=DATE:${chinaDate}`);
      } else {
        lines.push(`DTSTART:${stamp(event.start)}`);
        if (event.end) lines.push(`DTEND:${stamp(event.end)}`);
      }
      lines.push('END:VEVENT');
      if (dateOnly && event.end && event.end.length > 10) {
        // Unknown start clock: keep an all-day start marker and a separate exact deadline.
        lines.push('BEGIN:VEVENT', `UID:${exam.id}-${key}-deadline@civil-service-deadlines`, `DTSTAMP:${stamp(now.toISOString())}`,
          `SUMMARY:${escapeICS(`${regionMap.get(exam.region_id)?.name || exam.region_id} ${exam.year} · ${STAGES[key]}截止`)}`,
          `DESCRIPTION:${escapeICS(event.evidence)}`, `URL:${escapeICS(event.source_url)}`, `DTSTART:${stamp(event.end)}`, 'END:VEVENT');
      }
    }
  }
  return lines.map(foldLine).join('\r\n') + '\r\n';
}
