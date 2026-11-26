import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const Engine = require('../public/cron-engine.js');

test('public/cron-engine.js rejects negative steps and out-of-bounds fields', () => {
  assert.equal(Engine.parseCron('*/-5 * * * *').isValid, false);
  assert.equal(Engine.parseCron('*/0 * * * *').isValid, false);
  assert.equal(Engine.parseCron('99 99 99 99 99').isValid, false);
});

test('public/cron-engine.js handles POSIX OR, leap years, macros, named DOW & transpilation', () => {
  const orRuns = Engine.getNextRuns('0 0 13 * 5', {
    count: 4,
    startDate: new Date('2026-11-26T00:00:00Z'),
    timezone: 'UTC',
  });
  assert.deepEqual(
    orRuns.map((d) => d.toISOString().slice(0, 10)),
    ['2026-11-27', '2026-12-04', '2026-12-11', '2026-12-13']
  );

  const leapRuns = Engine.getNextRuns('0 0 29 2 *', {
    count: 3,
    startDate: new Date('2026-11-26T00:00:00Z'),
    timezone: 'UTC',
  });
  assert.deepEqual(
    leapRuns.map((d) => d.toISOString().slice(0, 10)),
    ['2028-02-29', '2032-02-29', '2036-02-29']
  );

  assert.equal(Engine.parseCron('@daily').isValid, true);
  assert.equal(Engine.parseCron('@reboot').isReboot, true);
  assert.deepEqual(Engine.parseCron('0 9 * * MON-FRI').fields.dow, [1, 2, 3, 4, 5]);
  assert.deepEqual(Engine.parseCron('0 0 * * 7').fields.dow, [0]);

  assert.match(Engine.transpileCron('*/15 * * * *', 'systemd').syntax, /OnCalendar=\*-\*-\* \*:00\/15:00/);
  assert.match(Engine.transpileCron('30 4 * * 1-5', 'systemd').syntax, /OnCalendar=Mon\.\.Fri \*-\*-\* 04:30:00/);
  assert.equal(Engine.transpileCron('30 4 * * 1-5', 'eventbridge').syntax, 'cron(30 4 ? * MON-FRI *)');
  assert.equal(Engine.transpileCron('30 4 * * 1-5', 'quartz').syntax, '0 30 4 ? * MON-FRI *');
  assert.ok(Engine.transpileCron('0 0 13 * 5', 'systemd').warnings.length > 0);
});

test('public/cron-engine.js offline DST, Fleet, TZ Board, Heatmap toggle & Bundle export', () => {
  const dst = Engine.auditDstClient('30 2 * * *', 'America/New_York', 2026);
  assert.equal(dst.risk_level, 'HIGH');
  assert.ok(dst.anomalies.some((a) => a.type === 'SKIPPED_RUN'));

  const fleet = Engine.auditFleetClient({ a: '0 0 * * *', b: '0 0 * * *' });
  assert.equal(fleet.peak_concurrency, 2);

  const board = Engine.projectTzBoardClient('0 14 * * 1-5', 2);
  assert.equal(board.length, 2);
  assert.ok(board[0].hubs.length >= 5);

  assert.equal(Engine.toggleHourInExpression('0 9 * * *', 12), '0 9,12 * * *');
  assert.equal(Engine.buildExportBundle('30 4 * * 1-5').isValid, true);
});
