import assert from "node:assert/strict";

import {
  toMonthlyPlanLineCreatePayload,
  toMonthlyPlanLineUpdatePayload,
} from "../dist/tools/monthly-planning.js";

const baseLine = {
  target_period: "2026-06",
  line_type: "expense",
  target_type: "account",
  account_id: 10,
  name: "Food",
  amount: 42000,
  source: "manual",
  is_active: true,
  priority: 2,
  note: "This field is not accepted by the backend API.",
};

const createPayload = toMonthlyPlanLineCreatePayload(baseLine);
assert.equal(createPayload.id, undefined);
assert.equal(createPayload.priority, undefined);
assert.equal(createPayload.note, undefined);
assert.equal(createPayload.target_period, "2026-06");
assert.equal(createPayload.line_type, "expense");
assert.equal(createPayload.amount, 42000);

const updatePayload = toMonthlyPlanLineUpdatePayload({ id: 123, ...baseLine });
assert.equal(updatePayload.id, 123);
assert.equal(updatePayload.priority, undefined);
assert.equal(updatePayload.note, undefined);
assert.equal(updatePayload.target_period, "2026-06");
assert.equal(updatePayload.line_type, "expense");
assert.equal(updatePayload.amount, 42000);

console.log("monthly planning contract ok");
