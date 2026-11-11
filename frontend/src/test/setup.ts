import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

// jsdom lacks these browser APIs used by antd / recharts.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({ matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }),
});
class RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
// rc-util measures scrollbar size via getComputedStyle(el, "::-webkit-scrollbar"), which jsdom does not implement.
const gcs = window.getComputedStyle.bind(window);
window.getComputedStyle = ((el: Element) => gcs(el)) as typeof window.getComputedStyle;
