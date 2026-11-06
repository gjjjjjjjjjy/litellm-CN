interface MediaModelFieldHintProps {
  mode: unknown;
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
