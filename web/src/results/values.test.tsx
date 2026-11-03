// web/src/results/values.test.tsx - the parts of the value counts that need no API: the axis, the shades, the URL.
import { countMax } from "./BucketProfile";
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

test("the count axis is the smallest 1, 2 or 5 times a power of ten that holds the largest count", () => {
  expect([1, 3, 40, 51, 649, 2000].map(countMax)).toEqual([1, 5, 50, 100, 1000, 2000]);
});
