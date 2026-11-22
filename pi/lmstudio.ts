// Registers whatever LM Studio's local server offers as the "lmstudio"
// provider, so a model downloaded there shows up in pi's /model without
// editing a list. LM Studio's own /api/v0 is used instead of /v1 because
// only it reports the model type and the context length it was loaded with.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BASE = "http://localhost:1234";

type LmsModel = {
  id: string;
  type: "llm" | "vlm" | "embeddings";
  state: "loaded" | "not-loaded";
  max_context_length: number;
  loaded_context_length?: number;
};

export default async function (pi: ExtensionAPI) {
  let models: LmsModel[];
  try {
    const res = await fetch(`${BASE}/api/v0/models`, { signal: AbortSignal.timeout(1000) });
    models = ((await res.json()) as { data: LmsModel[] }).data;
  } catch {
    return; // server not running; pi starts without the provider
  }

  pi.registerProvider("lmstudio", {
    baseUrl: `${BASE}/v1`,
    apiKey: "lm-studio",
    api: "openai-completions",
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      maxTokensField: "max_tokens",
    },
    models: models
      .filter((m) => m.type !== "embeddings")
      .map((m) => {
        // pi compacts against this, so it has to be what LM Studio actually
        // loaded, not what the model could take.
        const ctx = m.loaded_context_length ?? 8192;
        return {
          id: m.id,
          name: `${m.id} (LM Studio)`,
          reasoning: true,
          input: m.type === "vlm" ? ["text", "image"] : ["text"],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: ctx,
          maxTokens: Math.min(8192, Math.floor(ctx / 4)),
        };
      }),
  });
}
