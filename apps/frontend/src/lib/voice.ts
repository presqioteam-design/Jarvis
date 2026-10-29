/**
 * A live voice call with Jarvis (Gemini Live over a WebSocket).
 * Mic → 16 kHz PCM chunks → Gemini; Gemini's 24 kHz PCM → speakers.
 * The token comes from our API, so the Gemini key never reaches the browser.
 */
import { startVoiceSession, voiceCommand } from "./api";

export type CallState = "connecting" | "listening" | "thinking" | "speaking" | "ended" | "error";

type Events = {
  state: (s: CallState) => void;
  caption: (who: "you" | "jarvis", text: string) => void;
  error: (message: string) => void;
  /** Today's allowance, known once the call is set up. */
  info: (i: { callsLeft: number; callsPerDay: number; maxSeconds: number }) => void;
};

// Runs on the audio thread: averages the mic down to 16 kHz and sends 40 ms Int16 chunks.
const MIC_WORKLET = `
class Mic16k extends AudioWorkletProcessor {
  constructor() { super(); this.ratio = sampleRate / 16000; this.pos = 0; this.acc = 0; this.n = 0; this.buf = []; }
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i]; this.n++; this.pos++;
      if (this.pos >= this.ratio) { this.pos -= this.ratio; this.buf.push(this.acc / this.n); this.acc = 0; this.n = 0; }
    }
    if (this.buf.length >= 640) {
      const out = new Int16Array(this.buf.length);
      for (let i = 0; i < out.length; i++) { const s = Math.max(-1, Math.min(1, this.buf[i])); out[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
      this.port.postMessage(out.buffer, [out.buffer]);
      this.buf = [];
    }
    return true;
  }
}
registerProcessor("mic-16k", Mic16k);
`;

const toBase64 = (buf: ArrayBuffer) => {
  let s = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};

function level(an: AnalyserNode | null, data: Uint8Array<ArrayBuffer>): number {
  if (!an) return 0;
  an.getByteTimeDomainData(data);
  let sum = 0;
  for (const v of data) sum += ((v - 128) / 128) ** 2;
  return Math.min(1, Math.sqrt(sum / data.length) * 4);
}

export class VoiceCall {
  state: CallState = "connecting";
  private ws?: WebSocket;
  private stream?: MediaStream;
  private micCtx?: AudioContext;
  private outCtx?: AudioContext;
  private micAn: AnalyserNode | null = null;
  private outAn: AnalyserNode | null = null;
  private outGain?: GainNode;
  private nextTime = 0;
  private playing = new Set<AudioBufferSourceNode>();
  private you = "";
  private jarvis = "";
  private muted = false;
  private buf = new Uint8Array(new ArrayBuffer(512));
  private timers: number[] = [];
  // Kept as fields on purpose: if nothing references the mic nodes, the browser's garbage
  // collector can remove them mid-call and your voice silently stops reaching Jarvis.
  private micSrc?: MediaStreamAudioSourceNode;
  private micNode?: AudioWorkletNode;
  private micSink?: GainNode;
  private lastChunk = 0;
  private workletUrl = URL.createObjectURL(new Blob([MIC_WORKLET], { type: "text/javascript" }));

  constructor(private on: Events) {}

  /** Must be called from a click: browsers only allow audio after a user gesture. */
  async start() {
    this.set("connecting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch {
      return this.fail("Microphone access was blocked. Allow the mic for this site and try again.");
    }
    this.outCtx = new AudioContext({ sampleRate: 24000 });
    this.outGain = this.outCtx.createGain();
    this.outAn = this.outCtx.createAnalyser();
    this.outGain.connect(this.outAn).connect(this.outCtx.destination);

    // set up audio and ask the server for the call at the same time
    const session = startVoiceSession();
    session.catch(() => undefined); // handled below; avoids an unhandled-rejection warning meanwhile
    await this.startMic();
    // watchdog: if the mic stops delivering audio (the tab was backgrounded, the browser paused audio,
    // or a device changed), rebuild it instead of leaving a call where Jarvis can't hear you
    this.timers.push(window.setInterval(() => this.checkMic(), 1500));

    let url: string;
    try {
      const s = await session;
      url = s.url;
      this.on.info(s);
      // daily-limit guard: Jarvis wraps up a minute before the end, then the call closes
      this.timers.push(
        window.setTimeout(() => this.say("One minute is left in this call. Tell the admin briefly and wrap up soon."), (s.maxSeconds - 60) * 1000),
        window.setTimeout(() => this.fail(`Calls are limited to ${Math.round(s.maxSeconds / 60)} minutes to stay within the free voice allowance. Call again if you need more.`), s.maxSeconds * 1000),
      );
    } catch (e) {
      return this.fail(e instanceof Error && e.message ? e.message : "Couldn't reach Jarvis. The server may be waking up; try again in a minute.");
    }
    this.ws = new WebSocket(url);
    this.ws.onopen = () => this.ws!.send(JSON.stringify({ setup: {} }));
    this.ws.onmessage = (e) => this.handle(e.data);
    this.ws.onclose = (e) => {
      if (this.state !== "ended" && this.state !== "error") {
        e.code === 1000 ? this.stop() : this.fail(e.reason ? `Call dropped: ${e.reason}` : "The call dropped. Tap to call again.");
      }
    };
  }

  private async startMic() {
    if (!this.stream || this.stream.getAudioTracks().every((t) => t.readyState === "ended")) {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    }
    this.micCtx = new AudioContext();
    await this.micCtx.audioWorklet.addModule(this.workletUrl);
    this.micSrc = this.micCtx.createMediaStreamSource(this.stream);
    this.micAn = this.micCtx.createAnalyser();
    this.micNode = new AudioWorkletNode(this.micCtx, "mic-16k");
    // a silent path to the speakers keeps Chrome processing the worklet for the whole call
    this.micSink = this.micCtx.createGain();
    this.micSink.gain.value = 0;
    this.micSrc.connect(this.micAn);
    this.micSrc.connect(this.micNode).connect(this.micSink).connect(this.micCtx.destination);
    this.lastChunk = performance.now();
    this.micNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      this.lastChunk = performance.now();
      if (this.ws?.readyState === WebSocket.OPEN && !this.muted && this.state !== "connecting") {
        this.ws.send(JSON.stringify({ realtimeInput: { audio: { data: toBase64(e.data), mimeType: "audio/pcm;rate=16000" } } }));
      }
    };
  }

  private restarting = false;

  private async checkMic() {
    if (this.restarting || this.state === "ended" || this.state === "error" || !this.micCtx) return;
    if (this.micCtx.state === "suspended") await this.micCtx.resume().catch(() => undefined);
    if (this.outCtx?.state === "suspended") await this.outCtx.resume().catch(() => undefined);
    if (performance.now() - this.lastChunk < 3000) return;
    this.restarting = true;   // no audio for 3 s: rebuild the mic chain
    try {
      this.micSrc?.disconnect();
      this.micNode?.disconnect();
      await this.micCtx.close().catch(() => undefined);
      await this.startMic();
    } catch {
      this.fail("The microphone stopped. Check that it's connected and allowed, then call again.");
    } finally {
      this.restarting = false;
    }
  }

  private async handle(raw: string | Blob) {
    const m = JSON.parse(typeof raw === "string" ? raw : await raw.text());
    if (m.setupComplete) {
      this.set("listening");
      // greet first, so it feels like Jarvis picked up
      this.say("The admin just opened the call. Greet them in English in a few words, like a quick hello, then wait.");
      return;
    }
    if (m.toolCall) {
      this.set("thinking");
      const responses = [];
      for (const fc of m.toolCall.functionCalls ?? []) {
        let result: string;
        try {
          result = (await voiceCommand(String(fc.args?.command ?? ""))).result;
        } catch {
          result = "That didn't work: the server didn't answer.";
        }
        responses.push({ id: fc.id, name: fc.name, response: { result } });
      }
      this.ws?.send(JSON.stringify({ toolResponse: { functionResponses: responses } }));
      return;
    }
    if (m.goAway) {
      this.on.caption("jarvis", "The voice service is ending this call shortly. Tap “Call again” if you need more.");
      return;
    }
    const sc = m.serverContent;
    if (!sc) return;
    if (sc.interrupted) this.flush(); // you spoke over Jarvis: stop talking at once
    if (sc.inputTranscription?.text) {
      if (this.jarvis) { this.jarvis = ""; this.you = ""; }
      this.you += sc.inputTranscription.text;
      this.on.caption("you", this.you.trim());
    }
    if (sc.outputTranscription?.text) {
      this.jarvis += sc.outputTranscription.text;
      this.on.caption("jarvis", this.jarvis.trim());
    }
    for (const p of sc.modelTurn?.parts ?? []) {
      if (p.inlineData?.data) this.play(p.inlineData.data);
    }
    if (sc.turnComplete) {
      this.you = "";
      if (!this.playing.size) this.set("listening");
    }
  }

  /** A text nudge to Jarvis (not shown or spoken as yours). */
  private say(text: string) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ realtimeInput: { text } }));
  }

  private play(b64: string) {
    const ctx = this.outCtx!;
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const pcm = new Int16Array(bytes.buffer, 0, bytes.length >> 1);
    const buffer = ctx.createBuffer(1, pcm.length, 24000);
    const ch = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.outGain!);
    this.nextTime = Math.max(this.nextTime, ctx.currentTime + 0.04);
    src.start(this.nextTime);
    this.nextTime += buffer.duration;
    this.playing.add(src);
    this.set("speaking");
    src.onended = () => {
      this.playing.delete(src);
      if (!this.playing.size && this.state === "speaking") this.set("listening");
    };
  }

  private flush() {
    this.playing.forEach((s) => s.stop());
    this.playing.clear();
    this.nextTime = 0;
  }

  /** 0..1 loudness of whoever is talking, for the orb. */
  levels(): { you: number; jarvis: number } {
    return { you: this.muted ? 0 : level(this.micAn, this.buf), jarvis: level(this.outAn, this.buf) };
  }

  setMuted(m: boolean) {
    this.muted = m;
  }

  stop() {
    this.timers.forEach((t) => { clearTimeout(t); clearInterval(t); });
    this.timers = [];
    this.micSrc?.disconnect();
    this.micNode?.disconnect();
    this.flush();
    this.ws?.close(1000);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.micCtx?.close();
    this.outCtx?.close();
    this.set("ended");
  }

  private fail(message: string) {
    this.on.error(message);
    this.stop();
    this.set("error");
  }

  private set(s: CallState) {
    if (this.state === s) return;
    this.state = s;
    this.on.state(s);
  }
}
