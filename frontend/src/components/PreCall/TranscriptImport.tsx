import { useRef, useState } from "react";
import * as api from "../../services/api";

interface Props {
  sessionId: string;
  onImported?: () => void;
}

export default function TranscriptImport({ sessionId, onImported }: Props) {
  const [status, setStatus] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const transcriptRef = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLInputElement>(null);

  const handleTranscript = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setStatus("");
    try {
      const result = await api.importTranscript(sessionId, file);
      setStatus(`Imported ${result.imported} segments from ${result.filename}`);
      onImported?.();
    } catch (err: any) {
      setStatus(`Error: ${err.message}`);
    } finally {
      setLoading(false);
      if (transcriptRef.current) transcriptRef.current.value = "";
    }
  };

  const handleAudio = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setStatus("Transcribing audio — this may take a moment...");
    try {
      const result = await api.importAudio(sessionId, file);
      setStatus(`Imported ${result.imported} segments from ${result.filename}`);
      onImported?.();
    } catch (err: any) {
      setStatus(`Error: ${err.message}`);
    } finally {
      setLoading(false);
      if (audioRef.current) audioRef.current.value = "";
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-4">
        {/* Transcript file import */}
        <div
          onClick={() => transcriptRef.current?.click()}
          className="cursor-pointer rounded-lg border-2 border-dashed border-brand-light-gray-1 p-4 text-center hover:border-brand-teal hover:bg-blue-50/30 transition-colors"
        >
          <p className="font-display text-sm font-semibold text-brand-dark-gray">
            Import Transcript
          </p>
          <p className="mt-1 font-body text-xs text-brand-mid-gray">
            .txt, .md, .docx
          </p>
          <input
            ref={transcriptRef}
            type="file"
            accept=".txt,.md,.docx"
            onChange={handleTranscript}
            className="hidden"
          />
        </div>

        {/* Audio file import */}
        <div
          onClick={() => audioRef.current?.click()}
          className="cursor-pointer rounded-lg border-2 border-dashed border-brand-light-gray-1 p-4 text-center hover:border-brand-amber hover:bg-orange-50/30 transition-colors"
        >
          <p className="font-display text-sm font-semibold text-brand-dark-gray">
            Import Audio
          </p>
          <p className="mt-1 font-body text-xs text-brand-mid-gray">
            .m4a, .mp3, .wav
          </p>
          <input
            ref={audioRef}
            type="file"
            accept=".m4a,.mp3,.wav,.ogg,.flac"
            onChange={handleAudio}
            className="hidden"
          />
        </div>
      </div>

      {/* Status message */}
      {(loading || status) && (
        <div className={`rounded-lg px-4 py-2 text-sm font-body ${
          loading
            ? "bg-blue-50 text-brand-teal"
            : status.startsWith("Error")
              ? "bg-red-50 text-red-600"
              : "bg-green-50 text-green-700"
        }`}>
          {loading && !status.startsWith("Error") ? (
            <span className="flex items-center gap-2">
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-brand-teal border-t-transparent" />
              {status || "Processing..."}
            </span>
          ) : (
            status
          )}
        </div>
      )}
    </div>
  );
}
