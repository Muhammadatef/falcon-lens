/* eslint-disable @typescript-eslint/no-explicit-any */
import type { Page } from "@playwright/test";

/** Fake microphone, voice-activity input, recorder, clipboard and speech engine (no real audio device is needed). */
export async function installMocks(page: Page) {
  await page.addInitScript(() => {
    const w = window as any;
    w.__level = 0;
    w.__voice = "noise";
    w.__tok = Math.random().toString(36).slice(2, 10);
    w.__spoken = [];
    w.__clip = "";
    w.__clipDenied = false;
    w.__gum = 0;
    w.__gumDenied = false;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => {
          w.__gum += 1;
          if (w.__gumDenied) throw new DOMException("denied", "NotAllowedError");
          return { getTracks: () => [{ stop() {} }] };
        },
      },
    });
    w.AudioContext = class {
      state = "running";
      createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
      createAnalyser() { return { fftSize: 1024, connect() {}, getFloatTimeDomainData(b: Float32Array) { b.fill(w.__level); } }; }
      resume() { return Promise.resolve(); }
      close() { return Promise.resolve(); }
    };
    w.MediaRecorder = class extends EventTarget {
      static isTypeSupported() { return true; }
      start() {}
      stop() {
        const ev: any = new Event("dataavailable");
        ev.data = new Blob([`VOICE:${w.__voice};T:${w.__tok}`], { type: "audio/webm;codecs=opus" });
        this.dispatchEvent(ev);
        this.dispatchEvent(new Event("stop"));
      }
    };
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { readText: async () => { if (w.__clipDenied) throw new DOMException("denied", "NotAllowedError"); return w.__clip; } },
    });
    const voices = [{ name: "Majed", lang: "ar-SA", localService: true }, { name: "Daniel", lang: "en-GB", localService: true }];
    class Utt { text: string; lang = ""; voice: unknown = null; rate = 1; pitch = 1; onend: null | (() => void) = null; onerror: null | (() => void) = null; constructor(t: string) { this.text = t; } }
    w.SpeechSynthesisUtterance = Utt;
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        getVoices: () => voices,
        speak(u: Utt) { w.__spoken.push({ text: u.text, lang: u.lang }); setTimeout(() => u.onend?.(), 15); },
        cancel() {},
        addEventListener() {},
        removeEventListener() {},
      },
    });
  });
}

/** Speaks one utterance: loud for ~1 s, then silent until the detector ends it. */
export async function say(page: Page, voice: string) {
  await page.evaluate((v) => { (window as any).__voice = v; (window as any).__level = 0.3; }, voice);
  await page.waitForTimeout(1000);
  await page.evaluate(() => { (window as any).__level = 0; });
}

