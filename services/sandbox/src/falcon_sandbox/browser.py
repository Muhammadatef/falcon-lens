"""Warm Chromium + fresh context per visit. Passive: never types, clicks or submits."""

from __future__ import annotations

import asyncio
import base64  # noqa: F401  (kept for debugging helpers)
import contextlib
import hashlib
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Route,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from falcon_core.signals.page.features import (
    BlockedRequest,
    Favicon,
    Hop,
    NetworkSummary,
    PostTarget,
    ProfileFeatures,
)
from falcon_core.signals.page.hosts import host_of, same_site
from falcon_core.signals.page.simhash import dom_simhash
from falcon_core.signals.visual.phash import phash_from_gray32

from .build import (
    build_dynamic_post_target,
    build_forms,
    build_js,
    build_static_post_targets,
    truncate_utf8,
)
from .extract_js import EXTRACT_JS
from .policy import (
    MAIN_DOC_HARD_BYTES,
    MAIN_DOC_MAX_BYTES,
    MAX_REDIRECTS,
    MAX_TOTAL_BYTES,
    NAV_BUDGET_S,
    SUBRESOURCE_TIMEOUT_S,
    TOTAL_TIMEOUT_S,
    ByteBudget,
    RequestPolicy,
    classify_fetch_error,
    declared_length,
    proxy_refusal,
)
from .profiles import PROFILES
from .settings import Settings

log = logging.getLogger("falcon.sandbox")
ASSET_TYPES = frozenset({"image", "stylesheet", "script", "font", "media"})
FAVICON_MAX_BYTES = 256 * 1024
HARD_TIMEOUT_GRACE_S = 0.5  # keeps one visit under the worker's 7 s wait (TOTAL 6.0 + this)
EXTRACT_TIMEOUT_S = 1.5
FAVICON_TIMEOUT_S = 1.0
SHOT_TIMEOUT_S = 1.2
POST_SAFETY_S = 0.15

try:  # Pillow is a sandbox dependency; hashing degrades to sha256-only without it
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 4_000_000
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]


def image_phash(data: bytes) -> str | None:
    if Image is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            gray = im.convert("RGBA")
            bg = Image.new("RGBA", gray.size, (255, 255, 255, 255))
            gray = Image.alpha_composite(bg, gray).convert("L").resize((32, 32), Image.LANCZOS)
        px = list(gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata())
        return phash_from_gray32([[float(v) for v in px[r * 32 : (r + 1) * 32]] for r in range(32)])
    except Exception:  # noqa: BLE001 - untrusted bytes: any decode failure just means no hash
        return None


@dataclass
class VisitResult:
    features: ProfileFeatures
    dom: str | None = None
    screenshot: bytes | None = None
    redirects: list[dict[str, Any]] = field(default_factory=list)


INTERRUPTED_NAV = "is interrupted by another navigation"
STUB_HEADER = "x-falcon-redirect-stub"
STUB_BODY = b"<!doctype html><title></title>"


@dataclass
class _State:
    blocked: list[BlockedRequest] = field(default_factory=list)
    blocked_total: int = 0
    requests: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    assets: set[str] = field(default_factory=set)
    posts: list[PostTarget] = field(default_factory=list)
    non_get_blocked: int = 0
    non_get_sent: int = 0
    size_cap_hit: bool = False
    redirect_limit_hit: bool = False
    pending: str | None = None
    stub_urls: set[str] = field(default_factory=set)  # hop URLs answered with the inert stub document
    nav_fail: str | None = None
    doc_blocked: bool = False  # a top-level document navigation was refused by policy
    nav_response: Any = None  # last top-level document response seen (client-side redirects)
    hops: list[Hop] = field(default_factory=list)
    nav: list[str] = field(default_factory=list)
    images: dict[str, Any] = field(default_factory=dict)
    inflight: dict[int, str] = field(default_factory=dict)  # request id -> host, for timeout diagnostics
    doc_bytes: int = 0
    doc_fetch_ms: int | None = None
    dcl_ms: int | None = None
    truncated: bool = False
    partial: bool = False


class SandboxBrowser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(settings.max_concurrent)
        self._visits = 0
        self._active = 0
        self._closing: set[asyncio.Future[Any]] = set()

    def _closed(self, task: asyncio.Future[Any]) -> None:
        self._closing.discard(task)
        if not task.cancelled():
            task.exception()  # retrieved: a failed close is not an unhandled error

    async def start(self) -> None:
        await self._launch()

    async def stop(self) -> None:
        if self._browser:
            with contextlib.suppress(PlaywrightError):
                await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = self._pw = None

    async def _launch(self) -> Browser:
        s = self.settings
        if self._pw is None:
            self._pw = await async_playwright().start()
        args = [
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--no-first-run",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        ]
        if s.proxy:
            proxy_host = s.proxy.split("//")[-1].split(":")[0]
            excl = ",".join(f"EXCLUDE {h}" for h in [proxy_host, *sorted(s.allow_hosts)])
            args.append(f"--host-resolver-rules=MAP * ~NOTFOUND,{excl}")
        self._browser = await self._pw.chromium.launch(headless=True, args=args)
        self._visits = 0
        return self._browser

    def _via_proxy(self, host: str) -> bool:
        return bool(self.settings.proxy) and host not in self.settings.allow_hosts

    def _proxy_opts(self) -> dict[str, Any]:
        s = self.settings
        if not s.proxy:
            return {}
        proxy: dict[str, str] = {"server": s.proxy}
        if s.allow_hosts:
            proxy["bypass"] = ",".join(sorted(s.allow_hosts))
        return {"proxy": proxy}

    async def ready(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def _get_browser(self) -> Browser:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                await self._launch()
            elif self._visits >= self.settings.recycle_after and self._active == 0:
                await self._browser.close()
                await self._launch()
            if self._browser is None:
                raise RuntimeError("browser failed to launch")
            self._visits += 1
            self._active += 1
            return self._browser

    async def visit(self, url: str, profile: str, *, visual: bool = False, keep_artifacts: bool = False) -> VisitResult:
        async with self._sem:
            browser = await self._get_browser()
            ctx: BrowserContext | None = None
            try:
                ctx = await browser.new_context(
                    **PROFILES[profile],
                    **self._proxy_opts(),
                    accept_downloads=False,
                    service_workers="block",
                    ignore_https_errors=False,
                    permissions=[],
                )
                return await asyncio.wait_for(
                    self._visit(ctx, url, profile, visual, keep_artifacts), TOTAL_TIMEOUT_S + HARD_TIMEOUT_GRACE_S
                )
            except TimeoutError:
                return VisitResult(
                    ProfileFeatures(
                        profile=profile,  # type: ignore[arg-type]
                        requested_url=url[:512],
                        error="timeout",
                        timed_out=True,
                    )
                )
            except PlaywrightError as exc:
                return VisitResult(
                    ProfileFeatures(
                        profile=profile,  # type: ignore[arg-type]
                        requested_url=url[:512],
                        error=f"browser_error:{str(exc)[:80]}",
                    )
                )
            finally:
                self._active -= 1
                if ctx is not None:
                    # teardown must not eat the caller's time budget: wait briefly, finish in the background
                    task: asyncio.Future[Any] = asyncio.ensure_future(asyncio.wait_for(ctx.close(), 5))
                    self._closing.add(task)
                    task.add_done_callback(self._closed)
                    await asyncio.wait({task}, timeout=0.5)

    async def _visit(self, ctx: BrowserContext, url: str, profile: str, visual: bool, keep: bool) -> VisitResult:
        loop = asyncio.get_running_loop()
        start = loop.time()
        deadline = start + TOTAL_TIMEOUT_S
        nav_deadline = start + min(NAV_BUDGET_S, TOTAL_TIMEOUT_S)
        policy = RequestPolicy(self.settings.guard, visual=visual)
        st = _State()
        budget = ByteBudget(MAX_TOTAL_BYTES)  # sub-resources only; the main document has its own caps

        def remaining_ms() -> int:
            """Navigation budget left (redirect hops + DOMContentLoaded); the rest is kept for extraction."""
            return max(200, int((nav_deadline - loop.time()) * 1000))

        def sub_timeout_ms() -> int:
            return max(200, int(min(SUBRESOURCE_TIMEOUT_S, deadline - loop.time()) * 1000))

        def left_s() -> float:
            return deadline - loop.time() - POST_SAFETY_S

        def record_block(target: str, reason: str, rtype: str) -> None:
            st.blocked_total += 1
            if len(st.blocked) < 30:
                st.blocked.append(
                    BlockedRequest(
                        host=(host_of(target) or target[:60])[:253],
                        reason=reason[:40],
                        resource_type=rtype[:20],
                    )
                )

        async def handler(route: Route) -> None:
            req = route.request
            st.requests += 1
            st.by_type[req.resource_type] = st.by_type.get(req.resource_type, 0) + 1
            d = policy.decide(req.url, req.method, req.resource_type, 0)
            if not d.allow:
                record_block(req.url, d.reason, req.resource_type)
                if req.is_navigation_request() and req.frame.parent_frame is None:
                    st.doc_blocked = True
                    st.nav_fail = st.nav_fail or f"blocked_by_policy:{d.reason}"[:60]
                if d.reason == "method_not_get":
                    st.non_get_blocked += 1
                    tgt = build_dynamic_post_target(req.url, req.resource_type, url)
                    if tgt and len(st.posts) < 20:
                        st.posts.append(tgt)
                with contextlib.suppress(PlaywrightError):
                    await route.abort("blockedbyclient")
                return
            main_nav = req.is_navigation_request() and req.frame.parent_frame is None
            if req.resource_type in ASSET_TYPES and not main_nav:
                h = host_of(req.url)
                if h:
                    st.assets.add(h)
            # Every request is fetched here WITHOUT following redirects (Chromium would follow up
            # to 20 hops internally and never re-enter this handler), so each hop is re-validated
            # against the SSRF policy, counted, and its bytes are capped. The proxy still applies.
            if not main_nav and budget.exhausted:
                # sub-resource budget spent: refuse WITHOUT fetching; the page itself is still judged
                st.size_cap_hit = True
                record_block(req.url, "size_cap", req.resource_type)
                with contextlib.suppress(PlaywrightError):
                    await route.abort("blockedbyclient")
                return
            target = req.url
            hops = 0
            t_req = loop.time()
            st.inflight[id(req)] = host_of(req.url) or ""
            try:
                while True:
                    resp = await route.fetch(
                        url=target, max_redirects=0, timeout=remaining_ms() if main_nav else sub_timeout_ms()
                    )
                    declared = declared_length(resp.headers)
                    over = declared is not None and (
                        declared > MAIN_DOC_HARD_BYTES if main_nav else budget.would_exceed(declared)
                    )
                    if over:
                        # refuse BEFORE the body is transferred out of the Playwright driver
                        st.size_cap_hit = True
                        if main_nav:
                            st.nav_fail = "size_cap"
                        with contextlib.suppress(PlaywrightError):
                            await route.abort("blockedbyclient")
                        return
                    body = await resp.body()
                    if main_nav:
                        st.doc_fetch_ms = int((loop.time() - t_req) * 1000)
                    location = resp.headers.get("location")
                    if not (300 <= resp.status < 400 and location):
                        break
                    if main_nav:
                        # hand the hop to the visit loop, which re-validates and navigates
                        st.hops.append(Hop(url=target[:512], status=resp.status))
                        st.pending = urljoin(target, location)
                        # NOT route.abort(): that commits a chrome-error page which races (and
                        # interrupts) the next navigation, ending as a bare blocked_by_policy for
                        # ordinary 301/302 chains. A tiny inert stub document commits cleanly and
                        # is superseded by the next goto.
                        st.stub_urls.add(target)
                        with contextlib.suppress(PlaywrightError):
                            await route.fulfill(
                                status=200,
                                headers={STUB_HEADER: "1", "content-type": "text/html", "cache-control": "no-store"},
                                body=STUB_BODY,
                            )
                        return
                    hops += 1
                    target = urljoin(target, location)
                    nd = policy.decide(target, "GET", req.resource_type, 0)
                    if hops > MAX_REDIRECTS or not nd.allow:
                        record_block(target, nd.reason or "too_many_redirects", req.resource_type)
                        with contextlib.suppress(PlaywrightError):
                            await route.abort("blockedbyclient")
                        return
            except PlaywrightError as exc:
                if main_nav:
                    st.nav_fail = classify_fetch_error(str(exc))
                with contextlib.suppress(PlaywrightError):
                    await route.abort("failed")
                return
            finally:
                st.inflight.pop(id(req), None)
            if main_nav:
                refusal = proxy_refusal(resp.status, resp.headers, len(body), self._via_proxy(host_of(req.url)))
                if refusal:
                    st.nav_fail = refusal
                    with contextlib.suppress(PlaywrightError):
                        await route.abort("failed")
                    return
            if main_nav:
                if len(body) > MAIN_DOC_MAX_BYTES:
                    # cut, don't fail: the part we have is still evidence (truncated=true, weight 0)
                    body = body[:MAIN_DOC_MAX_BYTES]
                    st.truncated = True
                    st.size_cap_hit = True
                st.doc_bytes = len(body)
            elif budget.add(len(body)):
                st.size_cap_hit = True
                record_block(req.url, "size_cap", req.resource_type)
                with contextlib.suppress(PlaywrightError):
                    await route.abort("blockedbyclient")
                return
            headers = {
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
            }
            with contextlib.suppress(PlaywrightError):
                await route.fulfill(status=resp.status, headers=headers, body=body)

        await ctx.route("**/*", handler)
        with contextlib.suppress(Exception):
            await ctx.route_web_socket("**/*", lambda ws: asyncio.ensure_future(ws.close()))
        page = await ctx.new_page()
        ctx.on("page", lambda p: asyncio.ensure_future(p.close()) if p is not page else None)
        page.on("dialog", lambda dlg: asyncio.ensure_future(dlg.dismiss()))
        page.on("download", lambda dl: asyncio.ensure_future(dl.cancel()))
        page.on(
            "framenavigated",
            lambda f: st.nav.append(f.url[:512]) if f == page.main_frame and f.url not in st.stub_urls else None,
        )
        page.on(
            "requestfinished",
            lambda r: (
                setattr(st, "non_get_sent", st.non_get_sent + 1) if r.method.upper() not in ("GET", "HEAD") else None
            ),
        )
        page.on("response", lambda r: st.images.__setitem__(r.url, r) if len(st.images) < 60 else None)
        page.on(
            "response",
            lambda r: (
                setattr(st, "nav_response", r)
                if r.request.is_navigation_request()
                and r.frame == page.main_frame
                and not 300 <= r.status < 400
                and STUB_HEADER not in r.headers
                else None
            ),
        )

        feats = ProfileFeatures(profile=profile, requested_url=url[:512])  # type: ignore[arg-type]
        response = None
        nav_error: str | None = None

        async def settle_interrupted() -> None:
            nonlocal response, nav_error
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=remaining_ms())
            except PlaywrightTimeout:
                feats.timed_out = True
                return
            except PlaywrightError as exc:
                nav_error = f"navigation_failed:{str(exc).splitlines()[0][:80]}"
                return
            if st.doc_blocked or not policy.decide(page.url, "GET", "document").allow:
                # fail closed: wherever the page ended up must pass the same policy
                if not st.doc_blocked:
                    record_block(page.url, "blocked_final_url", "document")
                nav_error = st.nav_fail or "blocked_by_policy:blocked_final_url"
                return
            response = st.nav_response  # None when no document actually loaded

        async def go(target: str) -> None:
            nonlocal response, nav_error
            nav_error = None
            response = None  # a timeout/failure must never leave the previous hop's response behind
            try:
                got = await page.goto(target, wait_until="domcontentloaded", timeout=remaining_ms())
                st.dcl_ms = int((loop.time() - start) * 1000)
                # fail closed: the inert redirect stub is never a page (only the next goto's result is)
                response = None if got is not None and STUB_HEADER in got.headers else got
            except PlaywrightTimeout:
                feats.timed_out = True
            except PlaywrightError as exc:
                msg = str(exc)
                if INTERRUPTED_NAV in msg:
                    # A client-side redirect (JS / meta refresh) started a second navigation while
                    # the first was loading. Not a failure: wait for the document it lands on.
                    await settle_interrupted()
                    return
                nav_error = (
                    (st.nav_fail or "blocked_by_policy:blocked_by_client")
                    if "BLOCKED_BY_CLIENT" in msg
                    else f"navigation_failed:{msg.splitlines()[0][:80]}"
                )

        async def follow_redirects() -> None:
            n = 0
            while st.pending and not feats.error:
                nxt, st.pending = st.pending, None
                n += 1
                if n > MAX_REDIRECTS:
                    st.redirect_limit_hit = True
                    feats.error = "too_many_redirects"
                    return
                d = policy.decide(nxt, "GET", "document")
                if not d.allow:
                    st.blocked_total += 1
                    st.blocked.append(
                        BlockedRequest(
                            host=(host_of(nxt) or nxt[:60])[:253],
                            reason=d.reason[:40],
                            resource_type="document",
                        )
                    )
                    feats.error = f"blocked_by_policy:{d.reason}"[:60]
                    return
                await go(nxt)

        await go(url)
        await follow_redirects()
        if response is None and feats.timed_out and not st.pending and not feats.error and not st.doc_blocked:
            # The navigation budget ran out but a real document had already answered (a slow script or
            # frame is holding DOMContentLoaded): judge what has loaded instead of failing the visit.
            nr = st.nav_response
            if nr is not None and policy.decide(page.url, "GET", "document").allow:
                response, feats.timed_out, st.partial = nr, False, True
        if response is not None and not st.pending and not st.partial:
            settle = min(1.5, max(0.0, nav_deadline - loop.time()))
            if settle > 0.05:
                with contextlib.suppress(PlaywrightTimeout, PlaywrightError):
                    await page.wait_for_load_state("load", timeout=int(settle * 1000))
            if left_s() > 1.8:
                await asyncio.sleep(0.3)
            await follow_redirects()  # redirects triggered by scripts/meta refresh
        if st.doc_blocked and response is not None and not feats.error and not st.pending:
            nav_error = nav_error or st.nav_fail or "blocked_by_policy:blocked_final_url"  # client redirect refused
        if (st.nav_fail or nav_error) and not feats.error and not st.pending:
            feats.error = st.nav_fail or nav_error
        if response is None and not feats.error and not st.pending:
            feats.error = "timeout" if feats.timed_out else "no_response"
        if response is not None and not feats.error:
            st.hops.append(Hop(url=response.request.url[:512], status=response.status))
        hops = st.hops
        redirects: list[dict[str, Any]] = [h.model_dump() for h in hops]
        feats.redirect_chain = hops
        feats.status = response.status if response and not feats.error else None

        dom: str | None = None
        shot: bytes | None = None
        raw: dict[str, Any] | None = None
        if response is not None and not feats.error:
            feats.final_url = page.url[:512]
            raw = await self._extract(page, left_s)
        if raw is None and response is not None and not feats.error and st.partial:
            # nothing usable came out of a half-loaded page: that is a timeout, not a rendered empty page
            feats.error, feats.timed_out, feats.final_url = "timeout", True, None
        elif raw is None and response is not None and not feats.error and not feats.timed_out:
            feats.error = "extract_failed"
        if raw is not None:
            final = page.url
            feats.title = str(raw.get("title", ""))[:300]
            feats.lang = str(raw.get("lang", ""))[:20]
            feats.visible_text = truncate_utf8(str(raw.get("text", "")))
            feats.forms = build_forms(raw.get("forms", []), final)
            feats.js = build_js(raw.get("js", {}))
            feats.script_post_targets = [
                *build_static_post_targets(raw.get("typed", []), raw.get("literals", []), final),
                *st.posts,
            ][:40]
            feats.dom_simhash = dom_simhash(raw.get("struct", []))
            fh = host_of(final)
            feats.asset_origins = sorted(h for h in st.assets if not same_site(h, fh))[:30]
            feats.client_navigations = st.nav[1:][:10]

            # favicon and screenshot are optional extras: run together, each inside what is left of the budget
            async def get_favicon() -> Favicon:
                with contextlib.suppress(PlaywrightError, TimeoutError):
                    return await asyncio.wait_for(
                        self._favicon(page, st, str(raw.get("favicon", "")), policy),
                        max(0.05, min(FAVICON_TIMEOUT_S, left_s())),
                    )
                return Favicon()

            async def get_shot() -> bytes | None:
                with contextlib.suppress(PlaywrightError, TimeoutError):
                    return await page.screenshot(
                        type="png", timeout=int(max(0.1, min(SHOT_TIMEOUT_S, left_s())) * 1000)
                    )
                return None

            feats.favicon, shot = await asyncio.gather(get_favicon(), get_shot())
            if shot:
                feats.screenshot_sha256 = hashlib.sha256(shot).hexdigest()
                feats.screenshot_phash = image_phash(shot)
            if keep:
                with contextlib.suppress(PlaywrightError, TimeoutError):
                    dom = await asyncio.wait_for(page.content(), max(0.2, left_s()))
        elif st.posts:
            feats.script_post_targets = st.posts[:20]
        feats.network = NetworkSummary(
            requests=st.requests,
            bytes=budget.total + st.doc_bytes,
            by_type=st.by_type,
            blocked=st.blocked,
            blocked_total=st.blocked_total,
            non_get_sent=st.non_get_sent,
            non_get_blocked=st.non_get_blocked,
            size_cap_hit=st.size_cap_hit,
            redirect_limit_hit=st.redirect_limit_hit,
            doc_bytes=st.doc_bytes,
            doc_fetch_ms=st.doc_fetch_ms,
            dcl_ms=st.dcl_ms,
            truncated=st.truncated,
            partial=st.partial,
            pending_hosts=sorted({h for h in st.inflight.values() if h})[:8],
        )
        # size_cap_hit is telemetry: only a main document refused outright (nav_fail) is an error.
        return VisitResult(feats, dom=dom, screenshot=shot, redirects=redirects)

    @staticmethod
    async def _extract(page: Page, left_s: Callable[[], float]) -> dict[str, Any] | None:
        for _ in range(2):
            budget = min(EXTRACT_TIMEOUT_S, left_s())
            if budget < 0.1:
                return None
            try:
                out = await asyncio.wait_for(page.evaluate(EXTRACT_JS), budget)
                return out if isinstance(out, dict) else None
            except (PlaywrightError, TimeoutError):
                with contextlib.suppress(PlaywrightError, TimeoutError):
                    wait = max(0.05, min(0.5, left_s()))
                    await page.wait_for_load_state("domcontentloaded", timeout=int(wait * 1000))
        return None

    @staticmethod
    async def _favicon(page: Page, st: _State, url: str, policy: RequestPolicy) -> Favicon:
        if not url or not url.startswith(("http://", "https://")) or not policy.decide(url, "GET", "image").allow:
            return Favicon()
        resp = st.images.get(url)
        if resp is None:
            with contextlib.suppress(PlaywrightError, TimeoutError):
                await page.evaluate("u => { const i = new Image(); i.src = u; }", url)
                t0 = time.monotonic()
                while url not in st.images and time.monotonic() - t0 < 1.5:
                    await asyncio.sleep(0.05)
            resp = st.images.get(url)
        if resp is None or resp.status != 200:
            return Favicon()
        try:
            body = await asyncio.wait_for(resp.body(), 2)
        except (PlaywrightError, TimeoutError):
            return Favicon()
        if len(body) > FAVICON_MAX_BYTES:
            return Favicon()
        h = host_of(url)
        return Favicon(
            origin=h,
            sha256=hashlib.sha256(body).hexdigest(),
            phash=image_phash(body),
        )
