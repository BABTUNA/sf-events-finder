// the content script cannot always reach localhost from a https page, the
// worker has host permission so it does the post
const SERVER = "http://127.0.0.1:8765";

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.type !== "guests") return;
  fetch(`${SERVER}/api/guests`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ page_url: msg.page_url, guests: msg.guests }),
  })
    .then(async (r) => reply({ ok: r.ok, status: r.status, body: await r.json().catch(() => ({})) }))
    .catch((e) => reply({ ok: false, status: 0, body: { detail: String(e) } }));
  // keep the channel open for the async reply
  return true;
});
