import test from 'node:test';
import assert from 'node:assert/strict';
import { instant, stageState, nextMilestone, buildICS, escapeHTML } from '../site/lib.js';

test('China date interpretation does not depend on visitor timezone', () => {
  assert.equal(instant('2026-12-06').toISOString(), '2026-12-05T16:00:00.000Z');
  assert.equal(stageState({start:'2026-12-06'}, new Date('2026-12-06T15:59:59Z')), 'active');
  assert.equal(stageState({start:'2026-12-06'}, new Date('2026-12-06T16:00:00Z')), 'past');
});
test('active end is selected before future printing start', () => {
  const exam = {events:{registration:{start:'2026-11-12T09:00:00+08:00',end:'2026-11-18T18:00:00+08:00'},admission:{start:'2026-12-01T09:00:00+08:00'}}};
  const next = nextMilestone(exam,new Date('2026-11-17T12:00:00+08:00'));
  assert.equal(next.key,'registration'); assert.equal(next.action,'截止');
});
test('open ended printing does not stay marked active forever', () => {
  assert.equal(stageState({start:'2026-12-02T09:00:00+08:00'},new Date('2027-01-01T00:00:00Z')),'open');
});
test('ICS exports UTC timed events and exclusive all day ends', () => {
  const ics = buildICS([{id:'test-2027',region_id:'test',year:2027,events:{registration:{start:'2026-11-12T09:00:00+08:00',end:'2026-11-18T18:00:00+08:00',source_url:'https://example.gov.cn',evidence:'报名'},exam:{start:'2026-12-06',source_url:'https://example.gov.cn',evidence:'笔试'}}}],new Map([['test',{name:'测试'}]]),new Date('2026-11-17T00:00:00Z'));
  assert.ok(ics.includes('DTSTART:20261112T010000Z'));
  assert.ok(ics.includes('DTEND:20261118T100000Z'));
  assert.ok(ics.includes('DTSTART;VALUE=DATE:20261206'));
  assert.ok(ics.includes('DTEND;VALUE=DATE:20261207'));
  assert.ok(ics.includes('\r\n'));
});
test('untrusted notice text is escaped for HTML', () => {
  assert.equal(escapeHTML('<img src=x onerror="alert(1)">'),'&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
});
test('mixed date precision exports a separate exact deadline', () => {
  const ics = buildICS([{id:'sc-2027',region_id:'sc',year:2027,events:{registration:{start:'2026-10-29',end:'2026-11-04T08:00:00+08:00',source_url:'https://example.gov.cn',evidence:'开始未注明时刻；结束为8点'}}}],new Map([['sc',{name:'四川'}]]));
  assert.ok(ics.includes('DTSTART;VALUE=DATE:20261029'));
  assert.ok(ics.includes('DTEND;VALUE=DATE:20261030'));
  assert.ok(ics.includes('DTSTART:20261104T000000Z'));
  assert.equal((ics.match(/BEGIN:VEVENT/g) || []).length,2);
});
