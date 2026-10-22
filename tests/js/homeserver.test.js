import { afterEach, describe, expect, it } from "vitest";
import { FakeHomeserver } from "../../src/django_chat_ui/static/django_chat_ui/homeserver.js";
import { ANA, flush, ME, says, setup, stopAll } from "./helpers.js";

afterEach(stopAll);

const C = "/_matrix/client/v3";

async function call(server, method, path, body, query = "") {
    const response = await server.fetch(`http://x${path}${query}`, {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { status: response.status, data: await response.json() };
}

describe("FakeHomeserver", () => {
    it("has a default user, and answers what it doesn't know", async () => {
        const server = new FakeHomeserver();
        expect(server.me.id).toBe("@me:demo");
        server.addRoom({ id: "!r" });
        expect((await call(server, "GET", `${C}/rooms/!x/state`)).status).toBe(
            403,
        );
        expect(
            (await call(server, "GET", `${C}/rooms/!r/state`)).data.errcode,
        ).toBe("M_UNRECOGNIZED");
        expect(
            (await call(server, "PUT", `${C}/rooms/!r/redact/$999/t`)).status,
        ).toBe(404);
        expect(
            (
                await call(
                    server,
                    "GET",
                    "/chat/_matrix/client/v3/account/whoami",
                )
            ).data,
        ).toEqual({ user_id: "@me:demo" });
    });

    it("refuses reactions where the room doesn't take them, and what it's told to", async () => {
        const server = new FakeHomeserver({ me: ME });
        server.addRoom({ id: "!r" });
        const reaction = {
            "m.relates_to": {
                rel_type: "m.annotation",
                event_id: "$1",
                key: "👍",
            },
        };
        expect(
            (
                await call(
                    server,
                    "PUT",
                    `${C}/rooms/!r/send/m.reaction/t1`,
                    reaction,
                )
            ).status,
        ).toBe(403);
        server.reject = ({ type }) =>
            type === "com.acme.x" ? { errcode: "M_FORBIDDEN" } : null;
        expect(
            (await call(server, "PUT", `${C}/rooms/!r/send/com.acme.x/t2`, {}))
                .status,
        ).toBe(400);
        expect(
            (await call(server, "PUT", `${C}/rooms/!r/send/com.acme.y/t3`, {}))
                .status,
        ).toBe(200);
    });

    it("pages back through a room, and syncs with or without a filter", async () => {
        const server = new FakeHomeserver({ me: ME });
        server.addRoom({ id: "!r" }, [{ sender: ME.id, content: says("a") }]);
        server.receipt("!r", ANA.id, "$1");
        const all = await call(
            server,
            "GET",
            `${C}/rooms/!r/messages`,
            undefined,
            "?dir=b",
        );
        expect(all.data.end).toBeUndefined();
        expect(all.data.chunk.at(0).content.body).toBe("a");
        const synced = await call(
            server,
            "GET",
            `${C}/sync`,
            undefined,
            "?filter=nope",
        );
        expect(Object.keys(synced.data.rooms.join)).toEqual(["!r"]);
        const [, receipts] = synced.data.rooms.join["!r"].ephemeral.events;
        expect(receipts.content).toEqual({
            $1: { "m.read": { [ANA.id]: { ts: 0 } } },
        });
        const later = await call(
            server,
            "GET",
            `${C}/sync`,
            undefined,
            `?since=${synced.data.next_batch}&timeout=1`,
        );
        expect(later.data.rooms.join).toEqual({});
    });

    it("takes requests as fetch does: a GET by default, bodies optional", async () => {
        const server = new FakeHomeserver({ me: ME });
        const who = await server.fetch(`http://x${C}/account/whoami`);
        expect(await who.json()).toEqual({ user_id: ME.id });
        const created = await call(server, "POST", `${C}/createRoom`, {});
        const room = server.rooms.get(created.data.room_id);
        expect([...room.members]).toEqual([ME.id]);
        // Messages and buttons without hooks: sent, nothing else.
        const menu = server.post(room.id, ME.id, says("Pick"));
        expect(
            (
                await call(
                    server,
                    "PUT",
                    `${C}/rooms/${room.id}/send/m.room.message/a`,
                    says("x"),
                )
            ).status,
        ).toBe(200);
        const action = {
            ...says("y"),
            "io.github.rodolvbg.chat.action": {
                event_id: menu.event_id,
                button: "b",
            },
        };
        expect(
            (
                await call(
                    server,
                    "PUT",
                    `${C}/rooms/${room.id}/send/m.room.message/b`,
                    action,
                )
            ).status,
        ).toBe(200);
        // With a hook: told.
        const seen = [];
        server.onMessage = (event) => seen.push(event.content.body);
        await call(
            server,
            "PUT",
            `${C}/rooms/${room.id}/send/m.room.message/c`,
            says("z"),
        );
        expect(seen).toEqual(["z"]);
    });

    it("starts rooms on the web by default, and leaves others' quietly", async () => {
        const { client, server } = await setup({
            rooms: [[{ id: "!r:demo", members: [ME.id, ANA.id] }, []]],
        });
        const room = await client.createRoom();
        await flush();
        expect(client.room(room).conversation.channel).toBe("web");
        server.leave("!r:demo", ANA.id); // Someone else: the client stays.
        await flush();
        expect(client.list().map((s) => s.id)).toContain("!r:demo");
        expect(client.room("!r:demo").participants.has(ANA.id)).toBe(false);
        // A button that isn't there: none.
        let pressed = "nothing";
        server.onAction = (_event, _server, button) => {
            pressed = button;
        };
        await client.action("!r:demo", "$none", { id: "x" });
        expect(pressed).toBe(undefined);
    });
});
