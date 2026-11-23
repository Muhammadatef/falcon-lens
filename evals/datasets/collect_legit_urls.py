# ruff: noqa: E501
"""Collect and verify the legitimate-URL eval set (docs/EVALS.md: legit URLs).

Usage (run from repo root):
  uv run --no-project --with httpx --with tldextract --with pyyaml \
      python evals/datasets/collect_legit_urls.py run

Each candidate gets ONE plain GET (honest UA, <=1 req/s, redirects followed, no forms,
no JS). Only 2xx final responses are kept; for official rows the final host must also
stay inside the brand's verified_domains. The per-row status log goes to
data/private/legit_url_checks.jsonl (gitignored). The published CSV carries only rows
that passed.

When to use it:
    Rarely: only to refresh or extend the legitimate-URL list. The result is committed, so most people
    never need to run it.

How to run:
    uv run --no-project --with httpx --with tldextract --with pyyaml python evals/datasets/collect_legit_urls.py run
    (no make target; without the word `run` it only prints this text)

Inputs:
    The candidate lists inside this file (official UAE sites and popular domains), data/brands.yaml, and live HTTPS responses from those sites.

Outputs / side effects:
    Sends one plain GET per candidate (at most one per second, no forms, no JavaScript) and RDAP lookups
    for "new domain" rows. Overwrites evals/datasets/legit_urls.csv (defanged URLs, passed rows only) and
    data/private/legit_url_checks.jsonl (gitignored status log).

Safety notes:
    It only visits legitimate, public sites. Never add phishing URLs to the candidate lists.
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
    "abu_dhabi_police": [
        "hxxps://www.adpolice.gov.ae/",
        "hxxps://www.adpolice.gov.ae/en/",
        "hxxps://www.adpolice.gov.ae/ar/",
    ],
    "dubai_police": [
        "hxxps://www.dubaipolice.gov.ae/",
        "hxxps://www.dubaipolice.gov.ae/wps/portal/home/",
        "hxxps://www.dubaipolice.gov.ae/wps/portal/home/services",
    ],
    "moi_uae": ["hxxps://www.moi.gov.ae/", "hxxps://www.moi.gov.ae/en/", "hxxps://www.moi.gov.ae/ar/"],
    "uae_pass": ["hxxps://www.uaepass.ae/", "hxxps://www.uaepass.ae/faq", "hxxps://selfcare.uaepass.ae/"],
    "tamm_abu_dhabi": [
        "hxxps://www.tamm.abudhabi/",
        "hxxps://www.tamm.abudhabi/en",
        "hxxps://www.tamm.abudhabi/ar",
        "hxxps://www.tamm.abudhabi/en/life-events",
    ],
    "icp_uae": [
        "hxxps://icp.gov.ae/",
        "hxxps://icp.gov.ae/en/",
        "hxxps://icp.gov.ae/ar/",
        "hxxps://smartservices.icp.gov.ae/",
    ],
    "emirates_post": [
        "hxxps://www.emiratespost.ae/",
        "hxxps://www.emiratespost.ae/track-and-trace",
        "hxxps://www.emiratespost.ae/en",
        "hxxps://www.epg.ae/",
    ],
    "salik": ["hxxps://www.salik.ae/", "hxxps://www.salik.ae/en", "hxxps://www.salik.ae/ar"],
    "rta_dubai": [
        "hxxps://www.rta.ae/",
        "hxxps://www.rta.ae/wps/portal/rta/ae/home",
        "hxxps://www.nol.ae/",
        "hxxps://www.rta.ae/wps/portal/rta/ae/public-transport",
    ],
    "itc_abu_dhabi_darb": ["hxxps://admobility.gov.ae/", "hxxps://admobility.gov.ae/en", "hxxps://itc.gov.ae/"],
    "addc_taqa_distribution": ["hxxps://www.addc.ae/", "hxxps://www.taqadistribution.com/"],
    "dewa": [
        "hxxps://www.dewa.gov.ae/",
        "hxxps://www.dewa.gov.ae/en/",
        "hxxps://www.dewa.gov.ae/en/customer",
        "hxxps://www.dewa.gov.ae/ar/",
    ],
    "sewa": ["hxxps://www.sewa.gov.ae/", "hxxps://www.sewa.gov.ae/en/", "hxxps://www.sewa.gov.ae/ar/"],
    "etisalat_by_eand": [
        "hxxps://www.etisalat.ae/",
        "hxxps://www.etisalat.ae/en/c/personal.html",
        "hxxps://www.eand.com/",
        "hxxps://www.eand.com/en/home.html",
        "hxxps://www.eand.ae/",
    ],
    "du": [
        "hxxps://www.du.ae/",
        "hxxps://www.du.ae/personal",
        "hxxps://www.du.ae/business",
        "hxxps://www.du.ae/ar/personal",
    ],
    "cbuae": [
        "hxxps://www.centralbank.ae/",
        "hxxps://www.centralbank.ae/en/",
        "hxxps://www.centralbank.ae/ar/",
        "hxxps://www.centralbank.ae/en/consumer-protection/",
    ],
    "fab": [
        "hxxps://www.bankfab.com/",
        "hxxps://www.bankfab.com/en-ae/personal",
        "hxxps://www.bankfab.com/ar-ae/personal",
        "hxxps://www.bankfab.com/en-ae/personal/ways-to-bank/digital-banking",
    ],
    "adcb": [
        "hxxps://www.adcb.com/",
        "hxxps://www.adcb.com/en/personal/",
        "hxxps://www.adcb.com/en/personal/ways-to-bank/",
        "hxxps://www.adcb.com/ar/",
    ],
    "emirates_nbd": [
        "hxxps://www.emiratesnbd.com/",
        "hxxps://www.emiratesnbd.com/en",
        "hxxps://www.emiratesnbd.com/ar-ae",
        "hxxps://www.emiratesnbd.com/en/ways-to-bank/online-banking",
    ],
    "dib": [
        "hxxps://www.dib.ae/",
        "hxxps://www.dib.ae/personal",
        "hxxps://www.dib.ae/ar",
        "hxxps://www.dib.ae/personal/ways-to-bank",
    ],
    "mashreq": [
        "hxxps://www.mashreq.com/",
        "hxxps://www.mashreq.com/en/uae/neo/",
        "hxxps://www.mashreq.com/en/uae/neo/personal",
        "hxxps://www.mashreq.com/ar/uae/neo/",
    ],
    "adib": [
        "hxxps://www.adib.ae/",
        "hxxps://www.adib.ae/en/Pages/default.aspx",
        "hxxps://www.adib.ae/ar/Pages/default.aspx",
        "hxxps://www.adib.com/",
    ],
    "rakbank": [
        "hxxps://www.rakbank.ae/",
        "hxxps://www.rakbank.ae/wps/portal/retail-banking/home",
        "hxxps://www.rakbank.ae/en/",
        "hxxps://www.rakbank.ae/ar/",
    ],
    "emirates_islamic": [
        "hxxps://www.emiratesislamic.ae/",
        "hxxps://www.emiratesislamic.ae/en",
        "hxxps://www.emiratesislamic.ae/ar",
    ],
}
GOV_BRANDS = {
    "abu_dhabi_police",
    "dubai_police",
    "moi_uae",
    "uae_pass",
    "tamm_abu_dhabi",
    "icp_uae",
    "emirates_post",
    "salik",
    "rta_dubai",
    "itc_abu_dhabi_darb",
    "addc_taqa_distribution",
    "dewa",
    "sewa",
    "etisalat_by_eand",
    "du",
    "cbuae",
}
# Official login / payment / service pages (also hard negatives); brand_id filled.
OFFICIAL_HARD = [
    ("hxxps://www.dewa.gov.ae/en/customer/services/pay-your-bill", "hard_negative_payment", "dewa"),
    ("hxxps://www.salik.ae/en/recharge", "hard_negative_payment", "salik"),
    ("hxxps://www.etisalat.ae/en/c/pay-bill.html", "hard_negative_payment", "etisalat_by_eand"),
    ("hxxps://www.du.ae/personal/pay-bill", "hard_negative_payment", "du"),
    ("hxxps://www.emiratespost.ae/en/sendmoney", "hard_negative_payment", "emirates_post"),
    ("hxxps://www.adcb.com/en/personal/ways-to-bank/online-banking/", "hard_negative_login", "adcb"),
    ("hxxps://www.emiratesnbd.com/en/ways-to-bank/mobile-banking", "hard_negative_login", "emirates_nbd"),
    (
        "hxxps://www.bankfab.com/en-ae/personal/ways-to-bank/digital-banking/online-banking",
        "hard_negative_login",
        "fab",
    ),
    ("hxxps://www.mashreq.com/en/uae/neo/ways-to-bank/", "hard_negative_login", "mashreq"),
    ("hxxps://www.dib.ae/personal/ways-to-bank/online-banking", "hard_negative_login", "dib"),
    ("hxxps://www.rakbank.ae/en/personal/ways-to-bank/", "hard_negative_login", "rakbank"),
    ("hxxps://onlinebanking.emiratesnbd.com/", "hard_negative_login", "emirates_nbd"),
    ("hxxps://www.uaepass.ae/login", "hard_negative_login", "uae_pass"),
    ("hxxps://smartservices.icp.gov.ae/echannels/web/client/guest/index.html", "hard_negative_login", "icp_uae"),
    ("hxxps://www.tamm.abudhabi/en/aspects-of-life", "hard_negative_login", "tamm_abu_dhabi"),
    (
        "hxxps://www.dubaipolice.gov.ae/wps/portal/home/services/individualservices/paytrafficfines",
        "hard_negative_payment",
        "dubai_police",
    ),
    ("hxxps://www.adpolice.gov.ae/en/services", "hard_negative_payment", "abu_dhabi_police"),
    ("hxxps://www.rta.ae/wps/portal/rta/ae/home/fines", "hard_negative_payment", "rta_dubai"),
    ("hxxps://www.eand.com/en/personal/pay-bill.html", "hard_negative_payment", "etisalat_by_eand"),
]

# Tranco list TRANCO_ID (top-1m); user-facing sites picked by hand (CDN/infra domains excluded).
POPULAR = [
    "google.com",
    "facebook.com",
    "microsoft.com",
    "youtube.com",
    "apple.com",
    "instagram.com",
    "linkedin.com",
    "amazon.com",
    "wikipedia.org",
    "netflix.com",
    "github.com",
    "yahoo.com",
    "bing.com",
    "reddit.com",
    "x.com",
    "whatsapp.com",
    "zoom.us",
    "adobe.com",
    "wordpress.org",
    "wordpress.com",
    "paypal.com",
    "ebay.com",
    "cloudflare.com",
    "mozilla.org",
    "spotify.com",
    "tiktok.com",
    "pinterest.com",
    "tumblr.com",
    "medium.com",
    "dropbox.com",
    "salesforce.com",
    "oracle.com",
    "ibm.com",
    "intel.com",
    "nvidia.com",
    "bbc.com",
    "cnn.com",
    "nytimes.com",
    "theguardian.com",
    "reuters.com",
    "bloomberg.com",
    "aljazeera.com",
    "aljazeera.net",
    "khaleejtimes.com",
    "gulfnews.com",
    "thenationalnews.com",
    "arabianbusiness.com",
    "emirates.com",
    "etihad.com",
    "flydubai.com",
    "airarabia.com",
    "noon.com",
    "talabat.com",
    "careem.com",
    "dubizzle.com",
    "bayut.com",
    "propertyfinder.ae",
    "carrefouruae.com",
    "lulu.com",
    "namshi.com",
    "sharafdg.com",
    "amazon.ae",
    "amazon.sa",
    "python.org",
    "nodejs.org",
    "stackoverflow.com",
    "gitlab.com",
    "slack.com",
    "atlassian.com",
    "notion.so",
    "canva.com",
    "figma.com",
    "openai.com",
    "anthropic.com",
    "duckduckgo.com",
    "twitch.tv",
    "discord.com",
    "telegram.org",
    "signal.org",
    "skype.com",
    "office.com",
    "live.com",
    "outlook.com",
    "icloud.com",
    "booking.com",
    "airbnb.com",
    "tripadvisor.com",
    "expedia.com",
    "uber.com",
    "aliexpress.com",
    "alibaba.com",
    "temu.com",
    "shein.com",
    "walmart.com",
    "target.com",
    "bestbuy.com",
    "ikea.com",
    "nike.com",
    "adidas.com",
    "samsung.com",
    "sony.com",
    "hp.com",
    "dell.com",
    "lenovo.com",
    "huawei.com",
    "xiaomi.com",
    "cisco.com",
    "vmware.com",
    "docker.com",
    "kubernetes.io",
    "rust-lang.org",
    "golang.org",
    "php.net",
    "archive.org",
    "imdb.com",
    "quora.com",
    "vimeo.com",
    "soundcloud.com",
    "deezer.com",
    "anghami.com",
    "shahid.net",
    "who.int",
    "un.org",
    "worldbank.org",
    "imf.org",
    "nasa.gov",
    "nih.gov",
    "cdc.gov",
    "europa.eu",
    "www.gov.uk",
    "usa.gov",
    "mit.edu",
    "harvard.edu",
    "stanford.edu",
    "ox.ac.uk",
    "khalifa.ac.ae",
    "uaeu.ac.ae",
    "zu.ac.ae",
    "auc.edu",
    "visa.com",
    "mastercard.com",
    "americanexpress.com",
    "hsbc.com",
    "citi.com",
    "standardchartered.com",
    "barclays.com",
    "dhl.com",
    "fedex.com",
    "ups.com",
    "aramex.com",
]

# Candidates for "legitimate newly registered domain": kept only if RDAP says registered >= 2024-01-01.
NEW_DOMAIN_CANDIDATES = [
    "claude.com",
    "sora.com",
    "thinkingmachines.ai",
    "ssi.inc",
    "lovable.dev",
    "bolt.new",
    "windsurf.com",
    "cognition.ai",
    "manus.im",
    "kimi.com",
    "z.ai",
    "genspark.ai",
    "base44.com",
    "grok.com",
    "meta.ai",
    "threads.com",
    "bsky.app",
    "truthsocial.com",
    "pump.fun",
    "kalshi.com",
    "mistral.ai",
    "x.ai",
    "deepseek.com",
    "cursor.com",
    "v0.dev",
    "gemini.google",
    "notebooklm.google",
    "ai.google",
    "linear.app",
    "zed.dev",
    "ghostty.org",
    "astral.sh",
    "bun.sh",
    "deno.com",
    "tailscale.com",
    "resend.com",
    "clerk.com",
    "neon.com",
    "turso.tech",
    "convex.dev",
    "trigger.dev",
    "railway.com",
    "render.com",
    "northflank.com",
    "cerebras.ai",
    "groq.com",
    "together.ai",
    "fireworks.ai",
    "elevenlabs.io",
    "suno.com",
    "udio.com",
    "runwayml.com",
    "pika.art",
    "ideogram.ai",
    "leonardo.ai",
    "character.ai",
    "poe.com",
    "phind.com",
]


# C06 (contributor): new domains verified by hand on 2026-11-22. The RDAP registration date comes from
# the TLD's authoritative RDAP server (IANA bootstrap); the linking page is the owner's established site or
# official announcement and contains the domain. The date is pinned, so a re-run does not need rdap.org.
# (domain, rdap_registration, rdap_server, linked_from, note)
NEW_DOMAIN_VERIFIED: list[tuple[str, str, str, str, str]] = [
    (
        "k2think.ai",
        "2025-08-21",
        "rdap.identitydigital.services",
        "hxxps://mbzuai.ac.ae/news/mbzuai-and-g42-launch-k2-think-a-leading-open-source-system-for-advanced-ai-reasoning/",
        "MBZUAI + G42 K2 Think",
    ),
    (
        "inceptionai.ai",
        "2024-07-03",
        "rdap.identitydigital.services",
        "hxxps://www.g42.ai/companies/inception-institute-of-ai",
        "G42 company Inception (Jais)",
    ),
    (
        "investwithabudhabi.com",
        "2024-10-03",
        "rdap.verisign.com",
        "hxxps://www.investinabudhabi.ae/About-Us",
        "Abu Dhabi Investment Office (ADIO)",
    ),
    (
        "adif.abudhabi",
        "2025-05-29",
        "rdap.nic.abudhabi",
        "hxxps://www.investinabudhabi.ae/About-Us",
        "Abu Dhabi Investment Forum (ADIO)",
    ),
    (
        "aieverythingabudhabi.com",
        "2025-09-16",
        "rdap.verisign.com",
        "hxxps://u.ae/en/",
        "AI Everything Abu Dhabi, linked from the UAE gov portal",
    ),
    ("aieverythingglobal.com", "2024-01-11", "rdap.verisign.com", "hxxps://www.gitex.com/", "DWTC/KAOUN AI Everything"),
    (
        "gitexvietnam.com",
        "2024-07-23",
        "rdap.verisign.com",
        "hxxps://www.gitex.com/News/gitex-expands-to-vietnam-igniting-us200bn-national-digital-economy-potential",
        "DWTC/KAOUN GITEX edition",
    ),
    ("gitexturkiye.com", "2025-08-19", "rdap.verisign.com", "hxxps://www.gitex.com/", "DWTC/KAOUN GITEX edition"),
    ("gitexlatam.com", "2025-08-19", "rdap.verisign.com", "hxxps://www.gitex.com/", "DWTC/KAOUN GITEX edition"),
    ("gitexfuturehealth.com", "2025-03-14", "rdap.verisign.com", "hxxps://www.gitex.com/", "DWTC/KAOUN GITEX edition"),
    (
        "gitexserbia.com",
        "2024-10-30",
        "rdap.verisign.com",
        "hxxps://www.gitex.com/",
        "DWTC/KAOUN GITEX edition (redirects to gitexbelgrade.com)",
    ),
    ("gitexitaly.com", "2026-01-22", "rdap.verisign.com", "hxxps://www.gitex.com/", "DWTC/KAOUN GITEX edition"),
    (
        "aieverythingegypt.com",
        "2025-01-31",
        "rdap.verisign.com",
        "hxxps://www.gitex.com/",
        "DWTC/KAOUN AI Everything edition",
    ),
    ("gqxdubai.com", "2026-04-30", "rdap.verisign.com", "hxxps://www.gitex.com/", "DWTC/KAOUN GITEX event"),
    ("gitexnewenergy.com", "2026-05-14", "rdap.verisign.com", "hxxps://www.gitex.com/", "DWTC/KAOUN GITEX event"),
    ("gitex-india.com", "2025-10-08", "rdap.verisign.com", "hxxps://www.gitex.com/", "DWTC/KAOUN GITEX edition"),
    (
        "aistudio.google",
        "2026-05-19",
        "pubapi.registry.google",
        "hxxps://labs.google/",
        "closed .google brand TLD (Google AI Studio)",
    ),
    (
        "antigravity.google",
        "2025-09-19",
        "pubapi.registry.google",
        "hxxps://ai.google.dev/",
        "closed .google brand TLD",
    ),
    ("jules.google", "2025-01-16", "pubapi.registry.google", "hxxps://ai.google.dev/", "closed .google brand TLD"),
    (
        "notebook.google",
        "2026-06-25",
        "pubapi.registry.google",
        "hxxps://notebooklm.google/",
        "closed .google brand TLD",
    ),
    (
        "flow.google",
        "2025-05-05",
        "pubapi.registry.google",
        "hxxps://blog.google/technology/ai/google-flow-veo-ai-filmmaking-tool/",
        "closed .google brand TLD",
    ),
    (
        "beam.google",
        "2024-04-10",
        "pubapi.registry.google",
        "hxxps://blog.google/technology/research/project-starline-google-beam-update/",
        "closed .google brand TLD",
    ),
    (
        "googlebook.google",
        "2026-03-09",
        "pubapi.registry.google",
        "hxxps://about.google/products/",
        "closed .google brand TLD",
    ),
    ("tabletop.google", "2026-10-13", "pubapi.registry.google", "hxxps://labs.google/", "closed .google brand TLD"),
    ("hailuoai.video", "2024-09-05", "rdap.identitydigital.services", "hxxps://www.minimax.io/", "MiniMax Hailuo"),
    ("diabrowser.com", "2024-10-18", "rdap.verisign.com", "hxxps://thebrowser.company/", "The Browser Company Dia"),
    ("grokipedia.com", "2025-04-28", "rdap.verisign.com", "hxxps://x.ai/", "xAI"),
    (
        "lmarena.ai",
        "2024-06-21",
        "rdap.identitydigital.services",
        "hxxps://github.com/lm-sys/FastChat",
        "LMArena (redirects to arena.ai)",
    ),
    (
        "a2a-protocol.org",
        "2025-07-04",
        "rdap.publicinterestregistry.org",
        "hxxps://github.com/a2aproject/A2A",
        "Agent2Agent protocol",
    ),
    (
        "llmstxt.org",
        "2024-09-02",
        "rdap.publicinterestregistry.org",
        "hxxps://www.answer.ai/posts/2024-09-03-llmstxt.html",
        "Answer.AI llms.txt",
    ),
    ("voidzero.dev", "2024-03-15", "pubapi.registry.google", "hxxps://vite.dev/", "VoidZero (Vite)"),
    (
        "zen-browser.app",
        "2024-08-06",
        "pubapi.registry.google",
        "hxxps://github.com/zen-browser/desktop",
        "Zen Browser",
    ),
    (
        "omarchy.org",
        "2025-06-01",
        "rdap.publicinterestregistry.org",
        "hxxps://github.com/basecamp/omarchy",
        "Basecamp Omarchy",
    ),
    (
        "blackforestlabs.ai",
        "2024-03-12",
        "rdap.identitydigital.services",
        "hxxps://huggingface.co/black-forest-labs",
        "Black Forest Labs (redirects to bfl.ai)",
    ),
    ("trae.ai", "2024-12-16", "rdap.identitydigital.services", "hxxps://github.com/Trae-AI", "Trae"),
]

LOGIN = """hxxps://accounts.google.com/signin|hxxps://github.com/login|hxxps://www.facebook.com/login/
hxxps://www.paypal.com/signin|hxxps://appleid.apple.com/sign-in|hxxps://login.live.com/|hxxps://www.linkedin.com/login
hxxps://www.netflix.com/login|hxxps://www.dropbox.com/login|hxxps://accounts.spotify.com/en/login
hxxps://chatgpt.com/auth/login|hxxps://id.atlassian.com/login|hxxps://slack.com/signin|hxxps://zoom.us/signin
hxxps://login.salesforce.com/|hxxps://www.instagram.com/accounts/login/|hxxps://www.reddit.com/login/
hxxps://discord.com/login|hxxps://signin.ebay.com/signin/|hxxps://login.yahoo.com/|hxxps://www.tiktok.com/login
hxxps://wordpress.com/log-in|hxxps://gitlab.com/users/sign_in|hxxps://www.coinbase.com/signin
hxxps://www.airbnb.com/login|hxxps://www.amazon.ae/ap/signin|hxxps://www.amazon.com/ap/signin
hxxps://login.microsoftonline.com/|hxxps://www.office.com/login|hxxps://outlook.live.com/owa/
hxxps://www.adobe.com/account/sign-in.html|hxxps://account.proton.me/login|hxxps://app.hubspot.com/login
hxxps://www.notion.so/login|hxxps://www.canva.com/login|hxxps://www.figma.com/login|hxxps://trello.com/login
hxxps://login.docker.com/|hxxps://hub.docker.com/signin|hxxps://www.npmjs.com/login|hxxps://pypi.org/account/login/
hxxps://sso.godaddy.com/|hxxps://dash.cloudflare.com/login|hxxps://console.aws.amazon.com/
hxxps://signin.aws.amazon.com/|hxxps://portal.azure.com/|hxxps://www.twitch.tv/login
hxxps://myaccount.google.com/|hxxps://www.pinterest.com/login/|hxxps://accounts.snapchat.com/accounts/login
hxxps://account.booking.com/sign-in|hxxps://www.uber.com/login/|hxxps://auth.uber.com/|hxxps://my.noon.com/
hxxps://account.samsung.com/|hxxps://store.steampowered.com/login/|hxxps://www.epicgames.com/id/login
hxxps://account.battle.net/login/en/|hxxps://accounts.zoho.com/signin|hxxps://login.mailchimp.com/
hxxps://www.wix.com/signin|hxxps://www.shopify.com/login|hxxps://www.squarespace.com/login
hxxps://www.paypal.com/ae/signin|hxxps://www.emirates.com/ae/english/manage-booking/
hxxps://www.etihad.com/en-ae/manage|hxxps://www.flydubai.com/en/manage""".replace("\n", "|").split("|")

PAYMENT = """hxxps://www.paypal.com/ae/webapps/mpp/home|hxxps://stripe.com/payments|hxxps://pay.google.com/about/
hxxps://www.apple.com/apple-pay/|hxxps://www.apple.com/ae/shop/bag|hxxps://www.amazon.ae/gp/cart/view.html
hxxps://www.amazon.com/gp/cart/view.html|hxxps://wise.com/send-money|hxxps://www.westernunion.com/ae/en/home.html
hxxps://squareup.com/us/en/payments|hxxps://www.klarna.com/|hxxps://tabby.ai/|hxxps://tamara.co/
hxxps://www.checkout.com/|hxxps://www.adyen.com/|hxxps://razorpay.com/|hxxps://paytabs.com/|hxxps://www.telr.com/
hxxps://www.network.ae/|hxxps://www.visa.com/pay|hxxps://www.mastercard.com/global/en/personal/get-a-card.html
hxxps://www.paypal.com/us/digital-wallet/send-receive-money|hxxps://www.paypal.com/us/webapps/mpp/pay-online
hxxps://www.samsung.com/ae/apps/samsung-pay/|hxxps://pay.amazon.com/|hxxps://www.paypal.com/us/business/accept-payments
hxxps://www.shopify.com/payments|hxxps://www.sharafdg.com/|hxxps://www.carrefouruae.com/mafuae/en/
hxxps://www.noon.com/uae-en/|hxxps://www.talabat.com/uae|hxxps://www.namshi.com/uae-en/|hxxps://www.ikea.com/ae/en/
hxxps://www.apple.com/ae/shop|hxxps://www.microsoft.com/en-ae/store/b/home|hxxps://store.google.com/ae/
hxxps://www.spotify.com/ae-en/premium/|hxxps://www.netflix.com/signup/planform|hxxps://one.google.com/about/plans
hxxps://www.dropbox.com/plans|hxxps://zoom.us/pricing|hxxps://www.canva.com/pricing/|hxxps://github.com/pricing
hxxps://www.adobe.com/creativecloud/plans.html|hxxps://openai.com/chatgpt/pricing/|hxxps://slack.com/pricing
hxxps://www.atlassian.com/software/jira/pricing|hxxps://aws.amazon.com/pricing/
hxxps://www.aramex.com/ae/en/ship/pay-online|hxxps://www.dhl.com/ae-en/home.html|hxxps://www.fedex.com/en-ae/home.html
hxxps://www.ups.com/ae/en/Home.page|hxxps://www.booking.com/|hxxps://www.airbnb.com/help""".replace("\n", "|").split(
    "|"
)

DEEPLINK = """hxxps://www.youtube.com/watch?v=dQw4w9WgXcQ|hxxps://en.wikipedia.org/wiki/Abu_Dhabi#History
hxxps://en.wikipedia.org/wiki/Dubai#Economy|hxxps://ar.wikipedia.org/wiki/الإمارات_العربية_المتحدة
hxxps://github.com/python/cpython/blob/main/README.rst|hxxps://github.com/torvalds/linux/blob/master/MAINTAINERS
hxxps://docs.python.org/3/library/json.html#json.loads|hxxps://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
hxxps://stackoverflow.com/questions/11227809|hxxps://stackoverflow.com/questions/231767
hxxps://www.google.com/maps/place/Burj+Khalifa/|hxxps://www.google.com/maps/search/?api=1&query=Sheikh+Zayed+Grand+Mosque
hxxps://www.google.com/search?q=uae+pass|hxxps://www.bing.com/search?q=abu+dhabi+weather
hxxps://duckduckgo.com/?q=falcon+lens|hxxps://apps.apple.com/ae/app/whatsapp-messenger/id310633997
hxxps://apps.apple.com/ae/app/telegram-messenger/id686449807|hxxps://apps.apple.com/ae/app/spotify-music-and-podcasts/id324684580
hxxps://play.google.com/store/apps/details?id=com.whatsapp|hxxps://play.google.com/store/apps/details?id=org.telegram.messenger
hxxps://play.google.com/store/apps/details?id=com.spotify.music|hxxps://play.google.com/store/apps/details?id=com.google.android.apps.maps
hxxps://t.me/telegram|hxxps://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg|hxxps://www.linkedin.com/company/microsoft/
hxxps://www.linkedin.com/company/google/|hxxps://www.reddit.com/r/python/|hxxps://www.reddit.com/r/dubai/
hxxps://news.ycombinator.com/item?id=1|hxxps://www.bbc.com/news/world/middle_east|hxxps://www.bbc.com/arabic
hxxps://www.aljazeera.com/news/|hxxps://www.reuters.com/world/middle-east/|hxxps://www.nasa.gov/missions/
hxxps://www.who.int/news-room/fact-sheets/detail/malaria|hxxps://www.un.org/en/about-us/universal-declaration-of-human-rights
hxxps://arxiv.org/abs/1706.03762|hxxps://pypi.org/project/httpx/|hxxps://www.npmjs.com/package/react
hxxps://hub.docker.com/_/python|hxxps://crates.io/crates/serde|hxxps://pkg.go.dev/net/http
hxxps://www.imdb.com/title/tt0111161/|hxxps://www.goodreads.com/book/show/5107.The_Catcher_in_the_Rye
hxxps://www.apple.com/ae/iphone/|hxxps://www.apple.com/ae/macbook-air/|hxxps://support.apple.com/en-ae/HT201994
hxxps://support.google.com/accounts/answer/32040|hxxps://support.microsoft.com/en-us/windows
hxxps://www.microsoft.com/en-us/security/blog/|hxxps://blog.google/technology/ai/|hxxps://engineering.fb.com/
hxxps://developer.apple.com/documentation/swift|hxxps://learn.microsoft.com/en-us/azure/|hxxps://cloud.google.com/docs
hxxps://docs.github.com/en/get-started/start-your-journey|hxxps://kubernetes.io/docs/concepts/overview/
hxxps://react.dev/learn#components|hxxps://nodejs.org/en/download|hxxps://www.rust-lang.org/learn
hxxps://go.dev/doc/tutorial/getting-started|hxxps://www.php.net/manual/en/function.json-decode.php
hxxps://www.khaleejtimes.com/uae|hxxps://gulfnews.com/uae|hxxps://www.thenationalnews.com/uae/
hxxps://u.ae/en/information-and-services|hxxps://u.ae/ar-ae/information-and-services|hxxps://u.ae/en/about-the-uae
hxxps://u.ae/en/information-and-services/justice-safety-and-the-law|hxxps://u.ae/en/about-the-uae/digital-uae
hxxps://www.visitabudhabi.ae/en|hxxps://www.visitdubai.com/en|hxxps://www.emirates.com/ae/english/help/
hxxps://www.etihad.com/en-ae/help|hxxps://www.dubaiairports.ae/|hxxps://www.abudhabiairport.ae/en""".replace(
    "\n", "|"
).split("|")

# Only named slugs / well-known public video ids on shorteners run by the destination organisation.
SHORTENED = """hxxps://youtu.be/dQw4w9WgXcQ|hxxps://youtu.be/jNQXAC9IVRw|hxxps://youtu.be/9bZkp7q19f0
hxxps://youtu.be/kJQP7kiw5Fk|hxxps://youtu.be/YE7VzlLtp-4|hxxps://youtu.be/hTWKbfoikeg|hxxps://youtu.be/fJ9rUzIMcZQ
hxxps://aka.ms/terminal|hxxps://aka.ms/getwinget|hxxps://aka.ms/vscode|hxxps://aka.ms/pscore6|hxxps://aka.ms/wsl
hxxps://aka.ms/dotnet|hxxps://aka.ms/windows11|hxxps://aka.ms/edge|hxxps://aka.ms/mscert|hxxps://aka.ms/teams
hxxps://aka.ms/PowerToysOverview|hxxps://aka.ms/azcli|hxxps://aka.ms/devhome|hxxps://aka.ms/mslearn
hxxps://aka.ms/winget-packages|hxxps://aka.ms/installazurecliwindows
hxxps://g.co/recover|hxxps://g.co/gemini|hxxps://g.co/help|hxxps://g.co/pixel|hxxps://g.co/checkup|hxxps://g.co/ai
hxxps://g.co/workspace|hxxps://g.co/chrome|hxxps://g.co/kids|hxxps://g.co/legal|hxxps://g.co/offers
hxxps://apple.co/iphone|hxxps://apple.co/support|hxxps://apple.co/ipad|hxxps://apple.co/mac
hxxps://mzl.la/firefox
hxxps://amzn.to/ |hxxps://fb.me/|hxxps://on.fb.me/|hxxps://nyti.ms/|hxxps://cnn.it/|hxxps://bbc.in/|hxxps://reut.rs/
hxxps://go.microsoft.com/fwlink/?linkid=2086080|hxxps://go.microsoft.com/fwlink/?LinkID=135873
""".replace("\n", "|").split("|")


# C06 (contributor): short links on the destination organisation's own shortener, checked 2026-11-22
# (>= 1 redirect, final 2xx on the owner's registrable domain). (url, owner_final_domain)
SHORTENED_C06: list[tuple[str, str]] = [
    ("hxxps://aka.ms/authapp", "microsoft.com"),
    ("hxxps://aka.ms/mfasetup", "microsoft.com"),
    ("hxxps://aka.ms/sspr", "microsoftonline.com"),
    ("hxxps://aka.ms/powershell", "microsoft.com"),
    ("hxxps://aka.ms/vs", "microsoft.com"),
    ("hxxps://aka.ms/windowsinsider", "microsoft.com"),
    ("hxxps://youtu.be/OPf0YbXqDm0", "youtube.com"),
    ("hxxps://youtu.be/RgKAFK5djSk", "youtube.com"),
    ("hxxps://youtu.be/JGwWNGJdvx8", "youtube.com"),
    ("hxxps://youtu.be/60ItHLz5WEA", "youtube.com"),
    ("hxxps://youtu.be/CevxZvSJLk8", "youtube.com"),
    ("hxxps://g.co/play", "google.com"),
    ("hxxps://g.co/meet", "google.com"),
    ("hxxps://g.co/nest", "google.com"),
    ("hxxps://g.co/privacytools", "google.com"),
    ("hxxps://g.co/safety", "safety.google"),
    ("hxxps://goo.gle/gemini", "google.com"),
    ("hxxps://goo.gle/devfest", "google.com"),
    ("hxxps://goo.gle/gemini-api", "google.com"),
    ("hxxps://apple.co/applecard", "apple.com"),
    ("hxxps://m.me/meta", "messenger.com"),
    ("hxxps://fb.me/facebook", "facebook.com"),
    ("hxxps://gh.io/copilot", "github.com"),
]


def refang(url: str) -> str:
    """URLs are stored defanged (hxxps://) in this file and the CSV so the repo guard passes."""
    return url.replace("hxxp", "http", 1)


def reg_domain(url: str) -> str:
    """Registrable domain (eTLD+1) of a URL."""
    ext = PSL(refang(url))
    return ".".join(p for p in (ext.domain, ext.suffix) if p).lower()


def build_candidates() -> list[dict[str, str]]:
    """The candidate legitimate URLs (official sites, popular domains, new-domain hard negatives)."""
    brands = yaml.safe_load((ROOT / "data/brands.yaml").read_text())["brands"]
    verified = {b["brand_id"]: set(b["verified_domains"]) for b in brands}
    rows: list[dict[str, str]] = []
    for bid, urls in OFFICIAL_PATHS.items():
        cat = "official_gov" if bid in GOV_BRANDS else "official_bank"
        for u in urls:
            rows.append(
                {
                    "url": u,
                    "category": cat,
                    "brand_id": bid,
                    "source": "verified_domains of data/brands.yaml; page on the entity's own site",
                }
            )
    for u, cat, bid in OFFICIAL_HARD:
        rows.append(
            {
                "url": u,
                "category": cat,
                "brand_id": bid,
                "source": "official login/payment/service page on a verified_domain of data/brands.yaml",
            }
        )
    for d in POPULAR:
        rows.append(
            {
                "url": f"hxxps://{d}/",
                "category": "popular",
                "brand_id": "",
                "source": f"Tranco list {TRANCO_ID} (top-1m, retrieved {COLLECTED}); user-facing site picked by hand",
            }
        )
    for d in NEW_DOMAIN_CANDIDATES:
        rows.append(
            {"url": f"hxxps://{d}/", "category": "hard_negative_new_domain", "brand_id": "", "source": "candidate"}
        )
    for d, created, server, linked_from, _note in NEW_DOMAIN_VERIFIED:
        rows.append(
            {
                "url": f"hxxps://{d}/",
                "category": "hard_negative_new_domain",
                "brand_id": "",
                "source": f"RDAP registration event {created} ({server}, {COLLECTED}); legitimate site linked from {linked_from}",
                "_rdap_pinned": created,
            }
        )
    for u in LOGIN:
        rows.append(
            {
                "url": u,
                "category": "hard_negative_login",
                "brand_id": "",
                "source": "well-known login page of a legitimate service",
            }
        )
    for u in PAYMENT:
        rows.append(
            {
                "url": u,
                "category": "hard_negative_payment",
                "brand_id": "",
                "source": "payment/checkout/pricing page of a legitimate service",
            }
        )
    for u in DEEPLINK:
        rows.append(
            {
                "url": u,
                "category": "hard_negative_deeplink",
                "brand_id": "",
                "source": "deep link (path/query/fragment) on a legitimate site",
            }
        )
    for u in SHORTENED + [u for u, _owner in SHORTENED_C06]:
        u = u.strip()
        if not u:
            continue
        if u.endswith("/") and u.count("/") == 3:
            continue  # bare shortener roots are not short links
        rows.append(
            {
                "url": u,
                "category": "hard_negative_shortened",
                "brand_id": "",
                "source": "short link on a shortener operated by the destination organisation itself",
            }
        )
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
    """Registration date of a domain from RDAP, or None."""
    try:
        r = client.get(f"hxxps://rdap.org/domain/{domain}", follow_redirects=True, timeout=20)
        if r.status_code != 200:
            return None
        for ev in r.json().get("events", []):
            if ev.get("eventAction") == "registration":
                return str(ev["eventDate"])[:10]
    except Exception:  # noqa: BLE001
        return None
    return None


def main() -> None:
    """Check every candidate once and write evals/datasets/legit_urls.csv with the ones that passed."""
    cands = build_candidates()
    private = ROOT / "data/private"
    private.mkdir(parents=True, exist_ok=True)
    log = (private / "legit_url_checks.jsonl").open("w")
    kept: list[dict[str, str]] = []
    with httpx.Client(
        headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"}, follow_redirects=True, timeout=20
    ) as client:
        for r in cands:
            time.sleep(1.0)
            rec: dict[str, object] = {"url": r["url"], "category": r["category"], "checked_at": COLLECTED}
            ok = False
            try:
                resp = client.get(refang(r["url"]))
                rec.update(status=resp.status_code, final_url=str(resp.url), redirects=len(resp.history))
                ok = 200 <= resp.status_code < 300
                if ok and r["brand_id"]:
                    ok = reg_domain(str(resp.url)) in r["_verified"].split(",")
                    rec["final_in_verified"] = ok
            except Exception as e:  # noqa: BLE001
                rec["error"] = type(e).__name__
            if ok and r["category"] == "hard_negative_new_domain":
                created = r.get("_rdap_pinned")
                if not created:
                    time.sleep(1.0)
                    created = rdap_created(client, reg_domain(r["url"]))
                rec["rdap_registered"] = created
                ok = bool(created) and created >= "2024-01-01"
                if ok and not r.get("_rdap_pinned"):
                    r["source"] = (
                        f"RDAP registration event {created} (rdap.org, {COLLECTED}); legitimate product/company site"
                    )
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
