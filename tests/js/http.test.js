import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatClient } from "../../src/django_chat_ui/static/django_chat_ui/client.js";
import {
    HttpTransport,
    httpUploader,
} from "../../src/django_chat_ui/static/django_chat_ui/transports/http.js";

/** An EventSource that the test drives. */
class FakeSource {
    static last = null;
    constructor(url) {
        this.url = url;
        this.readyState = 0;
        this.closed = false;
        FakeSource.last = this;
    }
    open() {
        this.readyState = 1;
        this.onopen?.();
    }
    push(frame) {
        this.onmessage?.({
            data: typeof frame === "string" ? frame : JSON.stringify(frame),
        });
    }
    fail() {
        this.readyState = 2;
        this.onerror?.();
    }
    close() {
        this.closed = true;
    }
}

function json(body, status = 200) {
    return Promise.resolve({
        ok: status < 300,
        status,
        json: () => Promise.resolve(body),
    });
}

const READY = {
    type: "ready",
    data: { protocol: "1.0", me: { id: "1", kind: "user" }, conversations: [] },
};

afterEach(() => {
    vi.useRealTimers();
});

describe("HttpTransport over SSE", () => {
    it("opens the stream, then says hello by POST, taking the answers from the response", async () => {
        const fetch = vi.fn((_url, init) => {
            const frame = JSON.parse(init.body);
            return json([{ ...READY, ref: frame.id }]);
        });
        const transport = new HttpTransport({
            events: "/chat/events",
            commands: "/chat/commands",
            csrfToken: "tok",
            fetch,
            EventSource: FakeSource,
        });
        const client = new ChatClient(transport);

        const connecting = client.connect();
        expect(FakeSource.last.url).toBe("/chat/events");
        FakeSource.last.open();
        const ready = await connecting;

        expect(ready.me.id).toBe("1");
        const [url, init] = fetch.mock.calls[0];
        expect(url).toBe("/chat/commands");
        expect(init.method).toBe("POST");
        expect(init.credentials).toBe("same-origin");
        expect(init.headers["X-CSRFToken"]).toBe("tok");
        expect(JSON.parse(init.body).type).toBe("hello");
    });

    it("hands the stream's frames to the client, ignoring what isn't one", async () => {
        const transport = new HttpTransport({
            events: "/e?x=1",
            commands: "/c",
            EventSource: FakeSource,
            fetch: vi.fn(),
        });
        const frames = [];
        const connecting = transport.connect((frame) => frames.push(frame), {
            resume: { seq: 7 },
        });
        expect(FakeSource.last.url).toBe("/e?x=1&after=7");
        FakeSource.last.open();
        await connecting;

        FakeSource.last.push({ type: "typing", seq: 8, data: {} });
        FakeSource.last.push("not json");
        expect(frames).toEqual([{ type: "typing", seq: 8, data: {} }]);

        const source = FakeSource.last;
        transport.close();
        expect(source.closed).toBe(true);
    });

    it("fails if the stream never opens, not when it reconnects", async () => {
        const transport = new HttpTransport({
            events: "/e",
            commands: "/c",
            EventSource: FakeSource,
            fetch: vi.fn(),
        });
        const failing = transport.connect(() => {});
        FakeSource.last.fail();
        await expect(failing).rejects.toThrow("can't be opened");

        const opening = transport.connect(() => {});
        FakeSource.last.open();
        await opening;
        FakeSource.last.readyState = 0; // reconnecting
        expect(() => FakeSource.last.onerror()).not.toThrow();
    });

    it("rejects a command without answers, as a transport failure", async () => {
        const transport = new HttpTransport({
            events: "/e",
            commands: "/c",
            EventSource: FakeSource,
            fetch: () => json(null, 502),
        });
        await expect(
            transport.send({ type: "typing", id: "1" }),
        ).rejects.toThrow("HTTP 502");
        const broken = new HttpTransport({
            events: "/e",
            commands: "/c",
            fetch: () =>
                Promise.resolve({
                    ok: false,
                    status: 500,
                    json: () => Promise.reject(new Error("html")),
                }),
        });
        await expect(broken.send({})).rejects.toThrow("HTTP 500");
    });

    it("delivers an error answer (403) as a frame", async () => {
        const frames = [];
        const transport = new HttpTransport({
            events: "/e",
            commands: "/c",
            fetch: () =>
                json(
                    [
                        {
                            type: "error",
                            data: { code: "unauthorized", fatal: true },
                        },
                    ],
                    403,
                ),
        });
        transport.onFrame = (frame) => frames.push(frame);
        await transport.send({ type: "hello", id: "1" });
        expect(frames[0].data.code).toBe("unauthorized");
    });
});

describe("HttpTransport polling", () => {
    it("polls the events after the last seq", async () => {
        vi.useFakeTimers();
        const answers = [
            { frames: [], seq: 10 },
            { frames: [{ type: "typing", seq: 11, data: {} }], seq: 12 },
        ];
        const fetch = vi.fn(() =>
            json(answers.shift() ?? { frames: [], seq: 12 }),
        );
        const transport = new HttpTransport({
            events: "/e",
            commands: "/c",
            poll: 1000,
            fetch,
        });
        const frames = [];

        await transport.connect((frame) => frames.push(frame));
        expect(fetch.mock.calls[0][0]).toBe("/e");
        expect(fetch.mock.calls[0][1].headers.Accept).toBe("application/json");

        await vi.advanceTimersByTimeAsync(1000);
        expect(fetch.mock.calls[1][0]).toBe("/e?after=10");
        expect(frames).toEqual([{ type: "typing", seq: 11, data: {} }]);

        await vi.advanceTimersByTimeAsync(1000);
        expect(fetch.mock.calls[2][0]).toBe("/e?after=12");

        transport.close();
        await vi.advanceTimersByTimeAsync(5000);
        expect(fetch).toHaveBeenCalledTimes(3);
    });

    it("keeps polling after a failure", async () => {
        vi.useFakeTimers();
        const fetch = vi
            .fn()
            .mockReturnValueOnce(json({ frames: [], seq: 1 }))
            .mockReturnValueOnce(json({}, 500))
            .mockReturnValue(json({ frames: [], seq: 1 }));
        const transport = new HttpTransport({
            events: "/e",
            commands: "/c",
            poll: 100,
            fetch,
        });
        await transport.connect(() => {});
        await vi.advanceTimersByTimeAsync(250);
        expect(fetch.mock.calls.length).toBeGreaterThanOrEqual(3);
        transport.close();
    });
});

describe("httpUploader", () => {
    it("POSTs the file for its conversation, and gives its part", async () => {
        const part = { type: "image", url: "/chat/uploads/1/a.png" };
        const fetch = vi.fn(() => json(part));
        const upload = httpUploader({
            uploads: "/chat/uploads",
            csrfToken: "tok",
            fetch,
        });

        const file = new File(["x"], "a.png", { type: "image/png" });
        expect(await upload(file, "5")).toEqual(part);
        const [url, init] = fetch.mock.calls[0];
        expect(url).toBe("/chat/uploads");
        expect(init.headers["X-CSRFToken"]).toBe("tok");
        expect(init.body.get("conversation")).toBe("5");
        expect(init.body.get("file").name).toBe("a.png");
    });

    it("throws the server's error", async () => {
        const upload = httpUploader({
            uploads: "/u",
            fetch: () => json({ error: { message: "Too big" } }, 413),
        });
        await expect(upload(new File(["x"], "a"), "1")).rejects.toThrow(
            "Too big",
        );
        const bare = httpUploader({
            uploads: "/u",
            fetch: () =>
                Promise.resolve({
                    ok: false,
                    status: 500,
                    json: () => Promise.reject(new Error()),
                }),
        });
        await expect(bare(new File(["x"], "a"), "1")).rejects.toThrow(
            "HTTP 500",
        );
    });
});
