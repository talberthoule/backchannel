import { useCallback, useRef, useState } from "react";

export interface SpeechTranscript {
  text: string;
  isFinal: boolean;
  timestamp: string;
}

/**
 * Robust speech recognition using Chrome's Web Speech API.
 *
 * Fixes for common issues:
 * - Saves interim text before restart so nothing gets lost
 * - Runs two overlapping recognizers to eliminate dead gaps during restart
 * - Auto-promotes long interim text to final after a timeout
 * - Captures ALL speech — both speakers, everything said
 */
export function useSpeechRecognition() {
  const [isListening, setIsListening] = useState(false);
  const activeRef = useRef(false);
  const onTranscriptRef = useRef<((t: SpeechTranscript) => void) | null>(null);

  // Track interim text so we can save it if recognition dies before finalizing
  const lastInterimRef = useRef("");
  const lastInterimTimeRef = useRef(0);
  const interimTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Dual recognizer refs for overlap strategy
  const primaryRef = useRef<any>(null);
  const backupRef = useRef<any>(null);

  const INTERIM_TIMEOUT_MS = 3000; // Promote interim to final after 3s without update

  function createRecognizer(): any {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return null;

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.maxAlternatives = 1;
    return recognition;
  }

  function flushInterim() {
    const text = lastInterimRef.current.trim();
    if (text && text.length > 2) {
      onTranscriptRef.current?.({
        text,
        isFinal: true,
        timestamp: new Date().toISOString(),
      });
    }
    lastInterimRef.current = "";
    lastInterimTimeRef.current = 0;
    if (interimTimerRef.current) {
      clearTimeout(interimTimerRef.current);
      interimTimerRef.current = null;
    }
  }

  function resetInterimTimer() {
    if (interimTimerRef.current) {
      clearTimeout(interimTimerRef.current);
    }
    interimTimerRef.current = setTimeout(() => {
      // If we have interim text that hasn't been finalized, promote it
      if (lastInterimRef.current.trim().length > 2) {
        flushInterim();
      }
    }, INTERIM_TIMEOUT_MS);
  }

  function wireRecognizer(recognition: any, label: string) {
    recognition.onresult = (event: any) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0].transcript.trim();
        if (!text) continue;

        if (result.isFinal) {
          // Clear any pending interim since we got a final
          lastInterimRef.current = "";
          if (interimTimerRef.current) {
            clearTimeout(interimTimerRef.current);
            interimTimerRef.current = null;
          }

          onTranscriptRef.current?.({
            text,
            isFinal: true,
            timestamp: new Date().toISOString(),
          });
        } else {
          // Track interim text and emit for live display
          lastInterimRef.current = text;
          lastInterimTimeRef.current = Date.now();
          resetInterimTimer();

          onTranscriptRef.current?.({
            text,
            isFinal: false,
            timestamp: new Date().toISOString(),
          });
        }
      }
    };

    recognition.onerror = (event: any) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      console.warn(`[${label}] Speech recognition error:`, event.error);
    };

    recognition.onend = () => {
      if (!activeRef.current) return;

      // Save any unflushed interim text before restart
      if (lastInterimRef.current.trim().length > 2) {
        flushInterim();
      }

      // Restart with a slight delay
      setTimeout(() => {
        if (!activeRef.current) return;
        try {
          recognition.start();
        } catch {
          // Already running or other issue — try creating a fresh one
          try {
            const fresh = createRecognizer();
            if (fresh) {
              wireRecognizer(fresh, label);
              fresh.start();
              if (label === "primary") primaryRef.current = fresh;
              else backupRef.current = fresh;
            }
          } catch {
            console.warn(`[${label}] Failed to restart speech recognition`);
          }
        }
      }, 100);
    };
  }

  const startListening = useCallback((onTranscript: (t: SpeechTranscript) => void) => {
    onTranscriptRef.current = onTranscript;
    activeRef.current = true;
    lastInterimRef.current = "";

    const primary = createRecognizer();
    if (!primary) {
      console.warn("Speech Recognition API not available");
      return;
    }

    wireRecognizer(primary, "primary");
    primary.start();
    primaryRef.current = primary;

    // Start backup recognizer with a delay to cover restart gaps
    setTimeout(() => {
      if (!activeRef.current) return;
      const backup = createRecognizer();
      if (backup) {
        wireRecognizer(backup, "backup");
        try {
          backup.start();
          backupRef.current = backup;
        } catch {
          // Chrome may not allow two simultaneous — that's okay, primary handles it
          backupRef.current = null;
        }
      }
    }, 500);

    setIsListening(true);
  }, []);

  const stopListening = useCallback(() => {
    activeRef.current = false;

    // Flush any remaining interim text
    if (lastInterimRef.current.trim().length > 2) {
      flushInterim();
    }

    if (primaryRef.current) {
      try { primaryRef.current.stop(); } catch {}
      primaryRef.current = null;
    }
    if (backupRef.current) {
      try { backupRef.current.stop(); } catch {}
      backupRef.current = null;
    }
    if (interimTimerRef.current) {
      clearTimeout(interimTimerRef.current);
      interimTimerRef.current = null;
    }

    setIsListening(false);
  }, []);

  return { startListening, stopListening, isListening };
}
