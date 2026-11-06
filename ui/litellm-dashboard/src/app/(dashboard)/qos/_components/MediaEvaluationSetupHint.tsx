import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { uiHref } from "@/utils/uiHref";

export function MediaEvaluationSetupHint() {
  const modelsHref = uiHref("models-and-endpoints");
  return (
    <Alert>
      <AlertTitle>No models are configured for this evaluation</AlertTitle>
      <AlertDescription>
        <p>
          For a new model, choose its mode and open Advanced Settings. For a deployed model, click its Model ID and
          choose Edit Settings.
        </p>
        <p>
          Add <code>{'"qos_probe": {}'}</code> to Model Info. Save the model, then reopen this dialog.
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <a href={`${modelsHref}?tab=add`} target="_blank" rel="noopener noreferrer">
            Add Model
          </a>
          <a href={modelsHref} target="_blank" rel="noopener noreferrer">
            Open model management
          </a>
        </div>
      </AlertDescription>
    </Alert>
  );
}
