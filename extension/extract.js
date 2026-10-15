// pulls {name, bio, links} per guest out of the page. pure dom reading, no
// network, so it can be loaded on its own and run against saved html

window.sfEventsExtract = (() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();

  // partiful: every guest card has an avatar (a profile image or a default
  // avatar with initials), climbing three levels lands on the card, which
  // holds the name span, an optional bio span and the social links
  function partiful(root = document) {
    const avatars = root.querySelectorAll('img[src*="partiful.imgix.net/profileImages"], img[src*="assets.partiful.com/avatar/"]');
    const out = [];
    const seen = new Set();
    for (const img of avatars) {
      const card = img.parentElement?.parentElement?.parentElement;
      if (!card) continue;
      const info = img.parentElement.nextElementSibling;
      const spans = info ? [...info.querySelectorAll("span")].map((s) => clean(s.textContent)).filter(Boolean) : [];
      const name = clean(img.getAttribute("alt")) || spans[0] || "";
      if (!name || /^and \d+ more$/i.test(name)) continue;
      const bio = spans.find((t) => t !== name) || "";
      const links = [...card.querySelectorAll("a[href]")].map((a) => a.href).filter((h) => !h.includes("partiful.com"));
      const key = `${name}|${bio}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ name, bio, links });
    }
    return out;
  }

  // luma: the guest dialog lists rows that link to /user/... profiles. the
  // row's first text is the name, anything after it is the subtitle. best
  // effort until checked against a logged in page
  function luma(root = document) {
    const scope = root.querySelector('[role="dialog"]') || root;
    const rows = scope.querySelectorAll('a[href^="/user/"], a[href*="luma.com/user/"], a[href*="lu.ma/user/"]');
    const out = [];
    const seen = new Set();
    for (const a of rows) {
      const texts = [...a.querySelectorAll("div, span")].map((n) => clean(n.textContent)).filter(Boolean);
      const name = texts[0] || clean(a.textContent);
      if (!name) continue;
      const bio = texts.find((t) => t !== name && !t.startsWith(name)) || "";
      const profile = a.href;
      if (seen.has(profile)) continue;
      seen.add(profile);
      out.push({ name, bio, links: [profile] });
    }
    return out;
  }

  function extract(root = document, host = location.hostname) {
    return /partiful\.com$/.test(host) ? partiful(root) : luma(root);
  }

  return { extract, partiful, luma };
})();
