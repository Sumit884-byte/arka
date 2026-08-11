export type Suggestion = {
  title: string;
  body: string;
};

export const chatSuggestions: Suggestion[] = [
  { title: "Check setup", body: "Run doctor and summarize anything I should fix." },
  { title: "Repo health", body: "Check repo health for this project." },
  { title: "Capabilities", body: "What can you do?" },
  { title: "Weather", body: "What's the weather in Bangalore?" },
];
