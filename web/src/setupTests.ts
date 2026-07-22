// Vitest setup (Step 14): loads jest-dom's matchers (toBeVisible,
// toHaveTextContent, ...) globally and cleans up the DOM between
// tests, so individual test files don't each have to remember to.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
