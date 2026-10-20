import { defineConfig } from "vitest/config";

export default defineConfig({
    test: {
        environment: "jsdom",
        include: ["tests/js/**/*.test.js"],
        coverage: {
            provider: "v8",
            // Only what is missing: files fully covered left out, and the
            // uncovered lines in full (not cut to the terminal's width).
            reporter: [["text", { skipFull: true, maxCols: 0 }]],
            include: ["src/django_chat_ui/static/django_chat_ui/**/*.js"],
            // Nothing left untested: a drop fails the run.
            thresholds: { 100: true },
        },
    },
});
