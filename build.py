#!/usr/bin/env python3
"""
80scartoons.info site builder.

Netlify runs this on every GitHub commit (see netlify.toml).
It reads cartoons.json and writes the finished website into the "public" folder:

    public/index.html                    <- your holding page (copied as-is from index.html)
    public/site.css                      <- shared styling
    public/cartoons/index.html           <- the A-Z browse page
    public/cartoons/<slug>/index.html    <- one page per cartoon
    public/sitemap.xml, public/robots.txt

You never edit this file to add a cartoon. Just edit cartoons.json.
Only Python's standard library is used, so nothing needs installing.
"""

import html
import json
import os
import re
import shutil
import sys
from datetime import date
from urllib.parse import quote_plus

# ───────────────────────── SETTINGS ─────────────────────────
SITE = {
    "name": "80sCartoons.info",
    "domain": "https://80scartoons.info",
    "cloudinary": "donmltebd",
    "amazon_tag": "80scartoons-21",
    "amazon_host": "www.amazon.co.uk",
    "logo_url": "https://res.cloudinary.com/donmltebd/image/upload/w_600,f_auto,q_auto/v1778169958/logo.png",
    "instagram": "https://www.instagram.com/80scartoons.info",
}

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "public")

GROUPS = [
    ("0–9", "#"),
    ("A – C", "ABC"),
    ("D – G", "DEFG"),
    ("H – N", "HIJKLMN"),
    ("O – S", "OPQRS"),
    ("T – Z", "TUVWXYZ"),
]

WATCH_LABELS = {
    "free": ("free", "FREE"),
    "stream": ("stream", "STREAM"),
    "buy": ("buy", "BUY"),
    "physical": ("physical", "PHYSICAL"),
}

warnings = []


def warn(msg):
    warnings.append(msg)


def fail(msg):
    print("\n❌ BUILD STOPPED\n" + msg + "\n")
    sys.exit(1)


def esc(s):
    return html.escape(str(s), quote=True)


# ───────────────────────── HELPERS ─────────────────────────
def img_url(public_id, w, h=None, crop="fill"):
    """Cloudinary URL for an image. Accepts a Cloudinary public id or a full https:// URL."""
    if not public_id:
        return ""
    if public_id.startswith("http"):
        return public_id
    t = "w_%d" % w
    if h:
        t += ",h_%d,c_%s" % (h, crop)
    t += ",q_auto,f_auto"
    return "https://res.cloudinary.com/%s/image/upload/%s/%s" % (SITE["cloudinary"], t, public_id)


def flag(cc):
    cc = (cc or "").strip().upper()
    if len(cc) == 2 and cc.isalpha():
        return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc)
    return ""


def has(v):
    return v not in (None, "", [], {})


def display_title(c):
    return c.get("short_title") or c["title"]


def sort_key(c):
    t = (c.get("sort_title") or c["title"]).strip()
    if t.lower().startswith("the ") and not c.get("sort_title"):
        t = t[4:]
    return t.lower()


def letter_of(c):
    ch = sort_key(c)[:1].upper()
    return ch if "A" <= ch <= "Z" else "#"


def letter_id(l):
    return "num" if l == "#" else l.lower()


def years(c):
    ys, ye = c.get("year_start"), c.get("year_end")
    if ys and ye and ye != ys:
        return "%s – %s" % (ys, ye)
    return str(ys) if ys else ""


def script_json(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


# ───────────────────────── LOAD + CHECK DATA ─────────────────────────
def load_cartoons():
    path = os.path.join(HERE, "cartoons.json")
    if not os.path.exists(path):
        fail("cartoons.json was not found.")
    text = open(path, encoding="utf-8").read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        lines = text.splitlines()
        bad = lines[e.lineno - 1] if 0 < e.lineno <= len(lines) else ""
        prev = lines[e.lineno - 2] if e.lineno >= 2 else ""
        fail(
            "cartoons.json has a typo near line %d, column %d.\n"
            "Problem: %s\n"
            "  line %d: %s\n  line %d: %s\n\n"
            "Common causes: a missing comma between items, an extra comma after the last item,\n"
            "or a missing \" quote mark. The typo is usually at the end of the line above."
            % (e.lineno, e.colno, e.msg, e.lineno - 1, prev.strip(), e.lineno, bad.strip())
        )
    if not isinstance(data, list):
        fail("cartoons.json must be a list of cartoons, starting with [ and ending with ].")

    slugs = set()
    for i, c in enumerate(data, 1):
        name = c.get("title") if isinstance(c, dict) else None
        if not name:
            fail("Cartoon number %d in cartoons.json has no \"title\"." % i)
        for field in ("slug", "country", "year_start", "overview"):
            if not has(c.get(field)):
                fail("\"%s\" is missing the required field \"%s\"." % (name, field))
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", c["slug"]):
            fail("\"%s\": the slug \"%s\" must be lowercase letters, numbers and hyphens only." % (name, c["slug"]))
        if c["slug"] in slugs:
            fail("Two cartoons share the slug \"%s\". Each slug must be unique." % c["slug"])
        slugs.add(c["slug"])
        if not isinstance(c["overview"], list):
            fail("\"%s\": \"overview\" must be a list of paragraphs in [ ] brackets." % name)
        yt = (c.get("theme_tune") or {}).get("youtube_id", "")
        if yt and not re.fullmatch(r"[A-Za-z0-9_-]{11}", yt):
            fail("\"%s\": the youtube_id \"%s\" doesn't look right. It should be the 11 characters after v= in the YouTube address." % (name, yt))

    for c in data:
        for s in c.get("similar", []):
            if isinstance(s, str) and s not in slugs:
                warn("%s: similar → \"%s\" is not a cartoon slug yet (it will be skipped)." % (c["title"], s))
        if not c.get("hero_image"):
            warn("%s: no hero_image yet (showing the emoji placeholder)." % c["title"])
    data.sort(key=sort_key)
    return data


# ───────────────────────── SHARED PAGE PARTS ─────────────────────────
NAV_JS = """
function closeAll(){
  document.querySelectorAll('.letter-dropdown').forEach(function(d){d.classList.remove('open');});
  document.querySelectorAll('.group-btn').forEach(function(b){b.classList.remove('active');});
}
document.querySelectorAll('.group-btn').forEach(function(btn){
  btn.addEventListener('click', function(e){
    e.stopPropagation();
    var dd = btn.nextElementSibling;
    var wasOpen = dd.classList.contains('open');
    closeAll();
    if(!wasOpen){ dd.classList.add('open'); btn.classList.add('active'); }
  });
});
document.addEventListener('click', closeAll);
"""

LIGHTBOX_HTML = """
<div class="lightbox" id="lightbox" onclick="closeLightboxOnBg(event)">
  <button class="lightbox-close" onclick="closeLightbox()" aria-label="Close">✕</button>
  <div class="lightbox-inner">
    <button class="lightbox-prev" onclick="prevImage()" aria-label="Previous">‹</button>
    <div class="lightbox-img-wrap" id="lightboxImgWrap"></div>
    <button class="lightbox-next" onclick="nextImage()" aria-label="Next">›</button>
    <div class="lightbox-caption" id="lightboxCaption"></div>
    <div class="lightbox-counter" id="lightboxCounter"></div>
  </div>
</div>
"""

LIGHTBOX_JS = """
var galleryImages = __GALLERY__;
var currentIndex = 0;
function openLightbox(i){ currentIndex = i; updateLightbox(); document.getElementById('lightbox').classList.add('open'); document.body.style.overflow='hidden'; }
function closeLightbox(){ document.getElementById('lightbox').classList.remove('open'); document.body.style.overflow=''; }
function closeLightboxOnBg(e){ if(e.target === document.getElementById('lightbox')) closeLightbox(); }
function nextImage(){ currentIndex = (currentIndex+1) % galleryImages.length; updateLightbox(); }
function prevImage(){ currentIndex = (currentIndex-1+galleryImages.length) % galleryImages.length; updateLightbox(); }
function updateLightbox(){
  var item = galleryImages[currentIndex];
  var wrap = document.getElementById('lightboxImgWrap');
  wrap.innerHTML = '';
  var img = document.createElement('img');
  img.src = item.src; img.alt = item.caption || '';
  wrap.appendChild(img);
  document.getElementById('lightboxCaption').textContent = item.caption || '';
  document.getElementById('lightboxCounter').textContent = (currentIndex+1) + ' / ' + galleryImages.length;
}
document.addEventListener('keydown', function(e){
  if(!document.getElementById('lightbox').classList.contains('open')) return;
  if(e.key === 'ArrowRight') nextImage();
  if(e.key === 'ArrowLeft') prevImage();
  if(e.key === 'Escape') closeLightbox();
});
"""


def nav_html(by_letter):
    parts = []
    for label, letters in GROUPS:
        present = [l for l in letters if l in by_letter]
        if not present:
            continue
        btns = "".join(
            '<a class="letter-btn" href="/cartoons/#letter-%s">%s <span class="count">%d</span></a>'
            % (letter_id(l), esc(l), len(by_letter[l]))
            for l in present
        )
        parts.append(
            '<div class="group-item"><button class="group-btn" type="button">%s <span class="arrow">▼</span></button>'
            '<div class="letter-dropdown">%s</div></div>' % (esc(label), btns)
        )
    return '<nav class="alpha-nav" aria-label="Browse cartoons A to Z">%s</nav>' % "".join(parts)


def header_html(crumbs, by_letter):
    crumb = '<a href="/">Home</a>'
    for label, href in crumbs:
        crumb += '<span class="sep">/</span>'
        crumb += '<a href="%s">%s</a>' % (href, esc(label)) if href else "<span>%s</span>" % esc(label)
    return (
        '<header class="site-header"><div class="header-top">'
        '<a class="logo" href="/"><span class="num">80s</span><span class="word">Cartoons</span><span class="tld">.info</span></a>'
        '<div class="breadcrumb">%s</div></div>%s</header>' % (crumb, nav_html(by_letter))
    )


def footer_html():
    return (
        '<footer><div class="footer-links"><a href="/">Home</a><a href="/cartoons/">A–Z of cartoons</a>'
        '<a href="%s" rel="noopener">Instagram</a></div>'
        "© %d <a href=\"/\">80sCartoons.info</a> — Est. 1998 — Built with nostalgia — All rights belong to their respective owners</footer>"
        % (SITE["instagram"], date.today().year)
    )


def page_html(title, description, path, body, og_image="", extra_head="", extra_js="", og_type="website"):
    canonical = SITE["domain"] + path
    og_image = og_image or SITE["logo_url"]
    return """<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>%(title)s</title>
<meta name="description" content="%(desc)s"/>
<link rel="canonical" href="%(canon)s"/>
<meta property="og:site_name" content="80sCartoons.info"/>
<meta property="og:type" content="%(og_type)s"/>
<meta property="og:title" content="%(title)s"/>
<meta property="og:description" content="%(desc)s"/>
<meta property="og:url" content="%(canon)s"/>
<meta property="og:image" content="%(og_image)s"/>
<meta name="twitter:card" content="summary_large_image"/>
<link rel="stylesheet" href="/site.css"/>
%(extra_head)s
</head>
<body>
%(body)s
<script>%(nav_js)s%(extra_js)s</script>
</body>
</html>
""" % {
        "title": esc(title),
        "desc": esc(description),
        "canon": esc(canonical),
        "og_type": og_type,
        "og_image": esc(og_image),
        "extra_head": extra_head,
        "body": body,
        "nav_js": NAV_JS,
        "extra_js": extra_js,
    }


# ───────────────────────── CARTOON PAGE SECTIONS ─────────────────────────
def section(title, inner):
    return (
        '<div class="content-section"><h2 class="section-title"><span class="section-dot"></span>%s</h2>%s</div>'
        % (title, inner)
    )


def hero_html(c):
    words = c["title"].split()
    if len(words) >= 2:
        h1 = '%s<span class="orange">%s</span>' % (esc(" ".join(words[:-1])), esc(words[-1]))
    else:
        h1 = esc(c["title"])
    pills = '<span class="flag-pill country">%s %s</span>' % (flag(c.get("country_code")), esc(c["country"]))
    if years(c):
        pills += '<span class="flag-pill year">%s</span>' % esc(years(c))
    if has(c.get("hero_image")):
        pic = '<img src="%s" alt="%s screenshot" width="760" height="570"/>' % (
            esc(img_url(c["hero_image"], 760, 570)), esc(c["title"]))
    else:
        pic = '<div class="hero-image-placeholder"><span class="hero-emoji">%s</span><span class="hero-img-label">Screenshot coming soon</span></div>' % esc(c.get("emoji", "📺"))
    tagline = '<p class="hero-tagline">%s</p>' % esc(c["tagline"]) if has(c.get("tagline")) else ""
    return (
        '<div class="hero"><div class="hero-inner"><div><div class="hero-flags">%s</div><h1>%s</h1>%s</div>'
        '<div class="hero-image-box">%s</div></div></div>' % (pills, h1, tagline, pic)
    )


def stats_html(c):
    items = [
        ("Country", c.get("country")),
        ("First Aired", c.get("first_aired") or c.get("year_start")),
        ("Series", c.get("series")),
        ("Episodes", c.get("episodes")),
        ("Studio", c.get("studio")),
    ]
    cells = "".join(
        '<div class="stat-item"><span class="stat-label">%s</span><span class="stat-value">%s</span></div>' % (l, esc(v))
        for l, v in items if has(v)
    )
    return '<div class="stats-band">%s</div>' % cells


def overview_html(c):
    paras = "".join("<p>%s</p>" % esc(p) for p in c["overview"])
    rows = [
        ("Country", c.get("country")),
        ("Network", c.get("network")),
        ("Studio", c.get("studio")),
        ("Created by", c.get("created_by")),
        ("First Aired", c.get("first_aired")),
        ("Last Aired", c.get("last_aired")),
        ("Series", c.get("series")),
        ("Episodes", c.get("episodes")),
        ("Runtime", c.get("runtime")),
        ("Voice Cast", c.get("voice_cast")),
    ]
    trs = "".join("<tr><td>%s</td><td>%s</td></tr>" % (l, esc(v)) for l, v in rows if has(v))
    table = '<table class="info-table">%s</table>' % trs if trs else ""
    return section("Overview", '<div class="overview">%s</div>%s' % (paras, table))


def characters_html(c):
    chars = c.get("characters") or []
    if not chars:
        return ""
    cards = ""
    for ch in chars:
        if has(ch.get("image")):
            pic = '<img class="char-img" src="%s" alt="%s" loading="lazy" width="320" height="240"/>' % (
                esc(img_url(ch["image"], 320, 240)), esc(ch["name"]))
        else:
            pic = '<div class="char-img-placeholder">%s</div>' % esc(ch.get("emoji", "❓"))
        cards += (
            '<div class="char-card">%s<div class="char-body"><div class="char-name">%s</div>'
            '<div class="char-role">%s</div><div class="char-desc">%s</div></div></div>'
            % (pic, esc(ch["name"]), esc(ch.get("role", "")), esc(ch.get("desc", "")))
        )
    return section("Main Characters", '<div class="characters-grid">%s</div>' % cards)


def gallery_html(c):
    items = [g for g in (c.get("gallery") or []) if has(g.get("image"))]
    if not items:
        return "", []
    thumbs = ""
    js = []
    for i, g in enumerate(items):
        cap = g.get("caption", "")
        thumbs += (
            '<div class="gallery-thumb" onclick="openLightbox(%d)"><img src="%s" alt="%s" loading="lazy" width="400" height="300"/></div>'
            % (i, esc(img_url(g["image"], 400, 300)), esc(cap))
        )
        js.append({"src": img_url(g["image"], 900), "caption": cap})
    inner = (
        '<div class="gallery-note">LOW-RES SCREENSHOTS · VHS-ERA CAPTURES · EDITORIAL REFERENCE USE</div>'
        '<div class="gallery-grid">%s</div>' % thumbs
    )
    return section("Image Gallery", inner), js


def theme_html(c):
    t = c.get("theme_tune") or {}
    name = t.get("title") or ("%s theme tune" % display_title(c))
    inner = ""
    yt = t.get("youtube_id")
    if yt:
        inner += (
            '<div class="yt-label"><span class="yt-badge">▶ YouTube</span> Watch the opening theme</div>'
            '<div class="yt-player"><iframe src="https://www.youtube.com/embed/%s?rel=0&amp;modestbranding=1" title="%s" '
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen loading="lazy"></iframe></div>'
            % (yt, esc(name))
        )
    q = quote_plus(name)
    inner += (
        '<div class="stream-links">'
        '<a class="stream-btn youtube" href="https://www.youtube.com/results?search_query=%s" target="_blank" rel="noopener">▶ Find it on YouTube</a>'
        '<a class="stream-btn spotify" href="https://open.spotify.com/search/%s" target="_blank" rel="noopener">🎧 Search Spotify</a></div>'
        % (q, quote_plus(name))
    )
    if has(t.get("lyrics")):
        inner += (
            '<div class="theme-wrap"><div class="theme-label">Lyrics</div><div class="theme-title">%s</div>'
            '<div class="lyrics">%s</div></div>' % (esc(name), esc(t["lyrics"]))
        )
    credit = t.get("credit") or ("Theme composed by %s." % t["composer"] if has(t.get("composer")) else "")
    if credit:
        inner += '<p class="theme-credit">%s</p>' % esc(credit)
    return section("Theme Tune", inner)


def watch_html(c):
    items = c.get("watch") or []
    if not items:
        return ""
    cards = ""
    for w in items:
        cls, label = WATCH_LABELS.get(w.get("type", "buy"), WATCH_LABELS["buy"])
        inner = (
            '<span class="watch-icon">%s</span><div><div class="watch-platform">%s</div><div class="watch-detail">%s</div></div>'
            '<span class="watch-type %s">%s</span>' % (esc(w.get("icon", "📺")), esc(w["platform"]), esc(w.get("detail", "")), cls, label)
        )
        if w.get("url"):
            rel = "noopener sponsored" if w.get("affiliate") else "noopener"
            cards += '<a class="watch-card" href="%s" target="_blank" rel="%s">%s</a>' % (esc(w["url"]), rel, inner)
        else:
            cards += '<div class="watch-card">%s</div>' % inner
    return section("Where to Watch", '<div class="watch-grid">%s</div>' % cards)


def amazon_link(term):
    return "https://%s/s?k=%s&tag=%s" % (SITE["amazon_host"], quote_plus(term), SITE["amazon_tag"])


def merch_items(c):
    if "merch" in c:
        return c["merch"]
    term = c.get("search_term") or display_title(c)
    return [
        {"retailer": "Amazon", "icon": "💿", "name": "DVDs & Box Sets", "desc": "Look for %s on DVD" % display_title(c),
         "cta": "Shop on Amazon →", "url": amazon_link(term + " DVD"), "affiliate": True},
        {"retailer": "Amazon", "icon": "🎁", "name": "Toys, Gifts & More", "desc": "Mugs, toys, books and keepsakes for fellow fans",
         "cta": "Browse on Amazon →", "url": amazon_link(term), "affiliate": True},
        {"retailer": "eBay", "icon": "🕹️", "name": "Vintage Collectables", "desc": "Original 80s merchandise and memorabilia",
         "cta": "Search on eBay →", "url": "https://www.ebay.co.uk/sch/i.html?_nkw=%s" % quote_plus(term + " vintage"), "affiliate": False},
    ]


BADGE_COLOURS = {"amazon": "#ff9900", "ebay": "#222222", "truffleshuffle": "#e8001c"}


def merch_html(c):
    items = merch_items(c)
    if not items:
        return ""
    cards = ""
    any_aff = False
    for m in items:
        aff = bool(m.get("affiliate"))
        any_aff = any_aff or aff
        colour = BADGE_COLOURS.get(m["retailer"].lower().replace(" ", ""), "#3d7d8f")
        rel = "noopener sponsored" if aff else "noopener"
        cards += (
            '<a class="merch-card" href="%s" target="_blank" rel="%s">'
            '<div class="merch-retailer-badge" style="background:%s;color:#fff">%s</div>'
            '<div class="merch-icon">%s</div><div class="merch-name">%s</div><div class="merch-desc">%s</div>'
            '<div class="merch-cta">%s</div></a>'
            % (esc(m["url"]), rel, colour, esc(m["retailer"]), esc(m.get("icon", "🛍️")), esc(m["name"]),
               esc(m.get("desc", "")), esc(m.get("cta", "Take a look →")))
        )
    disc = ('<p class="merch-disclaimer">🔗 Some links are affiliate links. If you buy something we may earn a small commission, at no extra cost to you.</p>'
            if any_aff else "")
    intro = '<div class="merch-intro">Love %s? Here are some ways to own a piece of the nostalgia.</div>' % esc(display_title(c))
    return section("Treat Yourself! 🛍️", '%s<div class="merch-grid">%s</div>%s' % (intro, cards, disc))


def sidebar_html(c, by_slug):
    boxes = ""
    if c.get("trivia"):
        lis = "".join("<li>%s</li>" % esc(t) for t in c["trivia"])
        boxes += '<div class="sidebar-box"><div class="sidebar-box-title">💡 Did You Know?</div><div class="sidebar-box-body"><ul class="trivia-list">%s</ul></div></div>' % lis
    sim = ""
    for s in c.get("similar") or []:
        if isinstance(s, str):
            o = by_slug.get(s)
            if o:
                sim += '<li><a href="/cartoons/%s/">%s <span>%s</span></a></li>' % (o["slug"], esc(display_title(o)), esc(o.get("year_start", "")))
        elif isinstance(s, dict) and s.get("title"):
            sim += '<li><div class="plain">%s <span>%s</span></div></li>' % (esc(s["title"]), esc(s.get("year", "")))
    if sim:
        boxes += '<div class="sidebar-box"><div class="sidebar-box-title">📺 If You Liked This...</div><div class="sidebar-box-body"><ul class="also-list">%s</ul></div></div>' % sim
    if c.get("tags"):
        pills = "".join('<span class="tag-pill">%s</span>' % esc(t) for t in c["tags"])
        boxes += '<div class="sidebar-box"><div class="sidebar-box-title">🏷️ Tags</div><div class="sidebar-box-body"><div class="tag-cloud">%s</div></div></div>' % pills
    return '<aside class="sidebar">%s</aside>' % boxes


def schema_json(c, url):
    data = {
        "@context": "https://schema.org",
        "@type": "TVSeries",
        "name": c["title"],
        "url": url,
        "description": " ".join(c["overview"])[:300],
        "startDate": str(c["year_start"]),
        "countryOfOrigin": c["country"],
    }
    if c.get("year_end"):
        data["endDate"] = str(c["year_end"])
    if c.get("studio"):
        data["productionCompany"] = {"@type": "Organization", "name": c["studio"]}
    if c.get("episodes"):
        data["numberOfEpisodes"] = c["episodes"]
    if c.get("series"):
        data["numberOfSeasons"] = c["series"]
    if c.get("hero_image"):
        data["image"] = img_url(c["hero_image"], 1200, 630)
    crumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE["domain"] + "/"},
            {"@type": "ListItem", "position": 2, "name": "Cartoons", "item": SITE["domain"] + "/cartoons/"},
            {"@type": "ListItem", "position": 3, "name": c["title"], "item": url},
        ],
    }
    return '<script type="application/ld+json">%s</script>\n<script type="application/ld+json">%s</script>' % (
        script_json(data), script_json(crumbs))


def meta_description(c):
    if has(c.get("meta_description")):
        return c["meta_description"]
    first = c["overview"][0]
    if len(first) > 155:
        first = first[:155].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return first


def build_cartoon(c, by_letter, by_slug):
    path = "/cartoons/%s/" % c["slug"]
    gal_html, gal_js = gallery_html(c)
    main = (
        overview_html(c) + characters_html(c) + gal_html + theme_html(c) + watch_html(c) + merch_html(c)
    )
    body = (
        header_html([("Cartoons", "/cartoons/"), (display_title(c), None)], by_letter)
        + hero_html(c) + stats_html(c)
        + '<div class="page-wrap"><div class="two-col"><main>%s</main>%s</div></div>' % (main, sidebar_html(c, by_slug))
        + (LIGHTBOX_HTML if gal_js else "")
        + footer_html()
    )
    og = img_url(c["hero_image"], 1200, 630) if has(c.get("hero_image")) else ""
    title = "%s (%s) — 80sCartoons.info" % (c["title"], years(c)) if years(c) else "%s — 80sCartoons.info" % c["title"]
    return page_html(
        title, meta_description(c), path, body, og_image=og,
        extra_head=schema_json(c, SITE["domain"] + path),
        extra_js=LIGHTBOX_JS.replace("__GALLERY__", script_json(gal_js)) if gal_js else "",
        og_type="video.tv_show",
    )


# ───────────────────────── BROWSE PAGE ─────────────────────────
def build_browse(cartoons, by_letter):
    all_letters = [l for _, ls in GROUPS for l in ls]
    pills = "".join(
        '<a href="#letter-%s"%s>%s</a>' % (letter_id(l), "" if l in by_letter else ' class="empty"', esc(l))
        for l in all_letters if l != "#" or "#" in by_letter
    )
    sections = ""
    for l in all_letters:
        if l not in by_letter:
            continue
        cards = ""
        for c in by_letter[l]:
            if has(c.get("hero_image")):
                thumb = '<img class="cartoon-thumb" src="%s" alt="%s" loading="lazy" width="400" height="300"/>' % (
                    esc(img_url(c["hero_image"], 400, 300)), esc(c["title"]))
            else:
                thumb = '<div class="cartoon-thumb-ph">%s</div>' % esc(c.get("emoji", "📺"))
            cards += (
                '<a class="cartoon-card" href="/cartoons/%s/">%s<div class="cartoon-card-body">'
                '<div class="cartoon-card-title">%s</div><div class="cartoon-card-meta">%s %s</div></div></a>'
                % (c["slug"], thumb, esc(display_title(c)), flag(c.get("country_code")), esc(years(c)))
            )
        sections += (
            '<div class="letter-section" id="letter-%s"><h2 class="section-title"><span class="section-dot"></span>%s</h2>'
            '<div class="cartoon-grid">%s</div></div>' % (letter_id(l), esc(l), cards)
        )
    n = len(cartoons)
    body = (
        header_html([("Cartoons", None)], by_letter)
        + '<div class="browse-hero"><h1>The A–Z of <span>80s Cartoons</span></h1><p>%d cartoon%s and counting. How many do you remember?</p></div>' % (n, "" if n == 1 else "s")
        + '<div class="page-wrap"><div class="az-pills">%s</div>%s<div style="height:60px"></div></div>' % (pills, sections)
        + footer_html()
    )
    return page_html(
        "A–Z of 80s Cartoons — 80sCartoons.info",
        "An A–Z encyclopedia of 80s cartoons, with a special love for the British and European ones. %d cartoons and counting." % n,
        "/cartoons/", body,
    )


# ───────────────────────── WRITE EVERYTHING ─────────────────────────
def write(path, text):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    cartoons = load_cartoons()
    by_slug = {c["slug"]: c for c in cartoons}
    by_letter = {}
    for c in cartoons:
        by_letter.setdefault(letter_of(c), []).append(c)

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    for name in ("index.html", "site.css"):
        src = os.path.join(HERE, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(OUT, name))
        elif name == "site.css":
            fail("site.css is missing from the repository.")
    static = os.path.join(HERE, "static")
    if os.path.isdir(static):
        shutil.copytree(static, OUT, dirs_exist_ok=True)

    for c in cartoons:
        write("cartoons/%s/index.html" % c["slug"], build_cartoon(c, by_letter, by_slug))
    write("cartoons/index.html", build_browse(cartoons, by_letter))

    today = date.today().isoformat()
    urls = [("/", None), ("/cartoons/", today)] + [("/cartoons/%s/" % c["slug"], today) for c in cartoons]
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for u, d in urls:
        sm += "  <url><loc>%s%s</loc>%s</url>\n" % (SITE["domain"], u, "<lastmod>%s</lastmod>" % d if d else "")
    sm += "</urlset>\n"
    write("sitemap.xml", sm)
    write("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % SITE["domain"])

    print("✅ Built %d cartoon pages + the A–Z page into /public" % len(cartoons))
    if warnings:
        print("\nHeads-up (nothing is broken, these are just to-dos):")
        for w in warnings:
            print("  • " + w)


if __name__ == "__main__":
    main()

