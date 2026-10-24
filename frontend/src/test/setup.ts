import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
afterAll(() => server.close());
