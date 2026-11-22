# Falcon Lens extension: privacy and permissions

This file describes what the shipped code does. If the code and this file disagree, the code is a bug.

## What leaves your device

**One thing: the address (URL) being checked**, sent to the check server you configured
(`POST {API}/v1/check/url?wait=6`, body `{"url": "..."}`).

A URL is sent only in these three cases:

| When | Which URL |
|---|---|
| The on-device check interrupts a navigation and shows the warning page | the address you were about to open |
| You rest the pointer (or keyboard focus) on a link for 400 ms in a listed webmail or chat app | that link's address |
| You open the popup | the current tab's address |

Addresses that the on-device check does not flag are **not** sent when you simply browse.
The `#fragment` part of a URL is removed before sending. No cookies, no referrer, no page content,
no form data, no identifiers and no browsing history are sent. Requests use `credentials: "omit"`
and `referrerPolicy: "no-referrer"`. The optional API key, when you set one, goes in the
`X-API-Key` header to the check server only.

Turn off "Confirm results with a deeper server check" in the options page and nothing is sent at
all: the extension then works from the on-device check only.

## What is stored

| Data | Where | For how long |
|---|---|---|
| Settings: server address, optional API key, web app address, language, server checks on/off | `chrome.storage.local` (this device, not synced) | until you change them or remove the extension |
| Verdicts for checked URLs | `chrome.storage.session` (memory only, never written to disk) | 10 minutes, at most 200 entries, cleared when the browser closes |
| "Continue at my own risk" choices, per site | `chrome.storage.session` | 10 minutes |
| A marker per open tab that a warned page had already loaded, so "Go back" skips it | `chrome.storage.session` | until the tab closes |

There is no browsing-history log, no analytics and no telemetry. Both storage areas are set to
`TRUSTED_CONTEXTS`, so the script that runs inside webmail pages cannot read the API key or the cache.

## Permissions, one by one

| Permission | Why it is needed | What it is not used for |
|---|---|---|
| `webNavigation` | To see the address of a top-frame navigation as it starts, run the on-device check, and replace a risky navigation with the warning page before you can type. | Sub-frames are ignored. Addresses are not logged or sent unless the on-device check flags them. |
| `storage` | Settings, and the 10-minute in-memory cache described above. | No sync storage. |
| `activeTab` | To read the current tab's address when you open the popup. | No access to page content. No access to tabs you have not opened the popup on. |
| Host permission: **the API origin only** (set at build time, `https://localhost/*` by default) | To send the URL to the check server from the service worker. | No `<all_urls>`. |
| Optional host permissions (`https://*/*`, `http://localhost/*`, `http://127.0.0.1/*`) | Granted **only** when you save a different server address in the options page; Chrome asks you, and only for that one origin. | Nothing is requested at install. |
| Content script on `mail.google.com`, `outlook.live.com`, `outlook.office.com`, `web.whatsapp.com`, `web.telegram.org` | The hover badge. It reads the address of the link under the pointer and nothing else. | It does not read messages, contacts or anything you type. It is not injected anywhere else. |

Not requested: `tabs`, `scripting`, `webRequest`, `declarativeNetRequest`, `cookies`, `history`,
`<all_urls>`. The hover script is declared statically for the five hosts above, so the `scripting`
permission is not needed. The warning page is opened by the extension itself, so no
`web_accessible_resources` are exposed to web pages.

## No remote code

Everything is bundled at build time: scripts, styles, fonts (Readex Pro, JetBrains Mono, SIL OFL),
icons and the brand list generated from `data/brands.yaml`. The extension pages run under this
Content Security Policy:

```
default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:;
connect-src 'self' https: http://localhost:* http://127.0.0.1:*; object-src 'none'; base-uri 'none';
form-action 'none'; frame-ancestors 'none'
```

No `unsafe-inline`, no `unsafe-eval`, no WebAssembly. Text from the server and from URLs is written
through DOM text nodes only; `scripts/check-static.mjs` fails the build on `innerHTML` and similar.

## Limits you should know

- The on-device check is a small lexical filter. It can miss scams and it can flag honest sites
  that carry a known name in their address. The server verdict then corrects the warning page.
- When a risky navigation is replaced, the browser may already have sent the first request to that
  site. The page is not displayed and you cannot type into it, but the site can see that a request
  arrived.
- The extension never says a site is safe. The lowest result is "No warning signs found", always
  with a reminder to stay careful.
- This is an independent project. It is not affiliated with, endorsed by or integrated with any
  police force, bank or government entity. Brand names appear as text only, to tell you which name
  an address is imitating.
