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

  // luma: the guest modal lists rows of <a href="/user/..."> with the name in
  // the avatar alt ("Profile picture for NAME") and a sibling block of social
  // links. no bios here, the server fills those from luma's public profile api
  function luma(root = document) {
    const scope = root.querySelector(".lux-modal-body") || root.querySelector('[role="dialog"]') || root;
    const rows = scope.querySelectorAll('a[href^="/user/"], a[href*="luma.com/user/"], a[href*="lu.ma/user/"]');
    const out = [];
    const seen = new Set();
    for (const a of rows) {
      const img = a.querySelector("img[alt]");
      const alt = clean(img?.getAttribute("alt")).replace(/^profile picture for\s+/i, "");
      const name = alt || clean(a.querySelector(".name")?.textContent) || clean(a.textContent);
      if (!name) continue;
      const profile = new URL(a.getAttribute("href"), "https://luma.com/").href;
      if (seen.has(profile)) continue;
      seen.add(profile);
      const socials = [...(a.parentElement?.querySelectorAll('a[href^="http"]') || [])]
        .map((x) => x.href)
        .filter((h) => !/luma\.com|lu\.ma/.test(h));
      out.push({ name, bio: "", links: [profile, ...socials] });
    }
    return out;
  }

  function extract(root = document, host = location.hostname) {
    return /partiful\.com$/.test(host) ? partiful(root) : luma(root);
  }

  return { extract, partiful, luma };
})();
