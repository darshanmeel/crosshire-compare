// web/src/results/values.test.tsx - the parts of the value counts that need no API: the axis, the shades, the URL.
import { axisMax, rankCls, valuesUrl } from "./valuesApi";

test("the axis is the smallest round step that holds the largest share", () => {
  expect(axisMax(7.23)).toBe(10);
  expect(axisMax(60.46)).toBe(100);
  expect(axisMax(0.3)).toBe(1);
  expect(axisMax(25)).toBe(25);
});

test("the first three values have their own shade, the rest one", () => {
  expect([0, 1, 2, 3, 9].map(rankCls)).toEqual(["r1", "r2", "r3", "rn", "rn"]);
});

test("the URL lists what is asked, in one order, without empty parts", () => {
  expect(valuesUrl("r1", { size: 3, column: "a/b %", side: "a", differs: "", basis: "nonnull" }))
    .toBe("/api/results/r1/values?column=a%2Fb+%25&side=a&basis=nonnull&size=3");
});
