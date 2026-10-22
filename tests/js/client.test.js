import { afterEach, describe, expect, it, vi } from "vitest";
import {
    ChatClient,
    MatrixError,
} from "../../src/django_chat_ui/static/django_chat_ui/client.js";
import {
    ACTION,
    CONVERSATION,
} from "../../src/django_chat_ui/static/django_chat_ui/matrix.js";
import { ANA, BOT, flush, ME, says, setup, stopAll } from "./helpers.js";

afterEach(() => {
    stopAll();
    vi.useRealTimers();
});

const ROOM = {
    id: "!wa:demo",
    members: [ME.id, ANA.id],
    capabilities: { reactions: true },
};

/** A fetch answering `answers` in order (status, data), recording calls;
 * then, never (as a long poll with nothing to say). */
function fetcher(...answers) {
    const calls = [];
    const fetch = vi.fn(async (url, init) => {
        calls.push({ url, ...init });
        if (!answers.length) return new Promise(() => {});
        const [status, data] = answers.shift();
        return {
            ok: status < 400,
            status,
            json: async () => {
                if (data instanceof Error) throw data;
                return data;
            },
        };
    });
    fetch.calls = calls;
    return fetch;
}

describe("ChatClient requests", () => {
    it("speaks to a homeserver: its paths, token, CSRF and errors", async () => {
        const fetch = fetcher(
            [200, { ok: 1 }],
            [403, { errcode: "M_FORBIDDEN", error: "No." }],
            [500, new Error("not JSON")],
            [200, {}],
        );
        const client = new ChatClient({
            baseUrl: "/chat/",
            accessToken: "tok",
            csrfToken: "csrf",
            fetch,
        });
        expect(
            await client.request("GET", "/x", { query: { a: "1" } }),
        ).toEqual({ ok: 1 });
        const [get] = fetch.calls;
        expect(get.url).toBe("/chat/_matrix/client/v3/x?a=1");
        expect(get.headers.Authorization).toBe("Bearer tok");
        expect(get.headers["X-CSRFToken"]).toBeUndefined();
        expect(get.credentials).toBe("same-origin");

        const error = await client
            .request("PUT", "/y", { body: { b: 2 } })
            .catch((e) => e);
        expect(error).toBeInstanceOf(MatrixError);
        expect([error.errcode, error.status, error.message]).toEqual([
            "M_FORBIDDEN",
            403,
            "No.",
        ]);
        expect(fetch.calls[1].headers["X-CSRFToken"]).toBe("csrf");
        expect(fetch.calls[1].body).toBe('{"b":2}');

        const broken = await client.request("GET", "/z").catch((e) => e);
        expect([broken.errcode, broken.message]).toEqual([
            "M_UNKNOWN",
            "HTTP 500",
        ]);

        const file = new Blob(["x"]);
        await client.request("POST", "/_matrix/media/v3/upload", { raw: file });
        expect(fetch.calls[3].url).toBe("/chat/_matrix/media/v3/upload");
        expect(fetch.calls[3].headers["Content-Type"]).toBe(
            "application/octet-stream",
        );
        expect(fetch.calls[3].body).toBe(file);
        expect(new MatrixError().message).toBe("HTTP 0");
        expect(new MatrixError({ errcode: "M_X" }).message).toBe("M_X");
    });

    it("uses the page's fetch by default", () => {
        const client = new ChatClient();
        expect(typeof client.fetch).toBe("function");
        expect(client.baseUrl).toBe("");
    });
});

describe("ChatClient sync", () => {
    it("starts: who it is, then its rooms, once", async () => {
        const { client, server } = await setup({
            rooms: [[ROOM, [{ sender: ANA.id, content: says("Hi") }]]],
        });
        expect(client.me).toBe(ME.id);
        expect(client.start()).toBe(client.ready);
        expect(client.list().map((store) => store.id)).toEqual(["!wa:demo"]);
        expect(client.room("!wa:demo").messages[0].content.body).toBe("Hi");
        // What comes next arrives through the long poll.
        server.post("!wa:demo", ANA.id, says("Are you there?"));
        await flush();
        expect(client.room("!wa:demo").messages.at(-1).content.body).toBe(
            "Are you there?",
        );
        expect(client.room("!wa:demo").unread).toBe(1);
    });

    it("tells when the rooms change, and when it leaves one", async () => {
        const { client, server } = await setup({ rooms: [[ROOM, []]] });
        const listed = vi.fn();
        client.addEventListener("conversations", listed);
        server.leave("!wa:demo", ME.id);
        await flush();
        expect(listed).toHaveBeenCalled();
        expect(client.list()).toEqual([]);
        expect(client.room("!wa:demo").left).toBe(true);
        // A room it never had, left: nothing to do.
        client.applySync({ next_batch: "s9", rooms: { leave: { "!x": {} } } });
        expect(client.rooms.has("!x")).toBe(false);
    });

    it("lists the latest active first", async () => {
        const { client } = await setup({
            rooms: [
                [
                    { id: "!a:demo" },
                    [{ sender: ANA.id, content: says("old"), ts: 1 }],
                ],
                [
                    { id: "!b:demo" },
                    [{ sender: ANA.id, content: says("new"), ts: 5 }],
                ],
                [{ id: "!c:demo" }, []],
            ],
        });
        expect(client.list().map((s) => s.id)).toEqual([
            "!c:demo",
            "!b:demo",
            "!a:demo",
        ]);
        // Without messages nor this package's state: last.
        const empty = new ChatClient();
        empty.room("!y").joined = true;
        empty.room("!z").joined = true;
        expect(empty.list().map((s) => s.id)).toEqual(["!y", "!z"]);
    });

    it("can't start without a homeserver, and tries again later", async () => {
        const fetch = fetcher([401, { errcode: "M_MISSING_TOKEN" }]);
        const client = new ChatClient({ fetch });
        await expect(client.start()).rejects.toThrow(MatrixError);
        expect(client.ready).toBe(null);
        expect(client.running).toBe(false);
    });

    it("retries a sync that fails, and stops", async () => {
        const fetch = fetcher(
            [200, { user_id: "@me:x" }],
            [200, { next_batch: "s1" }],
            [500, {}],
            [200, { next_batch: "s2", rooms: { join: { "!r": {} } } }],
        );
        const client = new ChatClient({ fetch, retry: 1, timeout: 7 });
        await client.start();
        await flush();
        await new Promise((resolve) => setTimeout(resolve, 10));
        expect(client.since).not.toBe("s1");
        const urls = fetch.calls.map((c) => c.url);
        expect(urls[2]).toContain("since=s1");
        expect(urls[2]).toContain("timeout=7");
        client.stop();
        expect(client.ready).toBe(null);
        const calls = fetch.calls.length;
        await new Promise((resolve) => setTimeout(resolve, 10));
        expect(fetch.calls.length).toBeLessThanOrEqual(calls + 1);
    });

    it("polls instead, every `poll` milliseconds", async () => {
        const { client, server } = await setup({
            rooms: [[ROOM, []]],
            options: { poll: 5 },
        });
        server.post("!wa:demo", ANA.id, says("Hi"));
        await new Promise((resolve) => setTimeout(resolve, 30));
        await flush();
        expect(client.room("!wa:demo").messages[0].content.body).toBe("Hi");
        const polls = server.received.filter((r) => r.path.endsWith("/sync"));
        expect(polls.every((r) => r.query.get("timeout") === "0")).toBe(true);
    });

    it("stops quietly while a sync fails", async () => {
        const fetch = fetcher(
            [200, { user_id: "@me:x" }],
            [200, { next_batch: "s1" }],
            [500, {}],
        );
        const client = new ChatClient({ fetch, retry: 50 });
        await client.start();
        client.running = false;
        await flush();
        expect(fetch.calls.length).toBe(3);
    });
});

describe("ChatClient commands", () => {
    it("sends with a local echo, then the server's", async () => {
        const { client, server } = await setup({ rooms: [[ROOM, []]] });
        const store = client.room("!wa:demo");
        const sending = client.send("!wa:demo", says("Hi"));
        expect(store.messages[0]).toMatchObject({ status: "sending" });
        expect(store.messages[0].id).toBe(`~${store.messages[0].txnId}`);
        const id = await sending;
        await flush();
        expect(store.messages.map((m) => [m.id, m.status])).toEqual([
            [id, "sent"],
        ]);
        const [put] = server.received.filter((r) => r.method === "PUT");
        expect(put.path).toMatch(
            /\/rooms\/!wa:demo\/send\/m\.room\.message\/t/,
        );
    });

    it("marks what fails, and sends it again, once", async () => {
        const { client, server } = await setup({ rooms: [[ROOM, []]] });
        server.reject = () => ({ errcode: "M_FORBIDDEN", error: "No." });
        const store = client.room("!wa:demo");
        await expect(
            client.send("!wa:demo", says("Hi"), { txnId: "tx" }),
        ).rejects.toThrow("No.");
        expect(store.messages[0]).toMatchObject({ status: "failed" });
        expect(store.messages[0].error.errcode).toBe("M_FORBIDDEN");
        server.reject = null;
        await client.retry("!wa:demo", "tx");
        await flush();
        expect(store.messages.map((m) => m.status)).toEqual(["sent"]);
        await expect(client.retry("!wa:demo", "nope")).rejects.toThrow(
            MatrixError,
        );
        // The same transaction again: the same event.
        const again = await client.send("!wa:demo", says("Hi"), {
            txnId: "tx",
        });
        expect(again).toBe(store.messages[0].id);
    });

    it("uses buttons, reacts, takes reactions back, redacts", async () => {
        const { client, server } = await setup({
            rooms: [[ROOM, [{ sender: ANA.id, content: says("Hi") }]]],
        });
        const store = client.room("!wa:demo");
        const hi = store.messages[0].id;
        await client.action("!wa:demo", hi, { id: "y", label: "Yes" });
        await client.action("!wa:demo", hi, { id: "n" });
        const answers = server.received.filter((r) => r.body?.[ACTION]);
        expect(answers.map((r) => r.body.body)).toEqual(["Yes", "n"]);
        expect(answers[0].body["m.relates_to"]).toEqual({
            "m.in_reply_to": { event_id: hi },
        });

        await client.react("!wa:demo", hi, "👍");
        await flush();
        expect(store.messages[0].reactions).toMatchObject([
            { key: "👍", by: [ME.id] },
        ]);
        await client.unreact("!wa:demo", hi, "👍");
        await client.unreact("!wa:demo", "$none", "👍");
        await flush();
        expect(store.messages[0].reactions).toEqual([]);

        await client.redact("!wa:demo", hi, "spam");
        await flush();
        expect(store.messages[0].redacted).toBe(true);
        const redactions = server.received.filter((r) =>
            r.path.includes("/redact/"),
        );
        expect(redactions.at(-1).body).toEqual({ reason: "spam" });
        expect(redactions[0].body).toEqual({});
    });

    it("reads, types, starts rooms, uploads", async () => {
        const { client, server } = await setup({
            rooms: [[ROOM, [{ sender: ANA.id, content: says("Hi") }]]],
        });
        const hi = client.room("!wa:demo").messages[0].id;
        await client.read("!wa:demo", hi);
        await client.typing("!wa:demo", true);
        await client.typing("!wa:demo", false);
        const typing = server.received.filter((r) =>
            r.path.includes("/typing/"),
        );
        expect(typing.map((r) => r.body)).toEqual([
            { typing: true, timeout: 30000 },
            { typing: false },
        ]);
        expect(typing[0].path).toContain(`/typing/${ME.id}`);
        await flush();
        expect(client.room("!wa:demo").unread).toBe(0);

        const room = await client.createRoom({
            invite: [BOT.id],
            channel: "web",
        });
        await flush();
        expect(client.room(room).conversation.channel).toBe("web");
        const created = server.received.find((r) =>
            r.path.endsWith("/createRoom"),
        );
        expect(created.body).toEqual({
            invite: [BOT.id],
            preset: "private_chat",
            initial_state: [
                {
                    type: CONVERSATION,
                    state_key: "",
                    content: { channel: "web" },
                },
            ],
        });
        await client.createRoom();
        expect(server.received.at(-1).body.initial_state).toEqual([]);

        const uri = await client.upload(
            new File(["x"], "a.png", { type: "image/png" }),
        );
        expect(uri).toMatch(/^mxc:\/\/demo\//);
        const upload = server.received.find((r) => r.path.endsWith("/upload"));
        expect(upload.query.get("filename")).toBe("a.png");
        await client.upload(new Blob(["x"]));
        expect(server.received.at(-1).query.get("filename")).toBe("file");
    });

    it("fetches older messages", async () => {
        const history = Array.from({ length: 8 }, (_, n) => ({
            sender: ANA.id,
            content: says(String(n)),
        }));
        const { client } = await setup({
            rooms: [[ROOM, history]],
            options: { limit: 3 },
        });
        const store = client.room("!wa:demo");
        expect(store.messages.map((m) => m.content.body)).toEqual([
            "5",
            "6",
            "7",
        ]);
        await client.history("!wa:demo", 3);
        expect(store.messages.map((m) => m.content.body)).toEqual([
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
        ]);
        while (store.more) await client.history("!wa:demo", 30);
        expect(store.messages).toHaveLength(8);
        await client.history("!wa:demo"); // Nothing older: nothing asked.
    });

    it("waits for its start, or starts", async () => {
        const { client, server } = await setup({ rooms: [[ROOM, []]] });
        client.stop();
        // Stopped: a command starts it again (who it is, first).
        const before = server.received.length;
        await client.send("!wa:demo", says("Hi"));
        const paths = server.received.slice(before).map((r) => r.path);
        expect(paths[0]).toContain("/account/whoami");
        expect(paths.at(-1)).toContain("/send/");
    });

    it("gives the URL of an mxc:// URI", () => {
        const client = new ChatClient({ baseUrl: "/chat" });
        expect(client.mediaUrl("mxc://demo/abc_1")).toBe(
            "/chat/_matrix/client/v1/media/download/demo/abc_1",
        );
        expect(client.mediaUrl("https://x/y.png")).toBe("https://x/y.png");
        expect(client.mediaUrl(undefined)).toBe(undefined);
    });
});
