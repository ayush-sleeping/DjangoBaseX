const notes = {
  name: "notes",
  pages: {
    "": () => import("./notes-page"),
  },
  // The source (en) is required; other languages are optional and fall back to it key by key.
  messages: {
    en: () => import("./messages/en.json"),
    de: () => import("./messages/de.json"),
  },
};

export default notes;
