// Adds the DOM matchers (`toBeInTheDocument`, `toHaveFocus`, …) and clears the
// document between tests so one test's modal can never be another's fixture.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
