import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { uiHref } from "@/utils/uiHref";

export function MediaEvaluationSetupHint() {
  return (
    <Alert>
      <AlertTitle>No models are configured for this evaluation</AlertTitle>
      <AlertDescription>
        <p>
          Click a Model ID, choose Edit Settings, and add <code>{'"qos_probe": {}'}</code> to Model Info. Save the
          model, then reopen this dialog.
        </p>
        <a href={uiHref("models-and-endpoints")} target="_blank" rel="noopener noreferrer">
          Open model management
        </a>
      </AlertDescription>
    </Alert>
  );
}
