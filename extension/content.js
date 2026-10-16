// floating button on event pages: scroll the guest list until it stops
// growing, extract, post, report

(() => {
  if (document.getElementById("sf-events-btn")) return;

  const btn = document.createElement("button");
  btn.id = "sf-events-btn";
  btn.textContent = "guests → sf-events";
  Object.assign(btn.style, {
    position: "fixed", right: "16px", bottom: "16px", zIndex: 2147483647,
    padding: "10px 14px", borderRadius: "8px", border: "0", cursor: "pointer",
    background: "#d0401f", color: "#fff", font: "600 13px ui-monospace, monospace",
    boxShadow: "0 4px 14px rgba(0,0,0,.3)",
  });
  document.body.appendChild(btn);

  const say = (t, bg) => { btn.textContent = t; if (bg) btn.style.background = bg; };

  // the guest list on partiful lives in a scrollable modal, on luma in a
  // dialog. scroll whichever scrollable element currently holds the most
  // guests until the count stops changing
  async function loadAll() {
    let last = -1;
    for (let i = 0; i < 40; i++) {
      const found = window.sfEventsExtract.extract();
      if (found.length === last) break;
      last = found.length;
      say(`loading… ${last}`);
      const scroller = pickScroller();
      if (scroller) scroller.scrollTop = scroller.scrollHeight; else window.scrollTo(0, document.body.scrollHeight);
      await new Promise((r) => setTimeout(r, 600));
    }
    return window.sfEventsExtract.extract();
  }

  function pickScroller() {
    const dialog = document.querySelector('[role="dialog"]');
    const candidates = [...(dialog || document).querySelectorAll("*")].filter((el) => {
      const cs = getComputedStyle(el);
      return /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 40;
    });
    return candidates.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] || null;
  }

  // what the page says the list holds: luma "162 Guests", partiful "170 on the list"
  function expectedCount() {
    const t = document.body.innerText;
    const m = t.match(/(\d[\d,]*)\s+(?:on the list|Guests\b)/i);
    return m ? parseInt(m[1].replace(/,/g, ""), 10) : null;
  }

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const guests = await loadAll();
      if (!guests.length) { say("no guests visible, open the guest list first", "#7a3b2e"); return; }
      const expected = expectedCount();
      // a partial grab usually means the full modal is not open, send it anyway but say so
      const short = expected && guests.length < expected * 0.8;
      say(`sending ${guests.length}…`);
      const res = await chrome.runtime.sendMessage({ type: "guests", page_url: location.href, guests });
      if (res?.ok) {
        const c = res.body.counts || {};
        say(short
          ? `sent ${c.guests} of ${expected}. open the full guest list and click again to get the rest`
          : `sent ${c.guests} · ${c.founder || 0} founders · ${c.investor || 0} investors${res.body.known_event ? "" : " (event not in list yet)"}`, short ? "#9a6b1f" : "#1f8a4c");
      } else {
        say(`failed: ${res?.body?.detail || res?.status || "server off?"}`, "#7a3b2e");
      }
    } finally {
      btn.disabled = false;
    }
  });
})();
