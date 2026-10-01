import { createOrb, type OrbState } from "./orb";
import { createAudioPlayer } from "./voice";
import { createSocket } from "./ws";
import { requireSession } from "./auth";
import "./local.css";

await requireSession();

type State = "idle" | "listening" | "thinking" | "speaking";
const orb = createOrb(document.getElementById("orb-canvas") as HTMLCanvasElement);
const player = createAudioPlayer();
orb.setAnalyser(player.getAnalyser());
const status = document.getElementById("status-text") as HTMLDivElement;
const transcript = document.getElementById("transcript") as HTMLDivElement;
const reply = document.getElementById("reply") as HTMLDivElement;
const confirmButton = document.getElementById("confirm-button") as HTMLButtonElement;
let confirmationToken = "";
const recordButton = document.getElementById("record-button") as HTMLButtonElement;
const form = document.getElementById("command-form") as HTMLFormElement;
const input = document.getElementById("command-input") as HTMLInputElement;
const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
const socket = createSocket(`${wsProto}//${window.location.host}/ws/voice`);
let recorder: MediaRecorder | null = null;
let stream: MediaStream | null = null;
let chunks: Blob[] = [];

function state(next: State, label: string = next) {
  orb.setState(next as OrbState);
  status.textContent = label;
}

function submit(text: string) {
  const cleaned = text.trim().replace(/^hey jarvis[,\s]*/i, "");
  if (!cleaned) return;
  if (!socket.isConnected()) {
    reply.textContent = "Voice socket is reconnecting. Please try again.";
    state("idle");
    return;
  }
  transcript.textContent = cleaned;
  reply.textContent = "";
  confirmButton.hidden = true;
  confirmationToken = "";
  player.stop();
  socket.send({ type: "transcript", text: cleaned });
  state("thinking");
}

form.addEventListener("submit", event => {
  event.preventDefault();
  submit(input.value);
  input.value = "";
});

recordButton.addEventListener("click", async () => {
  if (recorder?.state === "recording") {
    recorder.stop();
    recordButton.textContent = "Processing...";
    recordButton.disabled = true;
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunks = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = async () => {
      stream?.getTracks().forEach(track => track.stop());
      const data = new FormData();
      data.append("file", new Blob(chunks, { type: recorder?.mimeType || "audio/webm" }), "command.webm");
      try {
        const response = await fetch("/api/v2/audio/transcribe", { method: "POST", body: data });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Transcription failed");
        submit(body.text);
      } catch (error) {
        reply.textContent = String(error);
        state("idle");
      } finally {
        recordButton.disabled = false;
        recordButton.textContent = "Record command";
      }
    };
    recorder.start();
    recordButton.textContent = "Stop recording";
    state("listening", "recording...");
  } catch (error) {
    reply.textContent = `Microphone error: ${error}`;
    state("idle");
  }
});

socket.onMessage(msg => {
  if (msg.type === "status") {
    if (msg.state === "thinking") state("thinking");
    if (msg.state === "idle" && !reply.textContent) state("idle");
  } else if (msg.type === "text") {
    reply.textContent = String(msg.text || "");
    if (msg.confirmation_token) {
      confirmationToken = String(msg.confirmation_token);
      confirmButton.hidden = false;
    }
    state("idle");
  } else if (msg.type === "audio" && msg.data) {
    state("speaking");
    player.enqueue(String(msg.data));
  }
});
confirmButton.addEventListener("click", async () => {
  confirmButton.hidden = true;
  const token = confirmationToken;
  confirmationToken = "";
  const response = await fetch(`/api/v2/assistant/confirm/${encodeURIComponent(token)}`, { method: "POST" });
  const body = await response.json();
  reply.textContent = body.text || body.detail || "Confirmation failed";
});
player.onFinished(() => state("idle"));
state("idle", "ready");
