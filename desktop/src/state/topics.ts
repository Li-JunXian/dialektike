export interface TopicViewState {
  archived: boolean;
  query: string;
  busy: boolean;
}

/**
 * Preview fixtures are synchronous; native topic lists remain disabled until
 * the trusted sidecar returns the requested active/archived view.
 */
export function transitionTopicView(
  state: TopicViewState,
  archived: boolean,
  previewMode: boolean,
): TopicViewState {
  if (state.busy) return state;
  return {
    archived,
    query: "",
    busy: !previewMode,
  };
}
