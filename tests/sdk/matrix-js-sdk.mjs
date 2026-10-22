/**
 * The Matrix project's own client, matrix-js-sdk, against a django-chat-ui
 * homeserver: it logs in, syncs, reads a room and writes to it. Prints what
 * it saw, as JSON. Run by tests/e2e/test_matrix_sdk.py:
 *
 *   node tests/sdk/matrix-js-sdk.mjs <baseUrl> <user> <password> <text>
 */
import * as sdk from "matrix-js-sdk";
import { logger } from "matrix-js-sdk/lib/logger.js";

logger.setLevel(process.env.SDK_LOG ?? "silent");

const [baseUrl, user, password, text] = process.argv.slice(2);

const login = sdk.createClient({ baseUrl });
const { access_token, user_id, device_id } = await login.login(
    "m.login.password",
    { identifier: { type: "m.id.user", user }, password },
);

const client = sdk.createClient({
    baseUrl,
    accessToken: access_token,
    userId: user_id,
    deviceId: device_id,
    timelineSupport: true,
});

const prepared = new Promise((resolve, reject) => {
    client.on(sdk.ClientEvent.Sync, (state) => {
        if (state === "PREPARED") resolve();
        if (state === "ERROR") reject(new Error("sync failed"));
    });
});
await client.startClient({ initialSyncLimit: 20, lazyLoadMembers: false });
await prepared;

const [room] = client.getRooms();
const before = room
    .getLiveTimeline()
    .getEvents()
    .filter((event) => event.getType() === "m.room.message")
    .map((event) => event.getContent().body);

const sent = await client.sendTextMessage(room.roomId, text);
// Its own message comes back from /sync: the local echo is the server's.
let echo = null;
for (let tries = 0; tries < 100 && !echo; tries += 1) {
    const found = room
        .getLiveTimeline()
        .getEvents()
        .find((event) => event.getId() === sent.event_id);
    if (found && found.status === null) echo = found.getId();
    else await new Promise((resolve) => setTimeout(resolve, 100));
}
const last = room
    .getLiveTimeline()
    .getEvents()
    .filter((event) => event.getType() === "m.room.message")
    .at(-2);
await client.sendEvent(room.roomId, "m.reaction", {
    "m.relates_to": {
        rel_type: "m.annotation",
        event_id: last.getId(),
        key: "👍",
    },
});
await client.sendReadReceipt(last);
await client.sendTyping(room.roomId, true, 3000);

console.log(
    JSON.stringify({
        user_id,
        rooms: client.getRooms().length,
        name: room.name,
        members: room
            .getJoinedMembers()
            .map((m) => m.name)
            .sort(),
        capabilities: room.currentState
            .getStateEvents("io.github.rodolvbg.chat.capabilities", "")
            ?.getContent(),
        before,
        sent: sent.event_id,
        echo,
    }),
);
client.stopClient();
process.exit(0);
