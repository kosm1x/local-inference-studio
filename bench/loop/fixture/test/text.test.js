'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { truncate, wordCount, parseDuration } = require('../src/text');

test('truncate keeps short strings and cuts long ones to max', () => {
  assert.strictEqual(truncate('hello', 5), 'hello');
  assert.strictEqual(truncate('hello world', 8), 'hello...');
  assert.strictEqual(truncate('abcdefghij', 6), 'abc...');
  assert.strictEqual(truncate('abcdefghij', 6).length, 6);
});

test('wordCount handles null, undefined and blank input', () => {
  assert.strictEqual(wordCount('one  two\tthree'), 3);
  assert.strictEqual(wordCount(null), 0);
  assert.strictEqual(wordCount(undefined), 0);
  assert.strictEqual(wordCount('   '), 0);
});

test('parseDuration converts h/m/s strings to seconds', () => {
  assert.strictEqual(parseDuration('45s'), 45);
  assert.strictEqual(parseDuration('2h'), 7200);
  assert.strictEqual(parseDuration('90m'), 5400);
  assert.strictEqual(parseDuration('1h30m'), 5400);
  assert.strictEqual(parseDuration('1h2m3s'), 3723);
  for (const bad of ['', 'abc', '10x', '5', 'h1', '1m2h', '1h1h']) {
    assert.throws(() => parseDuration(bad), Error, `expected a throw for ${JSON.stringify(bad)}`);
  }
});
