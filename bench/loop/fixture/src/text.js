'use strict';

// Shorten s to at most max characters, ending with '...' when it was cut.
function truncate(s, max) {
  if (s.length <= max) return s;
  return s.slice(0, max - 2) + '...';
}

// Number of whitespace-separated words in s; 0 for null, undefined or blank.
function wordCount(s) {
  return s.trim().split(/\s+/).length;
}

// Parse a duration such as '1h30m', '45s' or '2h5s' into seconds.
// Units are h, m and s, each at most once and in that order; anything else throws.
function parseDuration(text) {
  throw new Error('not implemented');
}

module.exports = { truncate, wordCount, parseDuration };
