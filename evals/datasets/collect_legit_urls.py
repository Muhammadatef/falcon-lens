"""Collect and verify the legitimate-URL eval set (docs/EVALS.md: legit URLs).

Usage (run from repo root):
  uv run --no-project --with httpx --with tldextract --with pyyaml \
      python evals/datasets/collect_legit_urls.py run

Each candidate gets ONE plain GET (honest UA, <=1 req/s, redirects followed, no forms,
no JS). Only 2xx final responses are kept; for official rows the final host must also
stay inside the brand's verified_domains. The per-row status log goes to
data/private/legit_url_checks.jsonl (gitignored). The published CSV carries only rows
that passed.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import httpx
import tldextract
import yaml

ROOT = Path(__file__).resolve().parents[2]
UA = "FalconLens-research/0.1"
COLLECTED = "2026-11-22"
TRANCO_ID = "46YLX"
PSL = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

OFFICIAL_PATHS: dict[str, list[str]] = {
    "abu_dhabi_police": ["https://www.adpolice.gov.ae/", "https://www.adpolice.gov.ae/en/", "https://www.adpolice.gov.ae/ar/"],
    "dubai_police": ["https://www.dubaipolice.gov.ae/", "https://www.dubaipolice.gov.ae/wps/portal/home/", "https://www.dubaipolice.gov.ae/wps/portal/home/services"],
    "moi_uae": ["https://www.moi.gov.ae/", "https://www.moi.gov.ae/en/", "https://www.moi.gov.ae/ar/"],
    "uae_pass": ["https://www.uaepass.ae/", "https://www.uaepass.ae/faq", "https://selfcare.uaepass.ae/"],
    "tamm_abu_dhabi": ["https://www.tamm.abudhabi/", "https://www.tamm.abudhabi/en", "https://www.tamm.abudhabi/ar", "https://www.tamm.abudhabi/en/life-events"],
    "icp_uae": ["https://icp.gov.ae/", "https://icp.gov.ae/en/", "https://icp.gov.ae/ar/", "https://smartservices.icp.gov.ae/"],
    "emirates_post": ["https://www.emiratespost.ae/", "https://www.emiratespost.ae/track-and-trace", "https://www.emiratespost.ae/en", "https://www.epg.ae/"],
    "salik": ["https://www.salik.ae/", "https://www.salik.ae/en", "https://www.salik.ae/ar"],
    "rta_dubai": ["https://www.rta.ae/", "https://www.rta.ae/wps/portal/rta/ae/home", "https://www.nol.ae/", "https://www.rta.ae/wps/portal/rta/ae/public-transport"],
    "itc_abu_dhabi_darb": ["https://admobility.gov.ae/", "https://admobility.gov.ae/en", "https://itc.gov.ae/"],
    "addc_taqa_distribution": ["https://www.addc.ae/", "https://www.taqadistribution.com/"],
    "dewa": ["https://www.dewa.gov.ae/", "https://www.dewa.gov.ae/en/", "https://www.dewa.gov.ae/en/customer", "https://www.dewa.gov.ae/ar/"],
    "sewa": ["https://www.sewa.gov.ae/", "https://www.sewa.gov.ae/en/", "https://www.sewa.gov.ae/ar/"],
    "etisalat_by_eand": ["https://www.etisalat.ae/", "https://www.etisalat.ae/en/c/personal.html", "https://www.eand.com/", "https://www.eand.com/en/home.html", "https://www.eand.ae/"],
    "du": ["https://www.du.ae/", "https://www.du.ae/personal", "https://www.du.ae/business", "https://www.du.ae/ar/personal"],
    "cbuae": ["https://www.centralbank.ae/", "https://www.centralbank.ae/en/", "https://www.centralbank.ae/ar/", "https://www.centralbank.ae/en/consumer-protection/"],
    "fab": ["https://www.bankfab.com/", "https://www.bankfab.com/en-ae/personal", "https://www.bankfab.com/ar-ae/personal", "https://www.bankfab.com/en-ae/personal/ways-to-bank/digital-banking"],
    "adcb": ["https://www.adcb.com/", "https://www.adcb.com/en/personal/", "https://www.adcb.com/en/personal/ways-to-bank/", "https://www.adcb.com/ar/"],
    "emirates_nbd": ["https://www.emiratesnbd.com/", "https://www.emiratesnbd.com/en", "https://www.emiratesnbd.com/ar-ae", "https://www.emiratesnbd.com/en/ways-to-bank/online-banking"],
    "dib": ["https://www.dib.ae/", "https://www.dib.ae/personal", "https://www.dib.ae/ar", "https://www.dib.ae/personal/ways-to-bank"],
    "mashreq": ["https://www.mashreq.com/", "https://www.mashreq.com/en/uae/neo/", "https://www.mashreq.com/en/uae/neo/personal", "https://www.mashreq.com/ar/uae/neo/"],
    "adib": ["https://www.adib.ae/", "https://www.adib.ae/en/Pages/default.aspx", "https://www.adib.ae/ar/Pages/default.aspx", "https://www.adib.com/"],
    "rakbank": ["https://www.rakbank.ae/", "https://www.rakbank.ae/wps/portal/retail-banking/home", "https://www.rakbank.ae/en/", "https://www.rakbank.ae/ar/"],
    "emirates_islamic": ["https://www.emiratesislamic.ae/", "https://www.emiratesislamic.ae/en", "https://www.emiratesislamic.ae/ar"],
}
GOV_BRANDS = {"abu_dhabi_police", "dubai_police", "moi_uae", "uae_pass", "tamm_abu_dhabi", "icp_uae", "emirates_post",
              "salik", "rta_dubai", "itc_abu_dhabi_darb", "addc_taqa_distribution", "dewa", "sewa", "etisalat_by_eand",
              "du", "cbuae"}
# Official login / payment / service pages (also hard negatives); brand_id filled.
OFFICIAL_HARD = [
    ("https://www.dewa.gov.ae/en/customer/services/pay-your-bill", "hard_negative_payment", "dewa"),
    ("https://www.salik.ae/en/recharge", "hard_negative_payment", "salik"),
    ("https://www.etisalat.ae/en/c/pay-bill.html", "hard_negative_payment", "etisalat_by_eand"),
    ("https://www.du.ae/personal/pay-bill", "hard_negative_payment", "du"),
    ("https://www.emiratespost.ae/en/sendmoney", "hard_negative_payment", "emirates_post"),
    ("https://www.adcb.com/en/personal/ways-to-bank/online-banking/", "hard_negative_login", "adcb"),
    ("https://www.emiratesnbd.com/en/ways-to-bank/mobile-banking", "hard_negative_login", "emirates_nbd"),
    ("https://www.bankfab.com/en-ae/personal/ways-to-bank/digital-banking/online-banking", "hard_negative_login", "fab"),
    ("https://www.mashreq.com/en/uae/neo/ways-to-bank/", "hard_negative_login", "mashreq"),
    ("https://www.dib.ae/personal/ways-to-bank/online-banking", "hard_negative_login", "dib"),
    ("https://www.rakbank.ae/en/personal/ways-to-bank/", "hard_negative_login", "rakbank"),
    ("https://onlinebanking.emiratesnbd.com/", "hard_negative_login", "emirates_nbd"),
    ("https://www.uaepass.ae/login", "hard_negative_login", "uae_pass"),
    ("https://smartservices.icp.gov.ae/echannels/web/client/guest/index.html", "hard_negative_login", "icp_uae"),
    ("https://www.tamm.abudhabi/en/aspects-of-life", "hard_negative_login", "tamm_abu_dhabi"),
    ("https://www.dubaipolice.gov.ae/wps/portal/home/services/individualservices/paytrafficfines", "hard_negative_payment", "dubai_police"),
    ("https://www.adpolice.gov.ae/en/services", "hard_negative_payment", "abu_dhabi_police"),
    ("https://www.rta.ae/wps/portal/rta/ae/home/fines", "hard_negative_payment", "rta_dubai"),
    ("https://www.eand.com/en/personal/pay-bill.html", "hard_negative_payment", "etisalat_by_eand"),
]

# Tranco list TRANCO_ID (top-1m); user-facing sites picked by hand (CDN/infra domains excluded).
POPULAR = ["google.com", "facebook.com", "microsoft.com", "youtube.com", "apple.com", "instagram.com", "linkedin.com", "amazon.com", "wikipedia.org", "netflix.com", "github.com", "yahoo.com", "bing.com", "reddit.com", "x.com", "whatsapp.com", "zoom.us", "adobe.com", "wordpress.org", "wordpress.com", "paypal.com", "ebay.com", "cloudflare.com", "mozilla.org", "spotify.com", "tiktok.com", "pinterest.com", "tumblr.com", "medium.com", "dropbox.com", "salesforce.com", "oracle.com", "ibm.com", "intel.com", "nvidia.com", "bbc.com", "cnn.com", "nytimes.com", "theguardian.com", "reuters.com", "bloomberg.com", "aljazeera.com", "aljazeera.net", "khaleejtimes.com", "gulfnews.com", "thenationalnews.com", "arabianbusiness.com", "emirates.com", "etihad.com", "flydubai.com", "airarabia.com", "noon.com", "talabat.com", "careem.com", "dubizzle.com", "bayut.com", "propertyfinder.ae", "carrefouruae.com", "lulu.com", "namshi.com", "sharafdg.com", "amazon.ae", "amazon.sa", "python.org", "nodejs.org", "stackoverflow.com", "gitlab.com", "slack.com", "atlassian.com", "notion.so", "canva.com", "figma.com", "openai.com", "anthropic.com", "duckduckgo.com", "twitch.tv", "discord.com", "telegram.org", "signal.org", "skype.com", "office.com", "live.com", "outlook.com", "icloud.com", "booking.com", "airbnb.com", "tripadvisor.com", "expedia.com", "uber.com", "aliexpress.com", "alibaba.com", "temu.com", "shein.com", "walmart.com", "target.com", "bestbuy.com", "ikea.com", "nike.com", "adidas.com", "samsung.com", "sony.com", "hp.com", "dell.com", "lenovo.com", "huawei.com", "xiaomi.com", "cisco.com", "vmware.com", "docker.com", "kubernetes.io", "rust-lang.org", "golang.org", "php.net", "archive.org", "imdb.com", "quora.com", "vimeo.com", "soundcloud.com", "deezer.com", "anghami.com", "shahid.net", "who.int", "un.org", "worldbank.org", "imf.org", "nasa.gov", "nih.gov", "cdc.gov", "europa.eu", "www.gov.uk", "usa.gov", "mit.edu", "harvard.edu", "stanford.edu", "ox.ac.uk", "khalifa.ac.ae", "uaeu.ac.ae", "zu.ac.ae", "auc.edu", "visa.com", "mastercard.com", "americanexpress.com", "hsbc.com", "citi.com", "standardchartered.com", "barclays.com", "dhl.com", "fedex.com", "ups.com", "aramex.com"]

# Candidates for "legitimate newly registered domain": kept only if RDAP says registered >= 2024-01-01.
NEW_DOMAIN_CANDIDATES = ["claude.com", "sora.com", "thinkingmachines.ai", "ssi.inc", "lovable.dev", "bolt.new", "windsurf.com", "cognition.ai", "manus.im", "kimi.com", "z.ai", "genspark.ai", "base44.com", "grok.com", "meta.ai", "threads.com", "bsky.app", "truthsocial.com", "pump.fun", "kalshi.com", "mistral.ai", "x.ai", "deepseek.com", "cursor.com", "v0.dev", "gemini.google", "notebooklm.google", "ai.google", "linear.app", "zed.dev", "ghostty.org", "astral.sh", "bun.sh", "deno.com", "tailscale.com", "resend.com", "clerk.com", "neon.com", "turso.tech", "convex.dev", "trigger.dev", "railway.com", "render.com", "northflank.com", "cerebras.ai", "groq.com", "together.ai", "fireworks.ai", "elevenlabs.io", "suno.com", "udio.com", "runwayml.com", "pika.art", "ideogram.ai", "leonardo.ai", "character.ai", "poe.com", "phind.com"]

LOGIN = """https://accounts.google.com/signin|https://github.com/login|https://www.facebook.com/login/
https://www.paypal.com/signin|https://appleid.apple.com/sign-in|https://login.live.com/|https://www.linkedin.com/login
https://www.netflix.com/login|https://www.dropbox.com/login|https://accounts.spotify.com/en/login
https://chatgpt.com/auth/login|https://id.atlassian.com/login|https://slack.com/signin|https://zoom.us/signin
https://login.salesforce.com/|https://www.instagram.com/accounts/login/|https://www.reddit.com/login/
https://discord.com/login|https://signin.ebay.com/signin/|https://login.yahoo.com/|https://www.tiktok.com/login
https://wordpress.com/log-in|https://gitlab.com/users/sign_in|https://www.coinbase.com/signin
https://www.airbnb.com/login|https://www.amazon.ae/ap/signin|https://www.amazon.com/ap/signin
https://login.microsoftonline.com/|https://www.office.com/login|https://outlook.live.com/owa/
https://www.adobe.com/account/sign-in.html|https://account.proton.me/login|https://app.hubspot.com/login
https://www.notion.so/login|https://www.canva.com/login|https://www.figma.com/login|https://trello.com/login
https://login.docker.com/|https://hub.docker.com/signin|https://www.npmjs.com/login|https://pypi.org/account/login/
https://sso.godaddy.com/|https://dash.cloudflare.com/login|https://console.aws.amazon.com/
https://signin.aws.amazon.com/|https://portal.azure.com/|https://www.twitch.tv/login
https://myaccount.google.com/|https://www.pinterest.com/login/|https://accounts.snapchat.com/accounts/login
https://account.booking.com/sign-in|https://www.uber.com/login/|https://auth.uber.com/|https://my.noon.com/
https://account.samsung.com/|https://store.steampowered.com/login/|https://www.epicgames.com/id/login
https://account.battle.net/login/en/|https://accounts.zoho.com/signin|https://login.mailchimp.com/
https://www.wix.com/signin|https://www.shopify.com/login|https://www.squarespace.com/login
https://www.paypal.com/ae/signin|https://www.emirates.com/ae/english/manage-booking/
https://www.etihad.com/en-ae/manage|https://www.flydubai.com/en/manage""".replace("\n", "|").split("|")

PAYMENT = """https://www.paypal.com/ae/webapps/mpp/home|https://stripe.com/payments|https://pay.google.com/about/
https://www.apple.com/apple-pay/|https://www.apple.com/ae/shop/bag|https://www.amazon.ae/gp/cart/view.html
https://www.amazon.com/gp/cart/view.html|https://wise.com/send-money|https://www.westernunion.com/ae/en/home.html
https://squareup.com/us/en/payments|https://www.klarna.com/|https://tabby.ai/|https://tamara.co/
https://www.checkout.com/|https://www.adyen.com/|https://razorpay.com/|https://paytabs.com/|https://www.telr.com/
https://www.network.ae/|https://www.visa.com/pay|https://www.mastercard.com/global/en/personal/get-a-card.html
https://www.paypal.com/us/digital-wallet/send-receive-money|https://www.paypal.com/us/webapps/mpp/pay-online
https://www.samsung.com/ae/apps/samsung-pay/|https://pay.amazon.com/|https://www.paypal.com/us/business/accept-payments
https://www.shopify.com/payments|https://www.sharafdg.com/|https://www.carrefouruae.com/mafuae/en/
https://www.noon.com/uae-en/|https://www.talabat.com/uae|https://www.namshi.com/uae-en/|https://www.ikea.com/ae/en/
https://www.apple.com/ae/shop|https://www.microsoft.com/en-ae/store/b/home|https://store.google.com/ae/
https://www.spotify.com/ae-en/premium/|https://www.netflix.com/signup/planform|https://one.google.com/about/plans
https://www.dropbox.com/plans|https://zoom.us/pricing|https://www.canva.com/pricing/|https://github.com/pricing
https://www.adobe.com/creativecloud/plans.html|https://openai.com/chatgpt/pricing/|https://slack.com/pricing
https://www.atlassian.com/software/jira/pricing|https://aws.amazon.com/pricing/
https://www.aramex.com/ae/en/ship/pay-online|https://www.dhl.com/ae-en/home.html|https://www.fedex.com/en-ae/home.html
https://www.ups.com/ae/en/Home.page|https://www.booking.com/|https://www.airbnb.com/help""".replace("\n", "|").split("|")

DEEPLINK = """https://www.youtube.com/watch?v=dQw4w9WgXcQ|https://en.wikipedia.org/wiki/Abu_Dhabi#History
https://en.wikipedia.org/wiki/Dubai#Economy|https://ar.wikipedia.org/wiki/الإمارات_العربية_المتحدة
https://github.com/python/cpython/blob/main/README.rst|https://github.com/torvalds/linux/blob/master/MAINTAINERS
https://docs.python.org/3/library/json.html#json.loads|https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
https://stackoverflow.com/questions/11227809|https://stackoverflow.com/questions/231767
https://www.google.com/maps/place/Burj+Khalifa/|https://www.google.com/maps/search/?api=1&query=Sheikh+Zayed+Grand+Mosque
https://www.google.com/search?q=uae+pass|https://www.bing.com/search?q=abu+dhabi+weather
https://duckduckgo.com/?q=falcon+lens|https://apps.apple.com/ae/app/whatsapp-messenger/id310633997
https://apps.apple.com/ae/app/telegram-messenger/id686449807|https://apps.apple.com/ae/app/spotify-music-and-podcasts/id324684580
https://play.google.com/store/apps/details?id=com.whatsapp|https://play.google.com/store/apps/details?id=org.telegram.messenger
https://play.google.com/store/apps/details?id=com.spotify.music|https://play.google.com/store/apps/details?id=com.google.android.apps.maps
https://t.me/telegram|https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg|https://www.linkedin.com/company/microsoft/
https://www.linkedin.com/company/google/|https://www.reddit.com/r/python/|https://www.reddit.com/r/dubai/
https://news.ycombinator.com/item?id=1|https://www.bbc.com/news/world/middle_east|https://www.bbc.com/arabic
https://www.aljazeera.com/news/|https://www.reuters.com/world/middle-east/|https://www.nasa.gov/missions/
https://www.who.int/news-room/fact-sheets/detail/malaria|https://www.un.org/en/about-us/universal-declaration-of-human-rights
https://arxiv.org/abs/1706.03762|https://pypi.org/project/httpx/|https://www.npmjs.com/package/react
https://hub.docker.com/_/python|https://crates.io/crates/serde|https://pkg.go.dev/net/http
https://www.imdb.com/title/tt0111161/|https://www.goodreads.com/book/show/5107.The_Catcher_in_the_Rye
https://www.apple.com/ae/iphone/|https://www.apple.com/ae/macbook-air/|https://support.apple.com/en-ae/HT201994
https://support.google.com/accounts/answer/32040|https://support.microsoft.com/en-us/windows
https://www.microsoft.com/en-us/security/blog/|https://blog.google/technology/ai/|https://engineering.fb.com/
https://developer.apple.com/documentation/swift|https://learn.microsoft.com/en-us/azure/|https://cloud.google.com/docs
https://docs.github.com/en/get-started/start-your-journey|https://kubernetes.io/docs/concepts/overview/
https://react.dev/learn#components|https://nodejs.org/en/download|https://www.rust-lang.org/learn
https://go.dev/doc/tutorial/getting-started|https://www.php.net/manual/en/function.json-decode.php
https://www.khaleejtimes.com/uae|https://gulfnews.com/uae|https://www.thenationalnews.com/uae/
https://u.ae/en/information-and-services|https://u.ae/ar-ae/information-and-services|https://u.ae/en/about-the-uae
https://u.ae/en/information-and-services/justice-safety-and-the-law|https://u.ae/en/about-the-uae/digital-uae
https://www.visitabudhabi.ae/en|https://www.visitdubai.com/en|https://www.emirates.com/ae/english/help/
https://www.etihad.com/en-ae/help|https://www.dubaiairports.ae/|https://www.abudhabiairport.ae/en""".replace("\n", "|").split("|")

# Only named slugs / well-known public video ids on shorteners run by the destination organisation.
SHORTENED = """https://youtu.be/dQw4w9WgXcQ|https://youtu.be/jNQXAC9IVRw|https://youtu.be/9bZkp7q19f0
https://youtu.be/kJQP7kiw5Fk|https://youtu.be/YE7VzlLtp-4|https://youtu.be/hTWKbfoikeg|https://youtu.be/fJ9rUzIMcZQ
https://aka.ms/terminal|https://aka.ms/getwinget|https://aka.ms/vscode|https://aka.ms/pscore6|https://aka.ms/wsl
https://aka.ms/dotnet|https://aka.ms/windows11|https://aka.ms/edge|https://aka.ms/mscert|https://aka.ms/teams
https://aka.ms/PowerToysOverview|https://aka.ms/azcli|https://aka.ms/devhome|https://aka.ms/mslearn
https://aka.ms/winget-packages|https://aka.ms/installazurecliwindows
https://g.co/recover|https://g.co/gemini|https://g.co/help|https://g.co/pixel|https://g.co/checkup|https://g.co/ai
https://g.co/workspace|https://g.co/chrome|https://g.co/kids|https://g.co/legal|https://g.co/offers
https://apple.co/iphone|https://apple.co/support|https://apple.co/ipad|https://apple.co/mac
https://mzl.la/firefox
https://amzn.to/ |https://fb.me/|https://on.fb.me/|https://nyti.ms/|https://cnn.it/|https://bbc.in/|https://reut.rs/
https://go.microsoft.com/fwlink/?linkid=2086080|https://go.microsoft.com/fwlink/?LinkID=135873
""".replace("\n", "|").split("|")


def reg_domain(url: str) -> str:
    ext = PSL(url)
    return ".".join(p for p in (ext.domain, ext.suffix) if p).lower()


def build_candidates() -> list[dict[str, str]]:
    brands = yaml.safe_load((ROOT / "data/brands.yaml").read_text())["brands"]
    verified = {b["brand_id"]: set(b["verified_domains"]) for b in brands}
    rows: list[dict[str, str]] = []
    for bid, urls in OFFICIAL_PATHS.items():
        cat = "official_gov" if bid in GOV_BRANDS else "official_bank"
        for u in urls:
            rows.append({"url": u, "category": cat, "brand_id": bid,
                             "source": "verified_domains of data/brands.yaml; page on the entity's own site"})
    for u, cat, bid in OFFICIAL_HARD:
        rows.append({"url": u, "category": cat, "brand_id": bid,
                         "source": "official login/payment/service page on a verified_domain of data/brands.yaml"})
    for d in POPULAR:
        rows.append({"url": f"https://{d}/", "category": "popular", "brand_id": "",
                         "source": f"Tranco list {TRANCO_ID} (top-1m, retrieved {COLLECTED}); user-facing site picked by hand"})
    for d in NEW_DOMAIN_CANDIDATES:
        rows.append({"url": f"https://{d}/", "category": "hard_negative_new_domain", "brand_id": "", "source": "candidate"})
    for u in LOGIN:
        rows.append({"url": u, "category": "hard_negative_login", "brand_id": "",
                         "source": "well-known login page of a legitimate service"})
    for u in PAYMENT:
        rows.append({"url": u, "category": "hard_negative_payment", "brand_id": "",
                         "source": "payment/checkout/pricing page of a legitimate service"})
    for u in DEEPLINK:
        rows.append({"url": u, "category": "hard_negative_deeplink", "brand_id": "",
                         "source": "deep link (path/query/fragment) on a legitimate site"})
    for u in SHORTENED:
        u = u.strip()
        if not u:
            continue
        if u.endswith("/") and u.count("/") == 3:
            continue  # bare shortener roots are not short links
        rows.append({"url": u, "category": "hard_negative_shortened", "brand_id": "",
                         "source": "short link on a shortener operated by the destination organisation itself"})
    seen: set[str] = set()
    out = []
    for r in rows:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        r["_verified"] = ",".join(sorted(verified.get(r["brand_id"], ())))
        out.append(r)
    return out


def rdap_created(client: httpx.Client, domain: str) -> str | None:
    try:
        r = client.get(f"https://rdap.org/domain/{domain}", follow_redirects=True, timeout=20)
        if r.status_code != 200:
            return None
        for ev in r.json().get("events", []):
            if ev.get("eventAction") == "registration":
                return str(ev["eventDate"])[:10]
    except Exception:  # noqa: BLE001
        return None
    return None


def main() -> None:
    cands = build_candidates()
    private = ROOT / "data/private"
    private.mkdir(parents=True, exist_ok=True)
    log = (private / "legit_url_checks.jsonl").open("w")
    kept: list[dict[str, str]] = []
    with httpx.Client(headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"}, follow_redirects=True,
                      timeout=20) as client:
        for r in cands:
            time.sleep(1.0)
            rec: dict[str, object] = {"url": r["url"], "category": r["category"], "checked_at": COLLECTED}
            ok = False
            try:
                resp = client.get(r["url"])
                rec.update(status=resp.status_code, final_url=str(resp.url), redirects=len(resp.history))
                ok = 200 <= resp.status_code < 300
                if ok and r["brand_id"]:
                    ok = reg_domain(str(resp.url)) in r["_verified"].split(",")
                    rec["final_in_verified"] = ok
            except Exception as e:  # noqa: BLE001
                rec["error"] = type(e).__name__
            if ok and r["category"] == "hard_negative_new_domain":
                time.sleep(1.0)
                created = rdap_created(client, reg_domain(r["url"]))
                rec["rdap_registered"] = created
                ok = bool(created) and created >= "2024-01-01"
                if ok:
                    r["source"] = f"RDAP registration event {created} (rdap.org, {COLLECTED}); legitimate product/company site"
            rec["kept"] = ok
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.flush()
            if ok:
                kept.append(r)
            print("OK  " if ok else "DROP", r["category"], r["url"], rec.get("status", rec.get("error")), flush=True)
    out = ROOT / "evals/datasets/legit_urls.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "registrable_domain", "category", "brand_id", "source", "first_seen"])
        for r in kept:
            w.writerow([r["url"], reg_domain(r["url"]), r["category"], r["brand_id"], r["source"], COLLECTED])
    print(f"kept {len(kept)} / {len(cands)}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        main()
    else:
        print(__doc__)
