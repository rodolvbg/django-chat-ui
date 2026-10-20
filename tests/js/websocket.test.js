import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatClient } from "../../src/django_chat_ui/static/django_chat_ui/client.js";
import { WebSocketTransport } from "../../src/django_chat_ui/static/django_chat_ui/transports/websocket.js";

class FakeSocket {
    static all = [];
    constructor(url) {
        this.url = url;
        this.readyState = 0;
        this.sent = [];
        FakeSocket.all.push(this);
    }
    open() {
        this.readyState = 1;
        this.onopen?.();
    }
    send(text) {
        this.sent.push(JSON.parse(text));
    }
    push(frame) {
        this.onmessage?.({
            data: typeof frame === "string" ? frame : JSON.stringify(frame),
        });
    }
    close() {
        this.readyState = 3;
        this.onclose?.();
    }
    drop() {
        this.readyState = 3;
        this.onclose?.();
    }
}

const last = () => FakeSocket.all.at(-1);

afterEach(() => {
    FakeSocket.all = [];
    vi.useRealTimers();
});

describe("WebSocketTransport", () => {
    it("says hello over the socket and gets its answers and events on it", async () => {
        const transport = new WebSocketTransport({
            url: "/chat/ws",
            WebSocket: FakeSocket,
        });
        expect(transport.url).toBe(`ws://${location.host}/chat/ws`);
        const client = new ChatClient(transport);
        const connecting = client.connect();
        last().open();
        await Promise.resolve();
        await Promise.resolve();
        const [hello] = last().sent;
        expect(hello.type).toBe("hello");
        last().push({
            type: "ready",
            ref: hello.id,
            data: { protocol: "1.0", me: { id: "1" } },
        });
        expect((await connecting).me.id).toBe("1");

        last().push({ type: "typing", seq: 5, data: {} });
        last().push("not json");
        expect(transport.seq).toBe(5);
        expect(client.seq).toBe(5);
    });

    it("reconnects by itself, saying hello again from the last seq", async () => {
        vi.useFakeTimers();
        const transport = new WebSocketTransport({
            url: "wss://x/chat/ws",
            retry: 100,
            WebSocket: FakeSocket,
        });
        expect(transport.url).toBe("wss://x/chat/ws");
        const connecting = transport.connect(() => {});
        last().open();
        await connecting;
        await transport.send({
            type: "hello",
            id: "h",
            data: { protocol: ["1.0"], resume: { seq: 1 } },
        });
        last().push({ type: "typing", seq: 9, data: {} });

        last().drop();
        await vi.advanceTimersByTimeAsync(100);
        last().open();
        await vi.advanceTimersByTimeAsync(0);
        expect(last().sent).toEqual([
            {
                type: "hello",
                id: "h-1",
                data: { protocol: ["1.0"], resume: { seq: 9 } },
            },
        ]);

        // A failed reconnection: tried again.
        last().drop();
        await vi.advanceTimersByTimeAsync(100);
        last().close(); // never opened
        await vi.advanceTimersByTimeAsync(100);
        last().open();
        await vi.advanceTimersByTimeAsync(0);
        expect(last().sent[0].id).toBe("h-2");

        transport.close();
        await vi.advanceTimersByTimeAsync(1000);
        expect(FakeSocket.all).toHaveLength(4);
    });

    it("says hello without resume when it got nothing yet", async () => {
        vi.useFakeTimers();
        const transport = new WebSocketTransport({
            url: "ws://x",
            retry: 10,
            WebSocket: FakeSocket,
        });
        const connecting = transport.connect(() => {});
        last().open();
        await connecting;
        last().drop(); // before any hello: nothing to say again
        await vi.advanceTimersByTimeAsync(10);
        last().open();
        await vi.advanceTimersByTimeAsync(0);
        expect(last().sent).toEqual([]);

        await transport.send({
            type: "hello",
            id: "h",
            data: { protocol: ["1.0"] },
        });
        last().drop();
        await vi.advanceTimersByTimeAsync(10);
        last().open();
        await vi.advanceTimersByTimeAsync(0);
        expect(last().sent.at(-1).data).toEqual({ protocol: ["1.0"] });
        transport.close();
        await transport.reopen(); // closed: nothing
    });

    it("fails to connect, or to send, without a socket", async () => {
        const transport = new WebSocketTransport({
            url: "ws://x",
            WebSocket: FakeSocket,
        });
        await expect(transport.send({ type: "typing" })).rejects.toThrow(
            "isn't open",
        );
        const connecting = transport.connect(() => {});
        last().close();
        await expect(connecting).rejects.toThrow("can't be opened");
    });

    it("on https, wss", () => {
        const location = globalThis.location;
        vi.stubGlobal("location", { protocol: "https:", host: "shop.example" });
        expect(new WebSocketTransport({ url: "/chat/ws" }).url).toBe(
            "wss://shop.example/chat/ws",
        );
        vi.stubGlobal("location", location);
        vi.unstubAllGlobals();
    });
});
