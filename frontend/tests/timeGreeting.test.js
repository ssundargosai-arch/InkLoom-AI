import assert from "node:assert/strict";
import test from "node:test";

import { getTimeBasedGreeting } from "../src/utils/timeGreeting.js";

const localTime = (hour, minute = 0) => new Date(2026, 0, 15, hour, minute);

test("uses morning from 5:00 AM through 11:59 AM", () => {
  assert.equal(getTimeBasedGreeting(localTime(5)), "Good Morning");
  assert.equal(getTimeBasedGreeting(localTime(11, 59)), "Good Morning");
});

test("uses afternoon from 12:00 PM through 4:59 PM", () => {
  assert.equal(getTimeBasedGreeting(localTime(12)), "Good Afternoon");
  assert.equal(getTimeBasedGreeting(localTime(16, 59)), "Good Afternoon");
});

test("uses evening from 5:00 PM through 8:59 PM", () => {
  assert.equal(getTimeBasedGreeting(localTime(17)), "Good Evening");
  assert.equal(getTimeBasedGreeting(localTime(20, 59)), "Good Evening");
});

test("uses night from 9:00 PM through 4:59 AM", () => {
  assert.equal(getTimeBasedGreeting(localTime(21)), "Good Night");
  assert.equal(getTimeBasedGreeting(localTime(23, 59)), "Good Night");
  assert.equal(getTimeBasedGreeting(localTime(0)), "Good Night");
  assert.equal(getTimeBasedGreeting(localTime(4, 59)), "Good Night");
});
