import { useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Mic, Square, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError, apiGet, apiUpload } from "@/lib/api";
import { describe } from "@/lib/interaction";
import { useI18n } from "@/lib/i18n/I18nProvider";

type Status = { speech_to_text: boolean; text_to_speech: boolean };
const useVoiceStatus = () => useQuery({ queryKey: ["voice-status"], queryFn: () => apiGet<Status>("/voice/status"), retry: false, staleTime: 300_000 });

const canRecord = () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

/** A microphone button: speak a question in any language and the words are added to the box. Recordings are never stored. */
export function VoiceInput({ onText }: { onText: (text: string) => void }) {
  const { t } = useI18n();
  const { data } = useVoiceStatus();
  const [state, setState] = useState<"idle" | "recording" | "working">("idle");
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  if (!data?.speech_to_text || !canRecord()) return null;

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const type = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm"].find((m) => MediaRecorder.isTypeSupported(m));
      const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      chunks.current = [];
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop()); // release the microphone at once
        setState("working");
        try {
          const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
          const ext = blob.type.includes("ogg") ? "ogg" : "webm";
          const out = await apiUpload<{ text: string }>("/voice/transcribe", new File([blob], `speech.${ext}`, { type: blob.type }));
          if (out.text) onText(out.text);
          else toast.info(t("voice.err"));
        } catch (e) {
          toast.error(e instanceof ApiError && e.status === 429 ? describe(e) : t("voice.err"));
        } finally {
          setState("idle");
        }
      };
      rec.current = mr;
      mr.start();
      setState("recording");
      window.setTimeout(() => mr.state === "recording" && mr.stop(), 120_000); // never record for more than two minutes
    } catch {
      toast.error(t("voice.err"));
      setState("idle");
    }
  }

  return state === "recording" ? (
    <Button type="button" variant="destructive" size="sm" onClick={() => rec.current?.stop()} data-testid="voice-stop">
      <Square /> {t("voice.stop")}
    </Button>
  ) : (
    <Button type="button" variant="outline" size="sm" loading={state === "working"} onClick={start} data-testid="voice-start">
      <Mic /> {t("voice.speak")}
    </Button>
  );
}

/** Reads text aloud: a natural voice from the server when it is set up, otherwise the browser's own voice. */
export function ListenButton({ text }: { text: string }) {
  const { t, lang } = useI18n();
  const { data } = useVoiceStatus();
  const [busy, setBusy] = useState(false);
  const browserVoice = typeof window !== "undefined" && "speechSynthesis" in window;
  if (!data?.text_to_speech && !browserVoice) return null;

  function browserSpeak() {
    if (!browserVoice) return toast.error(t("voice.err"));
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang === "en" ? "en-IN" : lang;
    window.speechSynthesis.speak(u);
  }

  async function listen() {
    if (!data?.text_to_speech) return browserSpeak();
    setBusy(true);
    try {
      const res = await apiFetch("/api/voice/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text.slice(0, 2000) }) });
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch {
      browserSpeak(); // the server voice failed or its allowance is used up: fall back to the device's voice
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button type="button" variant="outline" size="sm" loading={busy} onClick={listen} data-testid="listen-button">
      <Volume2 /> {t("voice.listen")}
    </Button>
  );
}
