import test from "node:test";
import assert from "node:assert/strict";
import { hasMessage, t } from "./i18n.js";

test("resources provide Chinese text and deterministic fallback", () => {
  assert.equal(t("common.cancel"), "取消");
  assert.equal(t("common.cancel", {}, "unknown"), "取消");
  assert.equal(t("common.cancel", {}, "__proto__"), "取消");
});

test("named interpolation preserves zero and literal data", () => {
  assert.equal(t("common.count", { count: 0 }), "0 项");
  assert.equal(t("common.count", { count: "<data>" }), "<data> 项");
});

test("missing keys and parameters fail explicitly", () => {
  assert.throws(() => t("missing"), /missing/);
  assert.throws(() => t("common.count"), /count/);
});

test("prototype properties are not translation entries", () => {
  assert.equal(hasMessage("__proto__"), false);
  assert.equal(hasMessage("constructor"), false);
  assert.equal(hasMessage("common.confirm"), true);
});