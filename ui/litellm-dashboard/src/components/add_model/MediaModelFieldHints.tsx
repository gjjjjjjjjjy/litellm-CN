interface MediaModelFieldHintProps {
  mode: unknown;
}

export function AddMediaModelGuide() {
  return (
    <section
      aria-label="Audio and video setup"
      className="mt-2 mb-4 space-y-1 rounded-lg border bg-muted/30 p-3 text-sm"
    >
      <h3 className="font-medium">Audio and video setup</h3>
      <div className="space-y-1 text-muted-foreground">
        <p>
          Choose <code>/videos</code> for video, <code>/audio/speech</code> for speech synthesis, or{" "}
          <code>/audio/transcriptions</code> for transcription.
        </p>
        <p>
          In Advanced Settings, use Model Info for evaluation. Enter <code>{'{"qos_probe": {}}'}</code> for audio or
          text-to-video, or <code>{'{"qos_probe": {"image": true}}'}</code> for image-to-video.
        </p>
        <p>
          For speech models that need reference audio, enter{" "}
          <code className="break-all">{'{"prompt_audio_url": "https://example.com/reference.wav"}'}</code> in LiteLLM
          Params and replace the example URL.
        </p>
      </div>
    </section>
  );
}

export function MediaModelInfoHint({ mode }: MediaModelFieldHintProps) {
  switch (mode) {
    case "video_generation":
      return (
        <p className="mt-1 text-xs text-muted-foreground">
          Add <code>{'"qos_probe": {}'}</code> for text-to-video evaluation. For image-to-video, use{" "}
          <code>{'"qos_probe": {"image": true}'}</code>.
        </p>
      );
    case "audio_speech":
    case "audio_transcription":
      return (
        <p className="mt-1 text-xs text-muted-foreground">
          Add <code>{'"qos_probe": {}'}</code> to include this model in audio evaluations.
        </p>
      );
    default:
      return null;
  }
}

export function MediaModelParamsHint({ mode }: MediaModelFieldHintProps) {
  switch (mode) {
    case "audio_speech":
      return (
        <p className="mt-1 text-xs text-muted-foreground">
          For models that require reference audio, set <code>prompt_audio_url</code> to a direct audio link. F5-TTS also
          uses <code>prompt_text</code> for the reference transcript.
        </p>
      );
    case "video_generation":
    case "audio_transcription":
      return (
        <p className="mt-1 text-xs text-muted-foreground">
          Set <code>qos_probe</code> in Model Info to include this model in evaluations.
        </p>
      );
    default:
      return null;
  }
}
